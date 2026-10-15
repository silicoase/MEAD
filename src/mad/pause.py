"""Pair-wide, quiescent pauses. In-flight work drains; nothing is replayed."""

import asyncio
import math
import time
from contextlib import asynccontextmanager
from datetime import timezone
from email.utils import parsedate_to_datetime


class PauseLimitExceeded(RuntimeError):
    pass


def new_account_reset_delay(error):
    """Recover explicit account and transient shared-provider-pool rate limits."""
    if getattr(error, "status_code", None) != 429:
        return None
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return None
    payload = body.get("error", body)
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    if not isinstance(metadata, dict) or metadata.get("limit_source") not in {
        "openrouter_new_account", "upstream_provider_shared_pool"
    }:
        return None
    raw_headers = metadata.get("headers", {})
    headers = (
        {str(k).lower(): v for k, v in raw_headers.items()} if isinstance(raw_headers, dict) else {}
    )
    response = getattr(error, "response", None)
    if response is not None:
        headers.update({k.lower(): v for k, v in response.headers.items()})
    delays = []
    try:
        delays.append(float(metadata["retry_after_seconds"]))
    except (KeyError, ValueError, TypeError):
        pass
    try:
        reset = float(headers["x-ratelimit-reset"])
        if reset > 100_000_000_000:
            reset /= 1000
        delays.append(reset - time.time())
    except (KeyError, ValueError, TypeError):
        pass
    try:
        retry = headers["retry-after"]
        try:
            delays.append(float(retry))
        except ValueError:
            date = parsedate_to_datetime(retry)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            delays.append(date.timestamp() - time.time())
    except (KeyError, ValueError, TypeError, OverflowError):
        pass
    # A stale/missing reset must not cause a tight loop. One second guards the boundary.
    future = [d for d in delays if math.isfinite(d) and d > 0]
    return max(future) + 1 if future else 60.0


class PairPause:
    def __init__(self, max_seconds=1800):
        self.max_seconds = max_seconds
        self.paused_seconds = 0.0
        self.frozen_at = None
        self.until = 0.0
        self.error = None
        self.recorders = set()
        self.environments = set()
        self.timers = set()
        self.active = 0
        self.open = asyncio.Event()
        self.open.set()
        self.idle = asyncio.Event()
        self.idle.set()
        self.admission = asyncio.Lock()  # FIFO admission, including across conditions.
        self.worker = None
        self.pause_count = 0

    def now(self, wall=None):
        wall = time.monotonic() if wall is None else wall
        frozen = wall - self.frozen_at if self.frozen_at is not None else 0
        return wall - self.paused_seconds - frozen

    def emit(self, kind, **data):
        for recorder in tuple(self.recorders):
            try:
                recorder.emit(kind, **data)
            except Exception as error:
                # Recovery must not strand containers or waiters if recording fails.
                self.error = RuntimeError(f"pause recording failed: {type(error).__name__}")

    def refresh_timers(self):
        for timeout, deadline in tuple(self.timers):
            if timeout.expired():
                continue
            timeout.reschedule(
                None
                if self.frozen_at is not None
                else asyncio.get_running_loop().time() + max(0, deadline - self.now())
            )

    async def wait_open(self):
        await self.open.wait()
        if self.error is not None:
            raise self.error

    @asynccontextmanager
    async def operation(self, *, cleanup=False):
        # Every tool and HTTP attempt enters once; retries re-enter as new admissions.
        async with self.admission:
            if cleanup:
                await self.open.wait()
            else:
                await self.wait_open()
            self.active += 1
            self.idle.clear()
        try:
            yield
        finally:
            self.active -= 1
            if not self.active:
                self.idle.set()

    @asynccontextmanager
    async def timeout(self, seconds):
        deadline = self.now() + seconds
        async with asyncio.timeout(None) as timer:
            entry = (timer, deadline)
            self.timers.add(entry)
            self.refresh_timers()
            try:
                yield
            finally:
                self.timers.discard(entry)

    async def sleep(self, seconds):
        """For stagger/ordinary backoff: elapsed active time, never wake into a freeze."""
        deadline = self.now() + seconds
        while self.now() < deadline or not self.open.is_set():
            await self.wait_open()
            await asyncio.sleep(min(0.05, max(0, deadline - self.now())))
        await self.wait_open()

    def request(self, seconds, *, model, agent, source_run=None):
        self.until = max(self.until, time.monotonic() + seconds)
        self.open.clear()
        self.emit(
            "cohort_pause_requested",
            source_model=model,
            source_agent=agent,
            source_run=source_run,
            reset_wait_seconds=seconds,
            active_operations=self.active,
        )
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self.cooldown())

    async def cooldown(self):
        try:
            await self.idle.wait()
            remaining = self.until - time.monotonic()
            if self.error is not None:
                return
            if remaining <= 0:
                return  # Draining already spanned the window; exclude no active work time.
            if self.paused_seconds + remaining > self.max_seconds:
                self.error = PauseLimitExceeded("matched-pair pause budget exhausted")
                self.emit("cohort_pause_limit", max_pause_seconds=self.max_seconds)
                return
            # Stop detached sandbox processes too; suspension overhead remains active time.
            suspending = asyncio.gather(
                *(env.freeze() for env in tuple(self.environments)), return_exceptions=True
            )
            try:
                outcomes = await asyncio.shield(suspending)
            except asyncio.CancelledError:
                # A late Docker pause must finish before its matching unpause is sent.
                await suspending
                raise
            if any(isinstance(outcome, BaseException) for outcome in outcomes):
                raise RuntimeError("sandbox suspension failed")
            self.frozen_at = time.monotonic()
            self.pause_count += 1
            self.refresh_timers()
            self.emit(
                "cohort_pause_started", pause_index=self.pause_count, reset_wait_seconds=remaining
            )
            while self.error is None and self.until > time.monotonic():
                remaining = self.until - time.monotonic()
                frozen = time.monotonic() - self.frozen_at
                if self.paused_seconds + frozen + remaining > self.max_seconds:
                    self.error = PauseLimitExceeded("matched-pair pause budget exhausted")
                    self.emit("cohort_pause_limit", max_pause_seconds=self.max_seconds)
                    break
                await asyncio.sleep(min(remaining, 0.05))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.error = RuntimeError(f"coordinated pause failed: {type(error).__name__}")
        finally:
            # Resume accounting before any container can compute during thaw overhead.
            duration = 0.0
            if self.frozen_at is not None:
                duration = time.monotonic() - self.frozen_at
                self.paused_seconds += duration
                self.frozen_at = None
                self.refresh_timers()
                self.emit(
                    "cohort_pause_clock_resumed",
                    pause_index=self.pause_count,
                    pause_seconds=duration,
                )
            try:
                outcomes = await asyncio.gather(
                    *(env.thaw() for env in tuple(self.environments)), return_exceptions=True
                )
                if any(isinstance(outcome, BaseException) for outcome in outcomes):
                    raise RuntimeError("sandbox resumption failed")
            except Exception as error:
                self.error = RuntimeError(f"sandbox resume failed: {type(error).__name__}")
            if duration:
                self.emit(
                    "cohort_pause_ended",
                    pause_index=self.pause_count,
                    pause_seconds=duration,
                    total_pause_seconds=self.paused_seconds,
                )
            self.open.set()

    async def abort(self):
        self.error = RuntimeError("coordinated pause cancelled")
        await self.close()

    async def close(self):
        if self.worker is not None and not self.worker.done():
            if not self.worker.cancelling():
                self.worker.cancel()
            await asyncio.shield(asyncio.gather(self.worker, return_exceptions=True))

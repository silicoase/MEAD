import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from mad.config import RolloutConfig
from mad.pause import PairPause, PauseLimitExceeded, new_account_reset_delay
from mad.recording import Recorder
from mad.task import OptimizationTask
from mad.tools import ToolService


def error(source="openrouter_new_account", status=429, **headers):
    return SimpleNamespace(
        status_code=status,
        body={"error": {"metadata": {"limit_source": source, "headers": headers}}},
    )


def test_supported_rate_limits_and_real_reset(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000)
    assert new_account_reset_delay(error(**{"X-RateLimit-Reset": "1700000030000"})) == 31
    assert new_account_reset_delay(error(**{"X-RateLimit-Reset": "1700000030"})) == 31
    assert new_account_reset_delay(error(**{"Retry-After": "12"})) == 13
    assert new_account_reset_delay(error(**{"X-RateLimit-Reset": "999"})) == 60
    assert new_account_reset_delay(error(source="upstream")) is None
    assert new_account_reset_delay(error(source="upstream_provider_shared_pool", **{"Retry-After": "28"})) == 29
    assert new_account_reset_delay(error(source="upstream_provider_shared_pool")) == 60
    provider = error(source="upstream_provider_shared_pool")
    provider.body["error"]["metadata"]["retry_after_seconds"] = 61
    assert new_account_reset_delay(provider) == 62
    assert new_account_reset_delay(error(status=503)) is None
    assert new_account_reset_delay(SimpleNamespace(status_code=429, body=None)) is None
    assert new_account_reset_delay(error(**{"Retry-After": "nan"})) == 60


async def wait_frozen(pause):
    for _ in range(200):
        if pause.frozen_at is not None:
            return
        await asyncio.sleep(0.001)
    raise AssertionError("pause did not freeze")


async def test_drains_then_freezes_and_blocks_peer_work(tmp_path):
    pause = PairPause(1)
    dirs = [tmp_path / c for c in ["control", "interact"]]
    for d in dirs:
        d.mkdir()
    rs = [Recorder(d, pause) for d in dirs]
    entered, release = asyncio.Event(), asyncio.Event()
    order = []

    async def admitted_tool():
        async with pause.operation():
            entered.set()
            await release.wait()
            order.append("in-flight write")
        await pause.wait_open()

    t = asyncio.create_task(admitted_tool())
    await entered.wait()
    pause.request(0.10, model="test/model", agent=0)

    async def queued_tool():
        async with pause.operation():
            order.append("queued experiment")

    q = asyncio.create_task(queued_tool())
    await asyncio.sleep(0.02)
    assert pause.frozen_at is None  # Draining counts as active time.
    assert order == []
    release.set()
    await wait_frozen(pause)
    before = pause.now()
    for r in rs:
        r.emit("clock_probe")
    await asyncio.sleep(0.02)
    assert abs(pause.now() - before) < 0.005
    assert order == ["in-flight write"]
    await asyncio.gather(t, q)
    assert order == ["in-flight write", "queued experiment"]
    assert 0.05 < pause.paused_seconds < 0.15
    for r in rs:
        r.emit("after")
        r.close()
        es = [json.loads(line) for line in (r.directory / "events.jsonl").read_text().splitlines()]
        assert sum(e["kind"] == "cohort_pause_started" for e in es) == 1
        assert sum(e["kind"] == "cohort_pause_ended" for e in es) == 1
        assert (
            abs(es[-1]["elapsed_seconds"] - es[-1]["active_elapsed_seconds"] - pause.paused_seconds)
            < 0.005
        )
    await pause.close()


async def test_active_deadline_survives_freeze_and_still_expires():
    p = PairPause(1)
    async with p.timeout(0.05):
        p.request(0.10, model="test/model", agent=0)
        await p.wait_open()
        await asyncio.sleep(0.01)
    assert p.paused_seconds >= 0.09
    with pytest.raises(TimeoutError):
        async with p.timeout(0.01):
            await asyncio.sleep(0.03)
    await p.close()


async def test_pause_budget_is_pair_wide_and_fails_closed():
    p = PairPause(0.01)
    p.request(0.05, model="test/model", agent=0)
    with pytest.raises(PauseLimitExceeded):
        await p.wait_open()
    with pytest.raises(PauseLimitExceeded):
        async with p.operation():
            pytest.fail("work admitted after exhaustion")
    await p.close()


async def test_cancellation_and_late_reset_extension_do_not_deadlock():
    p = PairPause(1)
    p.request(0.03, model="test/model", agent=0)
    await wait_frozen(p)
    p.request(0.06, model="test/model", agent=1)

    async def queued():
        async with p.operation():
            pass

    t = asyncio.create_task(queued())
    await asyncio.sleep(0.005)
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    await p.wait_open()
    assert p.paused_seconds >= 0.05
    async with p.operation():
        pass
    await p.close()


async def test_pause_preserves_noise_scores_writes_and_budgets(tmp_path):
    class Environment:
        def __init__(self, cfg):
            self.config = cfg
            self.author_ids = ["a", "b"]
            self.published = []
            self.writes = []

        async def publish_run(self, agent, record):
            self.published.append((agent, record["observed"]))

        async def file(self, agent, operation, **args):
            self.writes.append((agent, operation, args))
            return {"written": True}

    async def episode(label, freeze):
        d = tmp_path / label
        d.mkdir()
        cfg = RolloutConfig(agents=2, experiment_budget=2)
        p = PairPause(1) if freeze else None
        r = Recorder(d, p)
        env = Environment(cfg)
        task = OptimizationTask(cfg, env, r)
        service = ToolService(task, env, r, 2)
        params = [0.4] * 8
        for agent in range(2):
            await service.call(agent, "experiment", parameters=params)
        if p:
            p.request(0.03, model="test/model", agent=0)
        await asyncio.gather(
            *(
                service.call(i, "write_file", path=f"/lab/notes/{i}", content="result")
                for i in range(2)
            )
        )
        for agent in range(2):
            await service.call(agent, "experiment", parameters=params)
            await service.call(agent, "submit", parameters=params)
        result = ([task.report(i) for i in range(2)], env.published, env.writes)
        r.close()
        if p:
            await p.close()
        return result

    assert await episode("baseline", False) == await episode("paused", True)


@pytest.mark.parametrize("population", [1, 10])
@pytest.mark.parametrize("limit_source", ["openrouter_new_account", "upstream_provider_shared_pool"])
async def test_http_recovery_preserves_both_conditions_and_never_replays_tools(
    tmp_path, monkeypatch, population, limit_source
):
    import httpx2 as httpx
    from openai import AsyncOpenAI

    from mad import harness as harness_module
    from mad.harness import OpenRouterHarness

    real_delay = harness_module.new_account_reset_delay
    monkeypatch.setattr(
        harness_module,
        "new_account_reset_delay",
        lambda e: 0.03 if real_delay(e) is not None else None,
    )

    class Environment:
        def __init__(self, cfg):
            self.config = cfg
            self.author_ids = [f"author-{i}" for i in range(cfg.agents)]
            self.writes = 0
            self.records = []

        async def file(self, agent, operation, **args):
            if operation == "write":
                self.writes += 1
            return {"ok": True}

        async def publish_run(self, agent, record):
            self.records.append((agent, record["parameters"], record["observed"]))

    async def matched(label, inject):
        pause = PairPause(1)
        failures = 0
        serial = 0
        recorders = []
        results = []

        async def condition(name):
            nonlocal failures, serial
            directory = tmp_path / f"{label}-{name}"
            directory.mkdir()
            cfg = RolloutConfig(
                agents=population,
                experiment_budget=2,
                max_turns=5,
                harness={
                    "kind": "openrouter",
                    "coordinated_pause": True,
                    "request_retries": 0,
                    "routes": [{"model": "test/model"}],
                },
            )
            recorder = Recorder(directory, pause)
            recorders.append(recorder)
            env = Environment(cfg)
            task = OptimizationTask(cfg, env, recorder)
            service = ToolService(task, env, recorder, population)

            async def handle(request):
                nonlocal failures, serial
                assert pause.frozen_at is None
                body = json.loads(request.content)
                if inject and name == "control" and failures < 2:
                    failures += 1
                    return httpx.Response(
                        429,
                        json={
                            "error": {
                                "message": "temporary",
                                "code": 429,
                                "metadata": {
                                    "limit_source": limit_source,
                                    "headers": {"Retry-After": "1"},
                                },
                            }
                        },
                    )
                await asyncio.sleep(0.005)  # Peer response drains without being acted on.
                turn = sum(m["role"] == "tool" for m in body["messages"])
                tool, args = [
                    ("read_file", {"path": "/workspace/task.md"}),
                    ("experiment", {"parameters": [0.4] * 8}),
                    ("write_file", {"path": "/lab/notes/note.md", "content": "result"}),
                    ("experiment", {"parameters": [0.6] * 8}),
                    ("submit", {"parameters": [0.6] * 8}),
                ][turn]
                serial += 1
                return httpx.Response(
                    200,
                    json={
                        "id": f"gen-{serial}",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "test/model",
                        "provider": "Mock",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "tool_calls",
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": f"call-{serial}",
                                            "type": "function",
                                            "function": {
                                                "name": tool,
                                                "arguments": json.dumps(args),
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 2,
                            "completion_tokens": 3,
                            "total_tokens": 5,
                            "cost": 0.001,
                        },
                    },
                )

            async with AsyncOpenAI(
                api_key="dummy",
                base_url="https://openrouter.ai/api/v1",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
            ) as client:
                h = OpenRouterHarness(cfg, service, recorder, client=client)
                async with pause.timeout(5):
                    completed = await asyncio.gather(
                        *(h.run(i, task.instructions(2)) for i in range(population))
                    )
                await h.close()
            results.append(
                (
                    name,
                    [r["reason"] for r in completed],
                    [task.report(i) for i in range(population)],
                    env.writes,
                    sorted(env.records),
                )
            )

        await asyncio.gather(condition("control"), condition("interact"))
        for r in recorders:
            r.close()
        assert 1 <= pause.pause_count <= 2 if inject else pause.pause_count == 0
        for r in recorders:
            es = [
                json.loads(line) for line in (r.directory / "events.jsonl").read_text().splitlines()
            ]
            assert sum(e["kind"] == "model_request" for e in es) == 5 * population
            assert sum(e["kind"] == "experiment_started" for e in es) == 2 * population
            assert sum(e["kind"] == "submission" for e in es) == population
            assert sum(e["kind"] == "cohort_pause_started" for e in es) == pause.pause_count
            frozen = False
            for e in es:
                if e["kind"] == "cohort_pause_started":
                    frozen = True
                if e["kind"] == "cohort_pause_ended":
                    frozen = False
                if frozen:
                    assert e["kind"] not in {
                        "tool_called",
                        "experiment_started",
                        "submission",
                        "provider_request_started",
                    }
        await pause.close()
        return sorted(results)

    assert await matched("baseline", False) == await matched("recovery", True)


async def test_physical_suspension_and_thaw_on_cancel():
    p = PairPause(1)
    changes = []

    class Sandbox:
        async def freeze(self):
            assert p.frozen_at is None
            changes.append("freeze")

        async def thaw(self):
            changes.append("thaw")

    p.environments.add(Sandbox())
    p.request(0.10, model="test/model", agent=0)
    await wait_frozen(p)
    assert changes == ["freeze"]
    await p.close()
    assert changes == ["freeze", "thaw"]
    assert p.open.is_set()


async def test_failed_suspension_thaws_and_fails_closed():
    p = PairPause(1)
    changes = []

    class Sandbox:
        async def freeze(self):
            changes.append("freeze")
            raise RuntimeError("engine unavailable")

        async def thaw(self):
            changes.append("thaw")

    p.environments.add(Sandbox())
    p.request(0.10, model="test/model", agent=0)
    with pytest.raises(RuntimeError, match="coordinated pause failed"):
        await p.wait_open()
    assert changes == ["freeze", "thaw"]
    assert p.paused_seconds == 0
    await p.close()


async def test_thaw_overhead_is_active_not_free_computation():
    p = PairPause(1)

    class Sandbox:
        async def freeze(self):
            pass

        async def thaw(self):
            assert p.frozen_at is None
            before = p.now()
            await asyncio.sleep(0.02)
            assert p.now() - before >= 0.015

    p.environments.add(Sandbox())
    p.request(0.03, model="test/model", agent=0)
    await p.wait_open()
    assert 0.02 < p.paused_seconds < 0.05
    await p.close()


async def test_concurrent_abort_unblocks_waiters_and_thaws_once():
    p = PairPause(1)
    changes = []

    class Sandbox:
        async def freeze(self):
            changes.append("freeze")

        async def thaw(self):
            await asyncio.sleep(0.01)
            changes.append("thaw")

    p.environments.add(Sandbox())
    p.request(0.5, model="test/model", agent=0)
    await wait_frozen(p)
    await asyncio.gather(p.abort(), p.abort())
    assert changes == ["freeze", "thaw"]
    with pytest.raises(RuntimeError, match="cancelled"):
        await p.wait_open()


@pytest.mark.docker
async def test_real_sandbox_background_work_stops_during_freeze():
    from mad.environment import DockerEnvironment

    cfg = RolloutConfig(agents=2)
    env = DockerEnvironment(cfg)
    p = PairPause(3)
    try:
        await env.start(["pause infrastructure check"] * 2)
        await env.stop_agent(1)  # Finished agents must not break suspension of their peers.
        p.environments.add(env)
        background = (
            "import pathlib,time\n"
            "for i in range(1000):\n"
            " pathlib.Path('/workspace/counter').write_text(str(i))\n"
            " time.sleep(.03)\n"
        )
        code = (
            "import subprocess\n"
            f'subprocess.Popen(["python", "-c", {background!r}], '
            "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            'print("detached check started")'
        )
        result = await env.python(0, code)
        assert result["exit_code"] == 0
        await asyncio.sleep(0.1)

        async def counter():
            raw = await env.trusted_python(
                "from pathlib import Path\nprint(Path('/state/work/0/counter').read_text())", {}
            )
            return raw.strip()

        p.request(1.5, model="test/model", agent=0)
        async with asyncio.timeout(3):
            while p.frozen_at is None:
                await asyncio.sleep(0.01)
        before = await counter()
        await asyncio.sleep(0.15)
        assert await counter() == before
        await p.wait_open()
        await asyncio.sleep(0.15)
        assert await counter() != before
    finally:
        await p.close()
        await env.stop_agent(0)
        await env.close()


async def test_partial_suspension_failure_waits_for_late_peer_before_thaw():
    p = PairPause(1)
    suspended = False

    class SlowSandbox:
        async def freeze(self):
            nonlocal suspended
            await asyncio.sleep(0.02)
            suspended = True

        async def thaw(self):
            assert suspended

    class BrokenSandbox:
        async def freeze(self):
            raise RuntimeError("failed engine")

        async def thaw(self):
            assert suspended

    p.environments.update([SlowSandbox(), BrokenSandbox()])
    p.request(0.1, model="test/model", agent=0)
    with pytest.raises(RuntimeError, match="coordinated pause failed"):
        await p.wait_open()
    await p.close()


async def test_cancel_during_suspension_does_not_leave_late_frozen_container():
    p = PairPause(1)
    entered = asyncio.Event()
    changes = []

    class Sandbox:
        async def freeze(self):
            entered.set()
            await asyncio.sleep(0.02)
            changes.append("freeze completed")

        async def thaw(self):
            changes.append("thaw")

    p.environments.add(Sandbox())
    p.request(0.2, model="test/model", agent=0)
    await entered.wait()
    await p.abort()
    assert changes == ["freeze completed", "thaw"]


async def test_recording_failure_fails_closed_and_releases_waiters():
    class BrokenRecorder:
        def emit(self, *args, **kwargs):
            raise OSError("disk unavailable")

    pause = PairPause(1)
    pause.recorders.add(BrokenRecorder())
    pause.request(0.01, model="test", agent=0)
    with pytest.raises(RuntimeError, match="recording failed"):
        await asyncio.wait_for(pause.wait_open(), 1)
    assert pause.frozen_at is None
    await pause.close()


async def test_cleanup_waits_for_thaw_and_runs_even_after_pause_failure():
    p = PairPause(1)
    p.request(0.03, model="test", agent=0)
    await wait_frozen(p)
    cleaned = False

    async def cleanup():
        nonlocal cleaned
        async with p.operation(cleanup=True):
            assert p.frozen_at is None
            cleaned = True

    job = asyncio.create_task(cleanup())
    await asyncio.sleep(0.005)
    assert not cleaned
    await job
    p.error = RuntimeError("recovery failed")
    async with p.operation(cleanup=True):
        assert p.active == 1
    with pytest.raises(RuntimeError, match="recovery failed"):
        async with p.operation():
            pass
    await p.close()

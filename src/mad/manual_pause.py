"""Accounting for an operator pause taken at a fully quiescent recovery checkpoint."""

import time


def credit_relocation_pause(pause, *, started_monotonic, started_wall):
    """Keep operator downtime separate from the bounded API-recovery allowance.

    This does not resume containers or modify agents, budgets, noise or scoring.
    Caller must hold the pilot stopped at an already-frozen checkpoint.
    """
    if pause.frozen_at is None or pause.open.is_set() or pause.active or pause.error:
        raise RuntimeError("manual credit requires a healthy, fully frozen cohort")
    credits = getattr(pause, "manual_pause_credits", {})
    if started_monotonic in credits:
        return credits[started_monotonic]
    clock_seconds = max(0.0, time.monotonic() - started_monotonic)
    wall_seconds = max(0.0, time.time() - started_wall)
    sleep_seconds = max(0.0, wall_seconds - clock_seconds)
    result = dict(
        reason="operator-requested laptop relocation",
        manual_pause_clock_seconds=clock_seconds,
        manual_pause_wall_seconds=wall_seconds,
        system_sleep_seconds=sleep_seconds,
        api_pause_allowance_before=pause.max_seconds,
        api_pause_allowance_after=pause.max_seconds + clock_seconds,
    )
    # The active clock already excludes this frozen interval. Credit only the
    # operator portion against the API cap; leave the natural API pause charged.
    pause.max_seconds += clock_seconds
    # macOS uptime can stop during sleep, while the provider's reset clock keeps
    # advancing. Correct that existing reset deadline without adding a new wait.
    pause.until -= sleep_seconds
    # Preserve real wall-time plots across sleep without moving the active clock.
    for recorder in pause.recorders:
        recorder.started -= sleep_seconds
    credits[started_monotonic] = result
    pause.manual_pause_credits = credits
    pause.emit("manual_pause_ended", **result)
    if pause.error:
        raise pause.error
    return result

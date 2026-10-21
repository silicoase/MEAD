from types import SimpleNamespace

import pytest

from mad.manual_pause import credit_relocation_pause


@pytest.mark.parametrize("sleep_seconds", [0, 25])
def test_manual_credit_preserves_api_allowance_and_active_clock(monkeypatch, sleep_seconds):
    monkeypatch.setattr("mad.manual_pause.time.monotonic", lambda: 1000)
    monkeypatch.setattr("mad.manual_pause.time.time", lambda: 100 + sleep_seconds)
    events = []
    recorder = SimpleNamespace(started=900, active_started=900)
    pause = SimpleNamespace(
        frozen_at=990,
        open=SimpleNamespace(is_set=lambda: False),
        active=0,
        error=None,
        max_seconds=1800,
        until=1010,
        recorders=[recorder],
        emit=lambda kind, **kwargs: events.append((kind, kwargs)),
    )
    credit = credit_relocation_pause(pause, started_monotonic=995, started_wall=95)
    assert credit["manual_pause_clock_seconds"] == 5
    assert pause.max_seconds == 1805
    assert pause.until == 1010 - sleep_seconds
    assert recorder.started == 900 - sleep_seconds
    assert recorder.active_started == 900
    # Natural API freeze is 5 seconds; the extra 5 is operator downtime.
    assert pause.max_seconds - (1000 - pause.frozen_at) == 1800 - 5
    assert credit_relocation_pause(pause, started_monotonic=995, started_wall=95) == credit
    assert pause.max_seconds == 1805
    assert len(events) == 1


def test_manual_credit_rejects_unfrozen_work():
    pause = SimpleNamespace(frozen_at=None)
    with pytest.raises(RuntimeError, match="fully frozen"):
        credit_relocation_pause(pause, started_monotonic=0, started_wall=0)

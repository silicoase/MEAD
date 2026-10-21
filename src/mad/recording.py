import json
import time
from datetime import datetime, timezone
from pathlib import Path


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False, default=json_default) + "\n")


class Recorder:
    def __init__(self, directory: Path, pause=None):
        self.directory = directory
        self.sequence = 0
        self.started = time.monotonic()
        self.pause = pause
        self.active_started = pause.now(self.started) if pause else self.started
        if pause:
            pause.recorders.add(self)
        self.events = (directory / "events.jsonl").open("a", encoding="utf-8")

    def emit(self, kind: str, agent: int | None = None, **data):
        self.sequence += 1
        wall = time.monotonic()
        event = dict(
            sequence=self.sequence,
            timestamp=timestamp(),
            elapsed_seconds=wall - self.started,
            kind=kind,
            agent=agent,
            **data,
        )
        if self.pause:
            event["active_elapsed_seconds"] = self.pause.now(wall) - self.active_started
            event["paused_seconds"] = event["elapsed_seconds"] - event["active_elapsed_seconds"]
        self.events.write(json.dumps(event, allow_nan=False, default=json_default) + "\n")
        self.events.flush()

    def close(self):
        if self.pause:
            self.pause.recorders.discard(self)
        self.events.close()

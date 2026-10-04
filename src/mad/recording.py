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
    def __init__(self, directory: Path):
        self.directory = directory
        self.sequence = 0
        self.started = time.monotonic()
        self.events = (directory / "events.jsonl").open("a", encoding="utf-8")

    def emit(self, kind: str, agent: int | None = None, **data):
        self.sequence += 1
        event = dict(
            sequence=self.sequence,
            timestamp=timestamp(),
            elapsed_seconds=time.monotonic() - self.started,
            kind=kind,
            agent=agent,
            **data,
        )
        self.events.write(json.dumps(event, allow_nan=False, default=json_default) + "\n")
        self.events.flush()

    def close(self):
        self.events.close()

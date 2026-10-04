import math
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HarnessConfig(StrictModel):
    kind: Literal["openai", "scripted"] = "openai"
    model: str = "gpt-4.1-mini"
    reasoning_summary: Literal["auto", "concise", "detailed"] | None = None


class TaskConfig(StrictModel):
    kind: Literal["synthetic"] = "synthetic"
    dimensions: int = Field(default=8, ge=3, le=100)
    objective_seed: int = 42
    noise_seed: int = 123
    noise_std: float = Field(default=0.1, ge=0)
    lower: float = 0
    upper: float = 1
    instructions_file: Path | None = None
    initial_files: dict[str, Path] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounds(self):
        if self.lower >= self.upper:
            raise ValueError("lower must be less than upper")
        return self


class EnvironmentConfig(StrictModel):
    image: str = "mad-python:local"
    python_timeout_seconds: float = Field(default=20, gt=0, le=300)
    memory: str = "512m"
    cpus: float = Field(default=1, gt=0)
    pids_limit: int = Field(default=64, ge=16)


class RolloutConfig(StrictModel):
    agents: int = Field(default=3, ge=1, le=1000)
    experiment_budget: int = Field(default=8, ge=0)
    max_turns: int = Field(default=40, ge=1)
    timeout_seconds: float = Field(default=600, gt=0)
    runs_visibility: Literal["own", "all"] = "all"
    notes_visibility: Literal["own", "all"] = "all"
    note_author_headers: bool = True
    note_timestamps: bool = False
    experiment_duration_seconds: float = Field(default=0, ge=0)
    start_offsets_seconds: list[float] = Field(default_factory=list)
    tools: list[
        Literal[
            "experiment",
            "submit",
            "list_files",
            "read_file",
            "write_file",
            "append_file",
            "search_files",
            "python",
            "wait",
        ]
    ] = Field(
        default_factory=lambda: [
            "experiment",
            "submit",
            "list_files",
            "read_file",
            "write_file",
            "append_file",
            "search_files",
            "python",
            "wait",
        ]
    )
    harness: HarnessConfig = Field(default_factory=HarnessConfig)
    task: TaskConfig = Field(default_factory=TaskConfig)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)

    @model_validator(mode="after")
    def offsets(self):
        if "submit" not in self.tools or len(set(self.tools)) != len(self.tools):
            raise ValueError("tools must include submit and contain no duplicates")
        if not self.start_offsets_seconds:
            self.start_offsets_seconds = [0.0] * self.agents
        if len(self.start_offsets_seconds) != self.agents:
            raise ValueError("provide one start offset per agent")
        if any(x < 0 or not math.isfinite(x) for x in self.start_offsets_seconds):
            raise ValueError("start offsets must be finite and nonnegative")
        return self


def load_config(path: Path) -> RolloutConfig:
    config = RolloutConfig.model_validate(tomllib.loads(path.read_text()))
    if config.task.instructions_file:
        config.task.instructions_file = (path.parent / config.task.instructions_file).resolve()
    config.task.initial_files = {
        name: (path.parent / source).resolve() for name, source in config.task.initial_files.items()
    }
    return config

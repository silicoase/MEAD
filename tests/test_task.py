import asyncio
import json

import pytest
from pydantic import ValidationError

from mad.config import RolloutConfig, TaskConfig, load_config
from mad.recording import Recorder
from mad.task import OptimizationTask, SyntheticObjective


class Publisher:
    def __init__(self, agents):
        from uuid import uuid4

        self.author_ids = [uuid4().hex for _ in range(agents)]
        self.records = []

    async def publish_run(self, agent, record):
        self.records.append((agent, dict(record)))


def make_task(tmp_path, **kwargs):
    config = RolloutConfig(**kwargs)
    recorder = Recorder(tmp_path)
    return OptimizationTask(config, Publisher(config.agents), recorder), recorder


def test_config_rejects_unknown_invalid_and_mismatched_offsets(tmp_path):
    with pytest.raises(ValidationError):
        RolloutConfig(agents=2, start_offsets_seconds=[0])
    with pytest.raises(ValidationError):
        RolloutConfig(agents=0)
    with pytest.raises(ValidationError):
        RolloutConfig(notes_visibility="everyone")
    with pytest.raises(ValidationError):
        RolloutConfig(typo_budget=3)
    with pytest.raises(ValidationError):
        RolloutConfig(tools=["experiment"])
    with pytest.raises(ValidationError):
        RolloutConfig(tools=["submit", "submit"])
    with pytest.raises(ValidationError):
        TaskConfig(lower=2, upper=1)
    source = tmp_path / "config.toml"
    source.write_text('[task]\ninstructions_file = "task.md"\n')
    assert load_config(source).task.instructions_file == tmp_path / "task.md"


def test_function_generation_validation_and_irrelevant_parameter():
    config = TaskConfig()
    a, b = SyntheticObjective(config), SyntheticObjective(config)
    x = [0.5] * config.dimensions
    assert a.evaluate(x) == b.evaluate(x)
    assert a.evaluate(x) != SyntheticObjective(TaskConfig(objective_seed=43)).evaluate(x)
    x[-1] = 0.1
    assert a.evaluate(x) == b.evaluate([0.5] * config.dimensions)
    for invalid in ([0.5], [float("nan")] * 8, [True] * 8, [2.0] * 8):
        with pytest.raises(ValueError):
            a.evaluate(invalid)


async def test_budget_serializes_concurrent_calls_and_invalid_calls_are_free(tmp_path):
    task, recorder = make_task(tmp_path, agents=1, experiment_budget=1)
    try:
        with pytest.raises(ValueError):
            await task.experiment(0, [0.5])
        outcomes = await asyncio.gather(
            task.experiment(0, [0.5] * 8), task.experiment(0, [0.5] * 8), return_exceptions=True
        )
        assert sum(isinstance(x, dict) for x in outcomes) == 1
        assert task.report(0)["experiments_used"] == 1
        # Unmeasured submission still works after budget exhaustion.
        assert task.submit(0, [0.3] * 8) == {"submitted": True}
        assert task.report(0)["true_objective"] == task.objective.evaluate([0.3] * 8)
        with pytest.raises(ValueError):
            task.submit(0, [0.1] * 8)
        with pytest.raises(ValueError):
            await task.experiment(0, [0.1] * 8)
    finally:
        recorder.close()


async def test_noise_repeats_independently_and_is_seeded_per_agent(tmp_path):
    results = []
    for name in ("one", "two"):
        directory = tmp_path / name
        directory.mkdir()
        task, recorder = make_task(directory, agents=2, experiment_budget=2)
        try:
            a = await task.experiment(0, [0.5] * 8)
            b = await task.experiment(1, [0.5] * 8)
            c = await task.experiment(0, [0.5] * 8)
            results.append([a["observed"], b["observed"], c["observed"]])
            assert len(set(results[-1])) == 3
            assert task.report(0)["duplicate_experiments"] == 1
        finally:
            recorder.close()
    assert results[0] == results[1]


async def test_cancelled_experiment_consumes_budget_and_preserves_event(tmp_path):
    task, recorder = make_task(
        tmp_path, agents=1, experiment_budget=1, experiment_duration_seconds=10
    )
    try:
        pending = asyncio.create_task(task.experiment(0, [0.5] * 8))
        await asyncio.sleep(0.01)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert task.report(0)["experiments_used"] == 1
        assert task.report(0)["experiments_completed"] == 0
        assert task.report(0)["parameters"] is None
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        assert events[0]["kind"] == "experiment_started"
    finally:
        recorder.close()

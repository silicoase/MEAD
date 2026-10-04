import json
from pathlib import Path

import pytest

from mad import experiment

SPEC = Path(__file__).resolve().parents[1] / "experiments/swarm-hackathon-demo/experiment.toml"


def test_real_experiment_is_matched_and_uses_fresh_seeds():
    plan = experiment.validate_experiment(SPEC)
    assert len(plan["runs"]) == 60
    assert len({r["config"] for r in plan["runs"]}) == 1
    assert sum(run["agents"] for run in plan["runs"]) == 240
    for repetition in range(1, 21):
        trio = [r for r in plan["runs"] if r["repetition"] == repetition]
        assert {r["condition"] for r in trio} == {"control", "aware", "interact"}
        assert {r["objective_seed"] for r in trio} == {43 + repetition}
        assert {r["noise_seed"] for r in trio} == {124 + repetition}


def make_spec(tmp_path):
    (tmp_path / "experiment.toml").write_text("""name = "test-batch"
conditions = ["control", "aware"]
repetitions = 2
config_file = "config.toml"
concurrent_runs = 2
objective_seed_start = 44
noise_seed_start = 125
[prompts]
control = "control.txt"
aware = "aware.txt"
""")
    (tmp_path / "config.toml").write_text("""agents = 1
[harness]
kind = "scripted"
""")
    for c in ("control", "aware"):
        (tmp_path / f"{c}.txt").write_text(c)
    return tmp_path / "experiment.toml"


def test_rejects_missing_condition_prompt(tmp_path):
    path = make_spec(tmp_path)
    (tmp_path / "aware.txt").unlink()
    with pytest.raises(ValueError, match="prompt files"):
        experiment.validate_experiment(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_batch_snapshot_statuses_and_failure_stop(tmp_path, monkeypatch, fail):
    inputs = tmp_path / "definitions"
    inputs.mkdir()
    spec = make_spec(inputs)
    (inputs / ".env").write_text("SECRET=never-copy-me")
    calls = []

    async def rollout(config, directory):
        directory.mkdir()
        (directory / "config.json").write_text("{}")
        calls.append(directory.name)
        assert config.task.instructions_file.read_text() == directory.name.split("-")[0]
        # Editing the original during wave one must not change later configs.
        if directory.name == "control-001":
            original = inputs / "config.toml"
            original.write_text(original.read_text().replace("agents = 1", "agents = 2"))
        if directory.name == "control-002":
            assert config.task.objective_seed == 45
            assert config.task.noise_seed == 126
            assert config.agents == 1
        return {"agents": [{"reason": "error" if fail else "submitted", "true_objective": 1}]}

    monkeypatch.setattr(experiment, "run_rollout", rollout)
    monkeypatch.setattr(experiment, "export_review", lambda directory: None)
    output = tmp_path / "output"
    if fail:
        with pytest.raises(RuntimeError, match="remaining runs not launched"):
            await experiment.run_experiment(spec, output)
    else:
        await experiment.run_experiment(spec, output)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == ("error" if fail else "finished")
    assert len(calls) == (2 if fail else 4)
    assert [r["status"] for r in manifest["runs"]] == (
        ["error", "error", "pending", "pending"] if fail else ["finished"] * 4
    )
    assert not (output / "inputs/experiment/.env").exists()
    assert (output / "inputs/code/uv.lock").exists()
    recorded = json.loads((output / "checksums.json").read_text())
    assert recorded["manifest.json"] == experiment.checksum(output / "manifest.json")
    with pytest.raises(FileExistsError):
        await experiment.run_experiment(spec, output)

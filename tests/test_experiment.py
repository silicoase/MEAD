import json
from dataclasses import asdict
from pathlib import Path

import pytest
from agents.usage import Usage

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
        # SDK Usage is a dataclass containing Pydantic token-detail objects;
        # asdict leaves those nested objects intact, as in a real OpenAI rollout.
        usage = Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15)
        return {
            "agents": [
                {
                    "reason": "error" if fail else "submitted",
                    "true_objective": 1,
                    "usage": asdict(usage),
                }
            ]
        }

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
    usage = manifest["runs"][0]["agents_results"][0]["usage"]
    assert usage["input_tokens"] == 10
    assert usage["input_tokens_details"] == {"cached_tokens": 0, "cache_write_tokens": 0}
    assert usage["output_tokens_details"] == {"reasoning_tokens": 0}
    assert not (output / "inputs/experiment/.env").exists()
    assert (output / "inputs/code/uv.lock").exists()
    recorded = json.loads((output / "checksums.json").read_text())
    assert recorded["manifest.json"] == experiment.checksum(output / "manifest.json")
    with pytest.raises(FileExistsError):
        await experiment.run_experiment(spec, output)


def make_matrix_spec(tmp_path):
    spec = make_spec(tmp_path)
    text = spec.read_text().replace('config_file = "config.toml"\n', "")
    text = "schema_version = 3\n" + text
    text += '\n[model_configs]\nfirst = "first.toml"\nsecond = "second.toml"\n'
    spec.write_text(text)
    for name in ("first", "second"):
        (tmp_path / f"{name}.toml").write_text(
            f'agents = 1\n[harness]\nkind = "scripted"\nmodel = "{name}"\n'
        )
    return spec


def test_matrix_shares_seeds_across_models_and_conditions(tmp_path):
    plan = experiment.validate_experiment(make_matrix_spec(tmp_path))
    assert len(plan["runs"]) == 8
    assert len({e["run_id"] for e in plan["runs"]}) == 8
    for repetition in (1, 2):
        entries = [e for e in plan["runs"] if e["repetition"] == repetition]
        assert {(e["model_key"], e["condition"]) for e in entries} == {
            ("first", "control"),
            ("first", "aware"),
            ("second", "control"),
            ("second", "aware"),
        }
        assert {e["objective_seed"] for e in entries} == {43 + repetition}
        assert {e["noise_seed"] for e in entries} == {124 + repetition}


def test_matrix_rejects_unmatched_agent_counts(tmp_path):
    spec = make_matrix_spec(tmp_path)
    config = tmp_path / "second.toml"
    config.write_text(config.read_text().replace("agents = 1", "agents = 2"))
    with pytest.raises(ValueError, match="non-harness settings"):
        experiment.validate_experiment(spec)


@pytest.mark.parametrize("fail", [False, True])
async def test_matrix_runs_pairs_sequentially_and_stops_after_failure(tmp_path, monkeypatch, fail):
    import asyncio

    inputs = tmp_path / "definitions"
    inputs.mkdir()
    spec = make_matrix_spec(inputs)
    active = []
    calls = []
    max_active = 0

    async def rollout(config, directory):
        nonlocal max_active
        active.append(config.harness.model)
        max_active = max(max_active, len(active))
        assert len(set(active)) == 1
        calls.append(directory.name)
        await asyncio.sleep(0.01)
        active.remove(config.harness.model)
        return {"agents": [{"reason": "error" if fail else "submitted", "true_objective": 1}]}

    monkeypatch.setattr(experiment, "run_rollout", rollout)
    monkeypatch.setattr(experiment, "export_review", lambda directory: None)
    output = tmp_path / "output"
    if fail:
        with pytest.raises(RuntimeError, match="remaining runs not launched"):
            await experiment.run_experiment(spec, output)
    else:
        await experiment.run_experiment(spec, output)
    assert max_active == 2
    assert len(calls) == (2 if fail else 8)
    if not fail:
        assert calls[:4] == [
            "first-control-001",
            "first-aware-001",
            "second-control-001",
            "second-aware-001",
        ]
    snapshot = output / "inputs/experiment"
    assert experiment.validate_experiment(snapshot / "experiment.toml")["runs"]
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == ("error" if fail else "finished")
    assert all(e["status"] == "pending" for e in manifest["runs"][2:]) if fail else True
    assert "Model" in (output / "index.html").read_text()


async def test_pause_is_shared_by_conditions_and_reset_between_matched_pairs(tmp_path, monkeypatch):
    inputs = tmp_path / "definitions"
    inputs.mkdir()
    spec = make_spec(inputs)
    (inputs / "config.toml").write_text('''agents = 1
[harness]
kind = "openrouter"
coordinated_pause = true
[[harness.routes]]
model = "test/model"
''')
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    pauses = []
    async def rollout(config, directory, *, pause):
        assert config.harness.coordinated_pause
        pauses.append(pause)
        directory.mkdir()
        (directory / "config.json").write_text("{}")
        return {"agents": [{"reason": "submitted", "true_objective": 1}]}
    monkeypatch.setattr(experiment, "run_rollout", rollout)
    monkeypatch.setattr(experiment, "export_review", lambda directory: None)
    await experiment.run_experiment(spec, tmp_path / "out")
    assert pauses[0] is pauses[1]
    assert pauses[2] is pauses[3]
    assert pauses[0] is not pauses[2]

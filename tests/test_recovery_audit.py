"""The pilot audit must catch altered noise, scores and activity during a freeze."""

import importlib.util
import json
import random
from pathlib import Path

import pytest

from mad import task as task_module
from mad.config import RolloutConfig
from mad.task import SyntheticObjective


@pytest.mark.parametrize("corruption", [None, "noise", "score", "frozen_action"])
def test_saved_recovery_audit_detects_corruption(tmp_path, corruption):
    spec = importlib.util.spec_from_file_location(
        "pause_audit", Path(__file__).parents[1] / "scripts/review_coordinated_pause.py"
    )
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    batch, checks = tmp_path / "batch", tmp_path / "checks"
    run = batch / "control-001"
    run.mkdir(parents=True)
    code = batch / "inputs/code/src/mad/task.py"
    code.parent.mkdir(parents=True)
    code.write_bytes(Path(task_module.__file__).read_bytes())
    (batch / "manifest.json").write_text(
        json.dumps(
            {
                "status": "finished",
                "model_configs": {"test": "test.toml"},
                "runs": [
                    {
                        "run_id": "control-001",
                        "model_key": "test",
                        "model": "test/model",
                        "condition": "control",
                        "agents": 1,
                        "status": "finished",
                    }
                ],
            }
        )
    )
    cfg = RolloutConfig(agents=1, experiment_budget=1)
    (run / "config.json").write_text(cfg.model_dump_json())
    parameters = [0.5] * cfg.task.dimensions
    score = SyntheticObjective(cfg.task).evaluate(parameters)
    observed = score + random.Random(f"{cfg.task.noise_seed}:0").gauss(0, cfg.task.noise_std)
    record = {
        "run_id": "measurement-test",
        "parameters": parameters,
        "observed": observed + (0.1 if corruption == "noise" else 0),
    }
    raw = [
        {"kind": "experiment_started", "record": record},
        {"kind": "experiment_completed", "record": record},
        {"kind": "submission", "parameters": parameters},
        {
            "kind": "agent_finished",
            "report": {
                "reason": "submitted",
                "parameters": parameters,
                "true_objective": score + (0.1 if corruption == "score" else 0),
            },
        },
    ]
    if corruption == "frozen_action":
        raw = [{"kind": "cohort_pause_started"}, {"kind": "tool_called"}] + raw
    events = [
        dict(
            e,
            agent=0,
            sequence=i,
            timestamp=f"2026-10-11T00:00:0{i}+00:00",
            elapsed_seconds=i,
            active_elapsed_seconds=i,
            paused_seconds=0,
        )
        for i, e in enumerate(raw)
    ]
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (checks / "live-recovery").mkdir(parents=True)
    (checks / "live-recovery/summary.json").write_text(
        json.dumps({"status": "passed", "agent_reports": {}, "pause_count": 1, "paused_seconds": 1})
    )
    result = audit.review(batch, tmp_path / "review", checks)
    assert result["objective_and_noise_verified"]
    assert bool(result["violations"]) == (corruption is not None)
    if corruption == "noise":
        assert any("noise stream mismatch" in violation for violation in result["violations"])
    elif corruption == "score":
        assert any("final score mismatch" in violation for violation in result["violations"])
    elif corruption == "frozen_action":
        assert any("action during freeze" in violation for violation in result["violations"])

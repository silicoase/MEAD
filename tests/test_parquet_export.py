import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "parquet_export", Path(__file__).resolve().parents[1] / "scripts/export_batch_parquet.py"
)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def write(path, value):
    path.write_text(json.dumps(value))


def batch(tmp_path, finished=True):
    root = tmp_path / "raw"
    root.mkdir()
    run = root / "control-001"
    run.mkdir()
    record = dict(
        run_id="measurement-uuid",
        author_id="synthetic-author",
        parameters=[0.5] * 8,
        observed=0.3,
        started_at="start",
        completed_at="end",
    )
    report = dict(
        agent=0,
        author_id="synthetic-author",
        reason="submitted",
        parameters=[0.5] * 8,
        true_objective=0.2,
        experiments_used=1,
        experiments_completed=1,
        best_observed=0.3,
        duplicate_experiments=0,
        usage={"total_tokens": 12},
    )
    entry = dict(
        run_id=run.name,
        status="finished",
        condition="control",
        repetition=1,
        objective_seed=44,
        noise_seed=125,
        agents=1,
        experiment_budget=10,
        agents_results=[report],
    )
    runs = [entry]
    if not finished:
        runs.append(dict(entry, run_id="aware-001", status="pending", agents_results=[]))
    write(
        root / "manifest.json",
        dict(batch_id="manifest-id", status="finished" if finished else "running", runs=runs),
    )
    write(run / "config.json", {"task": {"dimensions": 8, "lower": 0, "upper": 1}})
    write(run / "identities.json", [{"agent": 0, "author_id": "synthetic-author"}])
    write(
        run / "summary.json",
        dict(
            agents=[report], experiment_records=[[record]], submissions={"0": report["parameters"]}
        ),
    )
    events = [
        dict(
            sequence=1,
            kind="experiment_started",
            agent=0,
            record={k: v for k, v in record.items() if k != "completed_at"},
        ),
        dict(sequence=2, kind="experiment_completed", agent=0, record=record),
        dict(sequence=3, kind="submission", agent=0, parameters=report["parameters"]),
    ]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return root


def test_export_roundtrip_provenance_and_raw_unchanged(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    root = batch(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = exporter.export(root, tmp_path / "tables")
    assert result["batch_id"] == "manifest-id"
    assert result["source_folder"] == "raw"
    assert result["all_agents_submitted"]
    row = pq.read_table(tmp_path / "tables/measurements.parquet").to_pylist()[0]
    assert row["run_id"] == "control-001"
    assert row["measurement_id"] == "measurement-uuid"
    assert row["publication_confirmed"] is True
    assert result["counts"] == {"runs": 1, "agents": 1, "measurements": 1}
    assert all(p.read_bytes() == content for p, content in before.items())
    with pytest.raises(ValueError, match="new directory"):
        exporter.export(root, tmp_path / "tables")


def test_partial_preserves_pending_slots_and_nulls(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    root = batch(tmp_path, finished=False)
    with pytest.raises(ValueError, match="incomplete"):
        exporter.export(root, tmp_path / "tables")
    result = exporter.export(root, tmp_path / "tables", allow_incomplete=True)
    assert result["preview"]
    assert not result["all_agents_submitted"]
    rows = pq.read_table(tmp_path / "tables/agents.parquet").to_pylist()
    pending = next(r for r in rows if r["run_id"] == "aware-001")
    assert pending["true_objective"] is None
    assert pending["record_available"] is False


def test_finished_run_with_non_submitter_fails_submission_audit(tmp_path):
    root = batch(tmp_path)
    path = root / "control-001/summary.json"
    summary = json.loads(path.read_text())
    summary["agents"][0].update(reason="time_limit", parameters=None, true_objective=None)
    summary["submissions"] = {}
    write(path, summary)
    _, _, tables, issues = exporter.collect(root)
    assert tables["runs"][0]["status"] == "finished"
    assert tables["agents"][0]["submission_confirmed"] is False
    assert issues[0]["reason"] == "time_limit"


def test_summaryless_fallback_keeps_interrupted_measurement(tmp_path):
    root = batch(tmp_path)
    (root / "control-001/summary.json").unlink()
    event_path = root / "control-001/events.jsonl"
    event_path.write_text(event_path.read_text().splitlines()[0] + "\n")
    _, _, tables, _ = exporter.collect(root)
    row = tables["measurements"][0]
    assert row["completed_at"] is None
    assert row["publication_confirmed"] is None
    assert row["source_path"].endswith("events.jsonl")


def test_count_mismatch_and_unsafe_run_rejected(tmp_path):
    root = batch(tmp_path)
    path = root / "control-001/summary.json"
    summary = json.loads(path.read_text())
    summary["agents"][0]["experiments_used"] = 2
    write(path, summary)
    with pytest.raises(ValueError, match="count mismatch"):
        exporter.collect(root)
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["runs"][0]["run_id"] = "../escape"
    write(path, manifest)
    with pytest.raises(ValueError, match="Unsafe"):
        exporter.collect(root)


def test_input_mutation_detected(tmp_path):
    root = batch(tmp_path)
    inputs, _, _, _ = exporter.collect(root)
    (root / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="Input changed"):
        inputs.verify_unchanged()


def test_empty_measurement_table_retains_typed_schema(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    root = batch(tmp_path)
    path = root / "control-001/summary.json"
    summary = json.loads(path.read_text())
    summary["experiment_records"] = [[]]
    summary["agents"][0].update(experiments_used=0, experiments_completed=0)
    write(path, summary)
    path = root / "control-001/events.jsonl"
    path.write_text(path.read_text().splitlines()[-1] + "\n")
    exporter.export(root, tmp_path / "tables")
    table = pq.read_table(tmp_path / "tables/measurements.parquet")
    assert table.num_rows == 0
    assert str(table.schema.field("observed").type) == "double"


def test_planned_grid_is_required_and_duplicate_measurements_rejected(tmp_path):
    root = batch(tmp_path)
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(conditions=["control", "aware"], repetitions=1)
    write(path, manifest)
    with pytest.raises(ValueError, match="planned condition/repetition grid"):
        exporter.collect(root)
    manifest["conditions"] = ["control"]
    write(path, manifest)
    path = root / "control-001/events.jsonl"
    event = json.loads(path.read_text().splitlines()[0])
    event["sequence"] = 4
    path.write_text(path.read_text() + json.dumps(event) + "\n")
    with pytest.raises(ValueError, match="Duplicate measurement start"):
        exporter.collect(root)

"""Export recorded batch tables without modifying raw inputs or calling any API.

Usage: uv run --locked --with pyarrow python scripts/export_batch_parquet.py BATCH OUTPUT
"""

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def encoded(value):
    return None if value is None else json.dumps(value, sort_keys=True, allow_nan=False)


class Inputs:
    def __init__(self, root):
        self.root = root
        self.hashes = {}

    def read(self, relative, default=None):
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise ValueError(f"Input must stay inside batch: {relative}")
        if not path.exists():
            return default
        if path.suffix == ".jsonl":
            return self.events(path, relative)
        content = path.read_bytes()
        self.hashes[relative] = hashlib.sha256(content).hexdigest()
        return json.loads(content)

    def events(self, path, relative):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for line in source:
                digest.update(line)
                if line.strip():
                    yield json.loads(line)
        self.hashes[relative] = digest.hexdigest()

    def verify_unchanged(self):
        for relative, digest in self.hashes.items():
            if hashlib.sha256((self.root / relative).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Input changed during export: {relative}; retry after collection")


def collect(root):
    inputs = Inputs(root)
    manifest = inputs.read("manifest.json")
    if not manifest or not manifest.get("batch_id"):
        raise ValueError("Batch manifest with batch_id is required")
    batch_id = manifest["batch_id"]
    if manifest.get("conditions") and manifest.get("repetitions"):
        expected = {
            (c, r) for c in manifest["conditions"] for r in range(1, manifest["repetitions"] + 1)
        }
        actual = [(r["condition"], r["repetition"]) for r in manifest["runs"]]
        if len(actual) != len(expected) or set(actual) != expected:
            raise ValueError(
                "Manifest does not contain exactly the planned condition/repetition grid"
            )
    tables = {name: [] for name in ("runs", "agents", "measurements")}
    issues = []
    seen_runs = set()
    for entry in manifest["runs"]:
        run_id = entry["run_id"]
        if Path(run_id).name != run_id or run_id in (".", "..") or run_id in seen_runs:
            raise ValueError(f"Unsafe or duplicate run ID: {run_id}")
        seen_runs.add(run_id)
        prefix = f"{run_id}/"
        summary = inputs.read(prefix + "summary.json")
        config = inputs.read(prefix + "config.json", {})
        identities = inputs.read(prefix + "identities.json", [])
        events = inputs.read(prefix + "events.jsonl", [])
        authors = {i["agent"]: i["author_id"] for i in identities}
        reports = {}
        for report in (summary or {}).get("agents", []):
            index = report["agent"]
            if index in reports or index not in range(entry["agents"]):
                raise ValueError(f"Duplicate or invalid agent index in {run_id}: {index}")
            reports[index] = report
        measurements = {}
        starts = set()
        completions = set()
        submission_events = {}
        last_sequence = 0
        for event in events:
            if event["sequence"] <= last_sequence:
                raise ValueError(f"Events out of order in {run_id}")
            last_sequence = event["sequence"]
            kind = event["kind"]
            if kind in ("experiment_started", "experiment_completed"):
                record = event["record"]
                key = record["run_id"]
                if kind == "experiment_started":
                    if key in starts:
                        raise ValueError(f"Duplicate measurement start {key} in {run_id}")
                    starts.add(key)
                old = measurements.get(key)
                if old and (
                    old[0] != event["agent"]
                    or any(
                        old[1].get(k) != record.get(k)
                        for k in ("author_id", "parameters", "observed", "started_at")
                    )
                ):
                    raise ValueError(f"Conflicting measurement {key} in {run_id}")
                measurements[key] = (
                    event["agent"],
                    record,
                    prefix + "events.jsonl",
                    f"sequence:{event['sequence']}",
                )
                if kind == "experiment_completed":
                    if key in completions:
                        raise ValueError(f"Duplicate measurement completion {key} in {run_id}")
                    completions.add(key)
            elif kind == "submission":
                if event["agent"] in submission_events:
                    raise ValueError(f"Duplicate submission in {run_id}")
                submission_events[event["agent"]] = event["parameters"]
        for agent, records in enumerate((summary or {}).get("experiment_records", [])):
            for index, record in enumerate(records):
                key = record["run_id"]
                old = measurements.get(key)
                if old and (
                    old[0] != agent
                    or any(
                        old[1].get(k) != record.get(k)
                        for k in ("author_id", "parameters", "observed", "started_at")
                    )
                ):
                    raise ValueError(f"Summary/event mismatch for {key} in {run_id}")
                if (
                    old
                    and old[1].get("completed_at") is not None
                    and (old[1]["completed_at"] != record.get("completed_at"))
                ):
                    raise ValueError(f"Completion timestamp mismatch for {key} in {run_id}")
                if old and old[2].endswith("summary.json"):
                    raise ValueError(f"Duplicate summary measurement {key} in {run_id}")
                measurements[key] = (
                    agent,
                    record,
                    prefix + "summary.json",
                    f"experiment_records/{agent}/{index}",
                )
        base = dict(release_schema_version=SCHEMA_VERSION, batch_id=batch_id, run_id=run_id)
        confirmed = 0
        submissions = (summary or {}).get("submissions", {})
        manifest_reports = {a["agent"]: a for a in entry.get("agents_results", [])}
        for agent in range(entry["agents"]):
            report = reports.get(agent, {})
            parameters = report.get("parameters")
            score = report.get("true_objective")
            submitted = (
                report.get("reason") == "submitted"
                and parameters is not None
                and score is not None
                and math.isfinite(score)
                and submissions.get(str(agent)) == parameters
                and submission_events.get(agent) == parameters
            )
            manifest_report = manifest_reports.get(agent)
            if manifest_report and any(
                manifest_report.get(k) != report.get(k)
                for k in ("reason", "parameters", "true_objective")
            ):
                submitted = False
            confirmed += submitted
            if not submitted:
                issues.append(
                    dict(
                        run_id=run_id,
                        agent=agent,
                        reason=report.get("reason"),
                        issue="submission missing or inconsistent",
                    )
                )
            tables["agents"].append(
                dict(
                    **base,
                    agent=agent,
                    author_id=report.get("author_id", authors.get(agent)),
                    record_available=agent in reports,
                    submission_confirmed=submitted,
                    reason=report.get("reason"),
                    parameters=parameters,
                    true_objective=score,
                    **{
                        k: report.get(k)
                        for k in (
                            "experiments_used",
                            "experiments_completed",
                            "best_observed",
                            "duplicate_experiments",
                        )
                    },
                    final_output_json=encoded(report.get("final_output")),
                    usage_json=encoded(report.get("usage")),
                )
            )
        for key, (agent, record, source, locator) in measurements.items():
            task = config.get("task", {})
            parameters = record["parameters"]
            dimensions = task.get("dimensions", len(parameters))
            lower, upper = task.get("lower", 0), task.get("upper", 1)
            if (
                agent not in range(entry["agents"])
                or len(parameters) != dimensions
                or any(
                    isinstance(v, bool)
                    or not isinstance(v, (float, int))
                    or not math.isfinite(v)
                    or not lower <= v <= upper
                    for v in parameters
                )
                or not math.isfinite(record["observed"])
            ):
                raise ValueError(f"Invalid measurement {key} in {run_id}")
            tables["measurements"].append(
                dict(
                    **base,
                    measurement_id=key,
                    agent=agent,
                    author_id=record["author_id"],
                    parameters=parameters,
                    observed=record["observed"],
                    started_at=record["started_at"],
                    completed_at=record.get("completed_at"),
                    completion_event_present=key in completions,
                    publication_confirmed=True if key in completions else None,
                    source_path=source,
                    source_locator=locator,
                )
            )
        for agent, report in reports.items():
            records = [r[1] for r in measurements.values() if r[0] == agent]
            for field, actual in (
                ("experiments_used", len(records)),
                ("experiments_completed", sum("completed_at" in r for r in records)),
            ):
                if report.get(field) is not None and report[field] != actual:
                    raise ValueError(f"{field} count mismatch in {run_id}, agent {agent}")
        tables["runs"].append(
            dict(
                **base,
                **{
                    k: entry.get(k)
                    for k in (
                        "condition",
                        "repetition",
                        "objective_seed",
                        "noise_seed",
                        "status",
                        "started_at",
                        "finished_at",
                        "experiment_budget",
                        "error_type",
                        "error",
                        "review_error",
                    )
                },
                planned_agents=entry["agents"],
                submitted_agents=sum(r.get("reason") == "submitted" for r in reports.values())
                if summary is not None
                else None,
                confirmed_submissions=confirmed,
                accepted_measurements=len(measurements)
                if summary is not None or measurements
                else None,
                completed_measurements=sum("completed_at" in r[1] for r in measurements.values())
                if summary is not None or measurements
                else None,
                raw_path=run_id if (root / run_id).is_dir() else None,
                missing_files=[
                    name
                    for name in (
                        "config.json",
                        "runtime.json",
                        "identities.json",
                        "events.jsonl",
                        "summary.json",
                        "artifacts.tar",
                        "run_metadata.json",
                        "checksums.json",
                        "review.html",
                    )
                    if not (root / run_id / name).is_file()
                ],
            )
        )
    return inputs, manifest, tables, issues


def schemas(pa):
    common = [
        ("release_schema_version", pa.int64()),
        ("batch_id", pa.string()),
        ("run_id", pa.string()),
    ]
    string, integer, number, boolean = pa.string(), pa.int64(), pa.float64(), pa.bool_()
    vector = pa.list_(number)
    return {
        "runs": pa.schema(
            common
            + [
                (k, string)
                for k in (
                    "condition",
                    "status",
                    "started_at",
                    "finished_at",
                    "raw_path",
                    "error_type",
                    "error",
                    "review_error",
                )
            ]
            + [
                (k, integer)
                for k in (
                    "repetition",
                    "objective_seed",
                    "noise_seed",
                    "planned_agents",
                    "experiment_budget",
                    "submitted_agents",
                    "confirmed_submissions",
                    "accepted_measurements",
                    "completed_measurements",
                )
            ]
            + [("missing_files", pa.list_(string))]
        ),
        "agents": pa.schema(
            common
            + [
                ("agent", integer),
                ("author_id", string),
                ("record_available", boolean),
                ("submission_confirmed", boolean),
                ("reason", string),
                ("parameters", vector),
                ("true_objective", number),
                ("best_observed", number),
            ]
            + [
                (k, integer)
                for k in ("experiments_used", "experiments_completed", "duplicate_experiments")
            ]
            + [("final_output_json", string), ("usage_json", string)]
        ),
        "measurements": pa.schema(
            common
            + [
                ("measurement_id", string),
                ("agent", integer),
                ("author_id", string),
                ("parameters", vector),
                ("observed", number),
                ("started_at", string),
                ("completed_at", string),
                ("completion_event_present", boolean),
                ("publication_confirmed", boolean),
                ("source_path", string),
                ("source_locator", string),
            ]
        ),
    }


def export(root, destination, allow_incomplete=False):
    import pyarrow as pa
    import pyarrow.parquet as pq

    root, destination = root.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError("Output must be a new directory separate from the raw batch")
    inputs, manifest, tables, issues = collect(root)
    finished = (
        bool(manifest["runs"])
        and manifest["status"] == "finished"
        and all(r["status"] == "finished" for r in manifest["runs"])
    )
    if not finished and not allow_incomplete:
        raise ValueError("Batch is incomplete; use --allow-incomplete for a labeled local preview")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".parquet-export-", dir=destination.parent))
    try:
        table_schemas = schemas(pa)
        schema_doc = {"release_schema_version": SCHEMA_VERSION, "tables": {}}
        for name, rows in tables.items():
            rows.sort(key=lambda r: (r["run_id"], r.get("agent", -1), r.get("measurement_id", "")))
            table = pa.Table.from_pylist(rows, schema=table_schemas[name])
            pq.write_table(table, staging / f"{name}.parquet", compression="zstd")
            if not pq.read_table(staging / f"{name}.parquet").equals(table):
                raise ValueError(f"Parquet round-trip mismatch: {name}")
            schema_doc["tables"][name] = [
                dict(name=f.name, type=str(f.type), nullable=f.nullable) for f in table.schema
            ]
        inputs.verify_unchanged()
        metadata = dict(
            release_schema_version=SCHEMA_VERSION,
            batch_id=manifest["batch_id"],
            source_folder=root.name,
            exported_at=datetime.now(timezone.utc).isoformat(),
            batch_finished=finished,
            preview=not finished,
            all_agents_submitted=not issues,
            submission_issues=issues,
            counts={k: len(v) for k, v in tables.items()},
            source_sha256=inputs.hashes,
            pyarrow_version=pa.__version__,
            exporter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            note="Derived tables only; not a publication approval or full raw checksum audit.",
        )
        for name, value in (("RELEASE.json", metadata), ("SCHEMA.json", schema_doc)):
            (staging / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
        checksums = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(staging.iterdir())
        }
        (staging / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")
        staging.rename(destination)
        return metadata
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    try:
        result = export(args.batch, args.output, args.allow_incomplete)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Export failed: {error}\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "batch_id",
                    "preview",
                    "all_agents_submitted",
                    "counts",
                    "submission_issues",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

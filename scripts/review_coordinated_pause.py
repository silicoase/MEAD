"""Read-only recovery audit and progress report for a saved matched pilot."""

import argparse
import hashlib
import html
import json
import random
from pathlib import Path

from mad import task as task_module
from mad.config import RolloutConfig
from mad.recording import write_json
from mad.task import SyntheticObjective


def review(batch, output, checks):
    manifest = json.loads((batch / "manifest.json").read_text())
    rows, violations = [], []
    saved_objective = batch / "inputs/code/src/mad/task.py"
    objective_verified = (
        saved_objective.exists()
        and hashlib.sha256(saved_objective.read_bytes()).digest()
        == hashlib.sha256(Path(task_module.__file__).read_bytes()).digest()
    )
    for entry in manifest["runs"]:
        run = batch / entry["run_id"]
        events = []
        path = run / "events.jsonl"
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    break
        config_path = run / "config.json"
        cfg = (
            RolloutConfig.model_validate(json.loads(config_path.read_text()))
            if config_path.exists()
            else None
        )
        objective = SyntheticObjective(cfg.task) if cfg and objective_verified else None
        noise = (
            [random.Random(f"{cfg.task.noise_seed}:{agent}") for agent in range(cfg.agents)]
            if cfg
            else []
        )
        frozen = False
        seen_measurements = set()
        seen_receipts = set()
        for event in events:
            kind = event["kind"]
            if kind == "experiment_started":
                record = event["record"]
                if record["run_id"] in seen_measurements:
                    violations.append([entry["run_id"], event["sequence"], "duplicate measurement"])
                seen_measurements.add(record["run_id"])
                if objective:
                    expected = objective.evaluate(record["parameters"]) + noise[
                        event["agent"]
                    ].gauss(0, cfg.task.noise_std)
                    if abs(expected - record["observed"]) > 1e-12:
                        violations.append(
                            [entry["run_id"], event["sequence"], "noise stream mismatch"]
                        )
            if kind == "agent_finished" and objective:
                report = event["report"]
                if (
                    report.get("parameters") is not None
                    and abs(objective.evaluate(report["parameters"]) - report["true_objective"])
                    > 1e-12
                ):
                    violations.append([entry["run_id"], event["sequence"], "final score mismatch"])
            if kind == "cohort_pause_started":
                frozen = True
            elif kind == "cohort_pause_clock_resumed":
                frozen = False
            elif frozen and kind in {
                "provider_request_started",
                "tool_called",
                "submission",
                "experiment_started",
            }:
                violations.append(
                    [entry["run_id"], event["sequence"], "action during freeze", kind]
                )
            if "active_elapsed_seconds" in event:
                if (
                    abs(
                        event["elapsed_seconds"]
                        - event["active_elapsed_seconds"]
                        - event["paused_seconds"]
                    )
                    > 1e-6
                ):
                    violations.append([entry["run_id"], event["sequence"], "clock mismatch"])
            if kind == "provider_response_metadata" and event.get("response_id"):
                if event["response_id"] in seen_receipts:
                    violations.append([entry["run_id"], event["sequence"], "duplicate receipt"])
                seen_receipts.add(event["response_id"])
        metadata = [e for e in events if e["kind"] == "provider_response_metadata"]
        costs = [(e["metadata"].get("usage") or {}).get("cost") for e in metadata]
        final = [e["report"] for e in events if e["kind"] == "agent_finished"]
        for agent in range(entry["agents"]):
            measurements = sum(
                e["kind"] == "experiment_completed" and e["agent"] == agent for e in events
            )
            if cfg and measurements > cfg.experiment_budget:
                violations.append([entry["run_id"], agent, "experiment budget exceeded"])
        causes = {}
        for report in final:
            if report.get("reason") != "error":
                continue
            message = report.get("error", "")
            cause = (
                "Empty token-limited response"
                if report.get("error_kind") == "empty_truncated_response"
                or "finish_reason='length'" in message
                else "Google HTTP 504"
                if message.startswith("Error code: 504")
                else "API recovery allowance"
                if "pause budget exhausted" in message
                else "Other"
            )
            causes[cause] = causes.get(cause, 0) + 1
        pauses = [e for e in events if e["kind"] == "cohort_pause_ended"]
        manual = [e for e in events if e["kind"] == "manual_pause_ended"]
        manual_wall = sum(e["manual_pause_wall_seconds"] for e in manual)
        frozen_seconds = events[-1].get("paused_seconds", 0) if events else 0
        rows.append(
            {
                "run_id": entry["run_id"],
                "model": entry.get("model_key"),
                "condition": entry["condition"],
                "status": entry["status"],
                "agents": entry["agents"],
                "submitted": sum(e["kind"] == "submission" for e in events),
                "finished_agents": len(final),
                "terminal_error_causes": causes,
                "end_reasons": {
                    reason: sum(a.get("reason") == reason for a in final)
                    for reason in sorted({a.get("reason", "unknown") for a in final})
                },
                "experiments": sum(e["kind"] == "experiment_completed" for e in events),
                "pauses": len(pauses),
                "currently_frozen": frozen,
                "wall_seconds": events[-1]["elapsed_seconds"] if events else 0,
                "active_seconds": events[-1].get(
                    "active_elapsed_seconds", events[-1]["elapsed_seconds"]
                )
                if events
                else 0,
                "paused_seconds": frozen_seconds,
                "manual_pause_wall_seconds": manual_wall,
                "api_pause_seconds": max(0, frozen_seconds - manual_wall),
                "pause_limit_reached": any(e["kind"] == "cohort_pause_limit" for e in events),
                "request_errors": sum(e["kind"] == "provider_request_failed" for e in events),
                "reported_cost_usd": sum(c for c in costs if c is not None),
                "reported_responses": sum(c is not None for c in costs),
                "missing_costs": sum(c is None for c in costs),
            }
        )
    # Compare only the period in which both arms still have recorded activity.
    # A completed arm need not log pauses occurring later in its remaining peer.
    for model in manifest["model_configs"]:
        streams = []
        for row in rows:
            if row["model"] != model or row["status"] not in {"finished", "error", "cancelled"}:
                continue
            events_path = batch / row["run_id"] / "events.jsonl"
            if events_path.exists():
                streams.append([json.loads(line) for line in events_path.read_text().splitlines()])
        if len(streams) == 2 and all(streams):
            overlap_end = min(es[-1]["timestamp"] for es in streams)
            shared = [
                [
                    (e["pause_index"], e["pause_seconds"])
                    for e in es
                    if e["kind"] == "cohort_pause_ended" and e["timestamp"] <= overlap_end
                ]
                for es in streams
            ]
            if shared[0] != shared[1]:
                violations.append([model, "conditions recorded different shared pauses"])
    result = {
        "batch": str(batch.resolve()),
        "status": manifest["status"],
        "runs": rows,
        "violations": violations,
        "objective_and_noise_verified": objective_verified,
        "reported_cost_usd": sum(r["reported_cost_usd"] for r in rows),
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "recovery-audit.json", result)
    preflight_root = checks / "preflight" if (checks / "preflight").is_dir() else checks
    preflights = [json.loads(p.read_text()) for p in preflight_root.glob("*/summary.json")
                  if p.parent.name != "live-recovery"]
    live_path = checks / "live-recovery/summary.json"
    live = json.loads(live_path.read_text()) if live_path.exists() else None

    def esc(value):
        return html.escape(str(value))

    page = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Coordinated-pause pilot</title><style>body{font:15px/1.5 system-ui;margin:32px;color:#17202a}table{border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}a{color:#155eab}</style><h1>Coordinated-pause pilot</h1>'
    page += f"<p>Compatibility: {sum(p['status'] == 'passed' for p in preflights)}/{len(preflights)} passed.</p>"
    if live is not None:
        page += f"<p>Live recovery check: {esc(live['status'])}; {sum(r['reason'] == 'submitted' for rs in live['agent_reports'].values() for r in rs)}/20 submissions, {live['pause_count']} shared pause, {live['paused_seconds']:.1f} seconds frozen.</p>"
    page += f'<p>Pilot status: {esc(result["status"])}. Recorded task cost: ${result["reported_cost_usd"]:.4f}. Recovery audit violations: {len(violations)}. <a href="figures/index.html">Interactive figures</a> · <a href="recovery-audit.json">Audit data</a></p>'
    headers = [
        "Model",
        "Condition",
        "Status",
        "Submitted",
        "Experiments",
        "Pauses",
        "Wall min",
        "Active min",
        "Frozen min",
        "Reported USD",
        "Missing costs",
        "End reasons",
    ]
    page += (
        '<div style="overflow:auto"><table><thead><tr>'
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr></thead><tbody>"
    )
    for row in rows:
        cells = [
            manifest["runs"][rows.index(row)].get("model", row["model"]),
            row["condition"],
            row["status"] + (" (frozen)" if row["currently_frozen"] else ""),
            f"{row['submitted']}/{row['agents']}",
            row["experiments"],
            row["pauses"],
        ]
        cells += [
            f"{row[k] / 60:.2f}" for k in ["wall_seconds", "active_seconds", "paused_seconds"]
        ]
        cells += [f"{row['reported_cost_usd']:.4f}", row["missing_costs"], row["terminal_error_causes"] or row["end_reasons"]]
        page += "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in cells) + "</tr>"
    page += "</tbody></table></div>"
    limited = sorted({r["model"] for r in rows if r["pause_limit_reached"]})
    if limited:
        page += (
            "<p><strong>Infrastructure stop:</strong> "
            + esc(", ".join(limited))
            + " exhausted the cumulative API-recovery allowance. This is distinct from agent active-time or turn exhaustion; incomplete final outcomes are reported as missing.</p>"
        )
    manual_seconds = max((r["manual_pause_wall_seconds"] for r in rows), default=0)
    page += f"<p>Operator relocation pause: {manual_seconds / 60:.2f} minutes in GPT-6 Luna. Wall time includes it; active time excludes it. It is credited separately from the API-recovery allowance.</p><p>Infrastructure recovery pauses both conditions after admitted work drains. Only fully frozen intervals are excluded from active time. In-flight completions and resumed queue order can affect artifact visibility and collaboration timing; artifacts retain wall timestamps. Experiment budgets, noise streams and scoring are unchanged.</p><p>One exploratory matched set per model; the formal twenty-pair experiment has not started. Probe costs are separate from the task cost above.</p></html>"
    (output / "index.html").write_text(page)
    print(
        json.dumps(
            {
                "status": result["status"],
                "reported_cost_usd": result["reported_cost_usd"],
                "violations": violations,
                "runs": [
                    {
                        k: r[k]
                        for k in [
                            "model",
                            "condition",
                            "status",
                            "submitted",
                            "experiments",
                            "pauses",
                            "end_reasons",
                        ]
                    }
                    for r in rows
                ],
            }
        ),
        flush=True,
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--checks", required=True, type=Path)
    args = parser.parse_args()
    review(args.batch, args.output, args.checks)

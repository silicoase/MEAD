"""Build a model-aware comparison snapshot beside an immutable raw batch."""

import argparse
import html
import json
import os
import statistics
from pathlib import Path

from summarize_collaboration import analyze_events


def read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def collect(batch):
    manifest = read(batch / "manifest.json", {})
    rows = []
    for entry in manifest["runs"]:
        directory = batch / entry["run_id"]
        events = []
        path = directory / "events.jsonl"
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    break  # A live writer may not have finished its final line.
        summary = read(directory / "summary.json", {})
        reports = summary.get("agents", []) or [
            e["report"] for e in events if e["kind"] == "agent_finished"
        ]
        scores = [a["true_objective"] for a in reports if a.get("true_objective") is not None]
        metadata = [e for e in events if e["kind"] == "provider_response_metadata"]
        costs = [(e["metadata"].get("usage") or {}).get("cost") for e in metadata]
        latencies = [e["latency_seconds"] for e in metadata if "latency_seconds" in e]
        ownership = read(directory / "note_ownership.json", {})
        identities = {a["agent"]: a["author_id"] for a in read(directory / "identities.json", [])}
        reads, mentions = analyze_events(events, ownership, identities)
        rows.append(
            {
                "run_id": entry["run_id"],
                "model": entry.get("model_key"),
                "condition": entry["condition"],
                "repetition": entry["repetition"],
                "status": entry["status"],
                "planned_agents": entry["agents"],
                "submitted": sum(a.get("reason") == "submitted" for a in reports),
                "finished_agents": len(reports),
                "mean_score": statistics.mean(scores) if scores else None,
                "best_score": max(scores) if scores else None,
                "measurements": sum(e["kind"] == "experiment_completed" for e in events),
                "calls": len(metadata),
                "reported_cost_usd": sum(costs)
                if costs and all(c is not None for c in costs)
                else None,
                "median_call_latency_seconds": statistics.median(latencies) if latencies else None,
                "peer_reads": len(reads),
                "peer_note_reads": sum(r["artifact"] == "note" for r in reads),
                "peer_mention_responses": len(mentions),
                "request_failures": sum(e["kind"] == "provider_request_failed" for e in events),
                "finish_reasons": {
                    reason: sum(a.get("reason") == reason for a in reports)
                    for reason in sorted({a.get("reason", "unknown") for a in reports})
                },
                "review": str(directory / "review.html"),
            }
        )
    pairs = []
    for repetition in range(1, manifest["repetitions"] + 1):
        for model in manifest["model_configs"]:
            group = {
                r["condition"]: r
                for r in rows
                if r["model"] == model and r["repetition"] == repetition
            }
            c, i = group["control"], group["interact"]
            complete = c["status"] == i["status"] == "finished"
            pairs.append(
                {
                    "model": model,
                    "repetition": repetition,
                    "complete": complete,
                    "mean_score_delta": i["mean_score"] - c["mean_score"]
                    if complete and c["mean_score"] is not None and i["mean_score"] is not None
                    else None,
                    "control_submitted": c["submitted"],
                    "interact_submitted": i["submitted"],
                }
            )
    return {
        "batch": str(batch.resolve()),
        "status": manifest["status"],
        "runs": rows,
        "pairs": pairs,
    }


def export(batch, output):
    data = collect(batch)
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").write_text(json.dumps(data, indent=2) + "\n")
    headers = [
        "Set",
        "Model",
        "Condition",
        "Status",
        "Submitted",
        "Mean score",
        "Best score",
        "Measurements",
        "Calls",
        "Reported $",
        "Median latency (s)",
        "Peer reads",
        "Peer mentions",
        "API failures",
        "Review",
    ]
    rows = []
    for r in data["runs"]:

        def fmt(value, digits=4):
            return "—" if value is None else f"{value:.{digits}f}"

        values = [
            r["repetition"],
            r["model"],
            r["condition"],
            r["status"],
            f"{r['submitted']}/{r['planned_agents']}",
            fmt(r["mean_score"]),
            fmt(r["best_score"]),
            r["measurements"],
            r["calls"],
            fmt(r["reported_cost_usd"]),
            fmt(r["median_call_latency_seconds"], 2),
            r["peer_reads"],
            r["peer_mention_responses"],
            r["request_failures"],
        ]
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in values)
        link = os.path.relpath(r["review"], output)
        cells += (
            f'<td><a href="{html.escape(link)}">Open</a></td>'
            if Path(r["review"]).exists()
            else "<td>—</td>"
        )
        rows.append("<tr>" + cells + "</tr>")
    pair_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(v))}</td>"
            for v in [
                p["repetition"],
                p["model"],
                "—" if p["mean_score_delta"] is None else f"{p['mean_score_delta']:+.4f}",
                p["control_submitted"],
                p["interact_submitted"],
            ]
        )
        + "</tr>"
        for p in data["pairs"]
    )
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><title>MEAD model comparison</title>
<style>body{font:15px/1.6 system-ui;margin:32px;color:#17202a}table{border-collapse:collapse}
td,th{padding:8px 12px;border-bottom:1px solid #ddd;text-align:left}th{background:#f1f5f9}
.scroll{overflow:auto}a{color:#155eab}</style><h1>MEAD: matched model comparison</h1>"""
    page += f"<p>Batch status: {html.escape(data['status'])}. Snapshot; refresh by regenerating this report.</p>"
    page += "<p>Scores include submitted agents only; inspect submission counts alongside scores. "
    page += "Peer reads count logged file-tool access; mentions are text candidates, not verified collaboration. "
    page += "Live note-read counts may be incomplete until ownership is archived. Missing cost is unknown. "
    page += "Two matched sets are exploratory; models are compared separately.</p>"
    page += '<div class="scroll"><table><thead><tr>' + "".join(f"<th>{h}</th>" for h in headers)
    page += "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    page += "<h2>Within-model interaction minus control</h2><table><thead><tr>"
    page += "<th>Set</th><th>Model</th><th>Mean score difference</th><th>Control submitted</th><th>Interact submitted</th>"
    page += "</tr></thead><tbody>" + pair_rows + "</tbody></table></html>"
    (output / "comparison.html").write_text(page)
    print(
        json.dumps(
            {
                "status": data["status"],
                "completed_runs": sum(r["status"] == "finished" for r in data["runs"]),
                "recorded_cost_usd": sum(r["reported_cost_usd"] or 0 for r in data["runs"]),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.batch, args.output)

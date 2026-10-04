"""Summarize logged peer reads and explicit peer-mention candidates.

Counts are navigation aids for reviewing collaboration examples, not classifiers.
"""

import argparse
import csv
import json
import re
import statistics
from pathlib import Path, PurePosixPath

PEER_WORDS = re.compile(
    r"\b(?:other|another|fellow|remaining|all|multiple|several|cooperating)"
    r"\s+(?:(?:\w+)\s+){0,2}(?:agents?|researchers?)\b|\bpeers?\b", re.I
)
ID_REFERENCE = re.compile(r"\b(?P<label>agent\s*)?(?P<id>[0-9a-f]{4,32})\b", re.I)


def specific_references(text, agent, identities):
    for match in ID_REFERENCE.finditer(text):
        prefix = match["id"].lower()
        # Avoid treating short decimal numbers as IDs unless labeled "agent".
        if prefix.isdigit() and len(prefix) < 32 and not match["label"]:
            continue
        owners = [owner for owner, identity in identities.items() if identity.startswith(prefix)]
        if len(owners) == 1 and owners[0] != agent:
            yield match.start()


def authored_text(output):
    """Exclude supplied prompts, tool results, opaque reasoning, and Python code."""
    for item in output:
        if item.get("type") == "reasoning":
            for part in item.get("summary", []):
                if part.get("text"):
                    yield "reasoning_summary", part["text"]
        elif item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text" and part.get("text"):
                    yield "message", part["text"]
        elif item.get("type") == "function_call" and item.get("name") in (
            "write_file", "append_file"
        ):
            try:
                args = json.loads(item["arguments"])
            except (KeyError, json.JSONDecodeError):
                continue
            if args.get("content"):
                yield "proposed_note_or_file_text", args["content"]


def analyze_events(events, ownership, identities):
    pending, measurements = {}, {}
    reads, mentions = [], []
    seen_responses = set()
    for event in events:
        agent, kind = event.get("agent"), event["kind"]
        if kind == "experiment_completed":
            measurements[f"/lab/runs/{event['record']['run_id']}.json"] = agent
        elif kind == "tool_called":
            pending[agent] = event
        elif kind == "tool_cancelled":
            pending.pop(agent, None)
        elif kind == "tool_result":
            call = pending.pop(agent, None)
            result = event.get("result")
            if not call or call["tool"] != "read_file" or not isinstance(result, str):
                continue
            path = str(PurePosixPath(call.get("arguments", {}).get("path", "")))
            owner = measurements.get(path)
            artifact = "measurement"
            if PurePosixPath(path).parent == PurePosixPath("/lab/notes"):
                owner = ownership.get(f"notes/all/{PurePosixPath(path).name}")
                artifact = "note"
            if owner is not None and owner != agent:
                reads.append(dict(agent=agent, peer=owner, artifact=artifact, path=path,
                                  sequence=event["sequence"], call_sequence=call["sequence"],
                                  elapsed_seconds=event["elapsed_seconds"]))
        elif kind == "model_response":
            response_id = event.get("response_id")
            if response_id and response_id in seen_responses:
                continue
            if response_id:
                seen_responses.add(response_id)
            excerpts = []
            for source, text in authored_text(event.get("output", [])):
                match = PEER_WORDS.search(text)
                matches = [("explicit_peer_language", match.start())] if match else []
                # Specific mentions remain a subset of all peer mentions, even
                # when the same text also uses generic words such as "peers".
                matches.extend(("peer_id", position)
                               for position in specific_references(text, agent, identities))
                for tag, position in matches:
                    excerpt = text[max(0, position - 100):position + 250].replace("\n", " ")
                    excerpts.append(dict(source=source, tag=tag, excerpt=excerpt))
            # One tagged response regardless of how many mentions/excerpts it contains.
            if excerpts:
                mentions.append(dict(agent=agent, sequence=event["sequence"],
                                     elapsed_seconds=event["elapsed_seconds"],
                                     response_id=response_id, excerpts=excerpts))
    return reads, mentions


def collect(batch, output):
    manifest = json.loads((batch / "manifest.json").read_text())
    matched = sorted({r["repetition"] for r in manifest["runs"] if all(
        p["status"] == "finished" for p in manifest["runs"]
        if p["repetition"] == r["repetition"]
    )})
    runs = []
    for entry in manifest["runs"]:
        if entry["repetition"] not in matched:
            continue
        directory = batch / entry["run_id"]
        events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
        ownership = json.loads((directory / "note_ownership.json").read_text())
        ids = {a["agent"]: a["author_id"] for a in json.loads((directory / "identities.json").read_text())}
        reads, mentions = analyze_events(events, ownership, ids)
        start = min(e["elapsed_seconds"] for e in events if e["kind"] == "agent_started")
        end = max(e["elapsed_seconds"] for e in events if e["kind"] == "agent_finished")
        for event in reads + mentions:
            event["normalized_time"] = (event["elapsed_seconds"] - start) / (end - start)
        runs.append(dict(run_id=entry["run_id"], condition=entry["condition"],
                         repetition=entry["repetition"], reads=reads, mentions=mentions,
                         specific_mentions=[m for m in mentions
                                            if any(e["tag"] == "peer_id" for e in m["excerpts"])]))
    if not runs:
        raise ValueError("No complete matched repetitions")
    output.mkdir(parents=True, exist_ok=True)
    data = dict(batch=str(batch.resolve()), conditions=manifest["conditions"],
                repetitions=matched, runs=runs)
    (output / "collaboration.json").write_text(json.dumps(data, indent=2) + "\n")
    columns = ["run_id", "agent", "sequence", "outcome", "peer", "artifact", "path",
               "source", "tag", "excerpt"]
    with (output / "evidence.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for run in runs:
            for read in run["reads"]:
                writer.writerow(dict(run_id=run["run_id"], outcome="peer_read", **read))
            for mention in run["mentions"]:
                for excerpt in mention["excerpts"]:
                    writer.writerow(dict(run_id=run["run_id"], outcome="peer_mention_candidate",
                                         agent=mention["agent"], sequence=mention["sequence"], **excerpt))
    print(f"Snapshot: {len(matched)} matched repetitions")
    for condition in data["conditions"]:
        group = [r for r in runs if r["condition"] == condition]
        print(condition, json.dumps(dict(
            mean_peer_reads=statistics.mean(len(r["reads"]) for r in group),
            mean_peer_note_reads=statistics.mean(sum(e["artifact"] == "note" for e in r["reads"]) for r in group),
            mean_peer_record_reads=statistics.mean(sum(e["artifact"] == "measurement" for e in r["reads"]) for r in group),
            mean_tagged_responses=statistics.mean(len(r["mentions"]) for r in group),
        )))


def plot(output, brand):
    import matplotlib
    matplotlib.use("Agg")
    import numpy as np
    from figure_style import COLORS, LINE_STYLES, Chart, style_axes
    data = json.loads((output / "collaboration.json").read_text())
    grid = np.linspace(0, 1, 201)
    writeup = Path(__file__).resolve().parents[1] / "experiments/swarm-hackathon-demo/WRITEUP.md"
    match = re.search(r"^\[\^interaction-counts\]:[ \t]*(.+?)(?:\n\s*\n|\Z)",
                      writeup.read_text(), flags=re.M | re.S)
    if match is None:
        raise ValueError("WRITEUP.md is missing the interaction-counts footnote")
    layout = Chart(output, brand, panels=3,
                   title="Agent interactions: peer-file reads and agent mentions",
                   subtitle="Cumulative counts across all 4 agents, mean across runs",
                   status="",
                   note="Notes: " + " ".join(match[1].split()))
    axes = layout.axes
    for ax, outcome, label in zip(axes, ["reads", "mentions", "specific_mentions"],
                                   ["Panel A. Peer-file reads", "Panel B. Other-agent mentions",
                                    "Panel C. Specific-agent mentions"]):
        for condition, color, style in zip(data["conditions"],
                                          COLORS, LINE_STYLES):
            counts = [np.searchsorted(sorted(e["normalized_time"] for e in r[outcome]), grid, side="right")
                      for r in data["runs"] if r["condition"] == condition]
            ax.plot(grid, np.mean(counts, axis=0), color=color, linestyle=style,
                    linewidth=2.3, label=condition.capitalize())
        ax.set_title(label, fontsize=9)
        style_axes(ax, panels=3)
        ax.set_ylim(bottom=0)
    axes[0].set_ylabel("Mean cumulative count per run")
    layout.legend(axes[0])
    layout.save(output, "collaboration-three-panel")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["collect", "plot"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--brand", type=Path)
    args = parser.parse_args()
    if args.mode == "collect":
        if args.batch is None:
            parser.error("collect requires --batch")
        collect(args.batch, args.output)
    else:
        if args.brand is None:
            parser.error("plot requires --brand")
        plot(args.output, args.brand)

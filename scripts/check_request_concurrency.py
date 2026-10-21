"""Bounded Docker-free API diagnostic: ten two-turn tool sessions per request limit."""

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from dotenv import load_dotenv

from mad.config import load_config
from mad.harness import OpenRouterHarness
from mad.recording import Recorder, write_json
from mad.task import OptimizationTask
from mad.tools import ToolService


async def check(config_path, limit, output):
    cfg = load_config(config_path)
    cfg.agents = 10
    cfg.start_stagger_seconds = 0
    cfg.start_offsets_seconds = [0] * 10
    cfg.experiment_budget = 0
    cfg.max_turns = 2
    cfg.timeout_seconds = 90
    cfg.harness.request_concurrency = limit
    cfg.harness.continue_after_text_final = False
    values = [(cfg.task.lower + cfg.task.upper) / 2] * cfg.task.dimensions

    class Environment:
        def __init__(self):
            self.config = cfg
            self.author_ids = [f"concurrency-probe-{i}" for i in range(10)]

        async def file(self, agent, operation, **arguments):
            if operation != "read" or arguments.get("path") != "/workspace/task.md":
                raise ValueError("Only the preflight task file is available")
            return f"Now call submit(parameters={json.dumps(values)})."

        async def python(self, agent, code):
            raise ValueError("Python is not executed during this check")

    output.mkdir(parents=True)
    write_json(output / "config.json", cfg.model_dump(mode="json"))
    recorder = Recorder(output)
    environment = Environment()
    task = OptimizationTask(cfg, environment, recorder)
    service = ToolService(task, environment, recorder, 10)
    harness = OpenRouterHarness(cfg, service, recorder)

    async def run(agent):
        recorder.emit("agent_started", agent)
        try:
            async with asyncio.timeout(90):
                result = await harness.run(
                    agent,
                    "This is an API plumbing check. First call read_file with path "
                    "/workspace/task.md; then follow that file and call submit. Exactly "
                    "one tool per turn. Keep reasoning brief. Do not optimize or run experiments.",
                )
            report = {"agent": agent, "reason": result["reason"]}
        except Exception as error:
            report = {
                "agent": agent,
                "reason": "error",
                "error_type": type(error).__name__,
                "status_code": getattr(error, "status_code", None),
            }
        recorder.emit("agent_finished", agent, report=report)
        return report

    try:
        reports = await asyncio.gather(*(run(i) for i in range(10)))
    finally:
        await harness.close()
        recorder.close()
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    active, peak, requested, started = set(), 0, {}, {}
    queue, api, costs = [], [], []
    for event in events:
        agent, kind, t = event["agent"], event["kind"], event["elapsed_seconds"]
        if kind == "model_request":
            requested[agent] = t
        elif kind == "provider_request_started":
            active.add(agent)
            peak = max(peak, len(active))
            started[agent] = t
            queue.append(t - requested[agent])
        elif kind in {"provider_response_metadata", "provider_request_failed"}:
            active.discard(agent)
            api.append(t - started[agent])
            if kind == "provider_response_metadata":
                cost = event["metadata"].get("usage", {}).get("cost")
                if cost is not None:
                    costs.append(cost)
        elif kind == "agent_finished":
            active.discard(agent)
    errors = [e for e in events if e["kind"] == "provider_request_failed"]
    submitted = sum(r["reason"] == "submitted" for r in reports)
    report = {
        "kind": "zero-stagger API stress check; no scientific experiments",
        "request_limit": limit,
        "submitted": submitted,
        "agents": 10,
        "duration_seconds": max(e["elapsed_seconds"] for e in events)
        - min(e["elapsed_seconds"] for e in events if e["kind"] == "agent_started"),
        "peak_inflight_requests": peak,
        "mean_local_queue_seconds": statistics.mean(queue),
        "mean_api_seconds": statistics.mean(api) if api else None,
        "request_error_statuses": [e.get("status_code") for e in errors],
        "reported_cost_usd": sum(costs),
        "actual_providers": sorted(
            {e["actual_provider"] for e in events if e["kind"] == "provider_response_metadata"}
        ),
        "agent_reports": reports,
    }
    assert peak <= limit
    assert not any(e["kind"] == "experiment_started" for e in events)
    write_json(output / "summary.json", report)
    print(json.dumps(report), flush=True)
    return report


async def main(args):
    load_dotenv(Path.cwd() / ".env", override=False)
    reports = []
    for limit in [3, 10]:
        reports.append(await check(args.config, limit, args.output / f"limit-{limit}"))
    write_json(args.output / "comparison.json", reports)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    asyncio.run(main(parser.parse_args()))

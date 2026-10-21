"""Bounded live paired recovery check: native tool calls, no scientific experiments."""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from mad.config import load_config
from mad.harness import OpenRouterHarness
from mad.pause import PairPause
from mad.recording import Recorder, write_json
from mad.task import OptimizationTask
from mad.tools import ToolService


async def check(config_path, output):
    cfg = load_config(config_path)
    cfg.agents = 10
    cfg.experiment_budget = 0
    cfg.max_turns = 2
    cfg.timeout_seconds = 180
    cfg.harness.continue_after_text_final = False
    cfg.harness.coordinated_pause = True
    cfg.harness.max_pause_seconds = 180
    pause = PairPause(cfg.harness.max_pause_seconds)
    output.mkdir(parents=True, exist_ok=False)
    parameters = [(cfg.task.lower + cfg.task.upper) / 2] * cfg.task.dimensions
    reports, recorders = {}, []

    class Environment:
        def __init__(self, condition):
            self.config = cfg
            self.author_ids = [f"recovery-{condition}-{i}" for i in range(cfg.agents)]

        async def file(self, agent, operation, **arguments):
            if operation != "read" or arguments.get("path") != "/workspace/task.md":
                raise ValueError("Only the check task file is available")
            return f"Now call submit(parameters={json.dumps(parameters)})."

        async def python(self, agent, code):
            raise ValueError("Python is not executed during this check")

    async def condition(name):
        directory = output / name
        directory.mkdir()
        write_json(directory / "config.json", cfg.model_dump(mode="json"))
        recorder = Recorder(directory, pause)
        recorders.append(recorder)
        environment = Environment(name)
        task = OptimizationTask(cfg, environment, recorder)
        service = ToolService(task, environment, recorder, cfg.agents)
        harness = OpenRouterHarness(cfg, service, recorder)

        async def agent(i):
            report = {"agent": i}
            try:
                await pause.sleep(cfg.start_offsets_seconds[i])
                recorder.emit("agent_started", i)
                async with pause.timeout(cfg.timeout_seconds):
                    result = await harness.run(
                        i,
                        "This is a two-turn API compatibility check. First call read_file with "
                        "path /workspace/task.md. Then follow its instruction and call submit. "
                        "Use exactly one tool per turn. Keep reasoning brief. Do not optimize, "
                        "run experiments, or return a text-only answer.",
                    )
                report["reason"] = result["reason"]
            except Exception as error:
                report.update(
                    reason="error",
                    error_type=type(error).__name__,
                    status_code=getattr(error, "status_code", None),
                )
            recorder.emit("agent_finished", i, report=report)
            return report

        try:
            reports[name] = await asyncio.gather(*(agent(i) for i in range(cfg.agents)))
        finally:
            await harness.close()

    failure = None
    try:
        async with asyncio.timeout(600):
            async with asyncio.TaskGroup() as group:
                for name in ["control", "interact"]:
                    group.create_task(condition(name))
    except BaseException as error:
        await pause.abort()
        if isinstance(error, asyncio.CancelledError):
            raise
        failure = type(error).__name__
    finally:
        await pause.close()
        for recorder in recorders:
            recorder.close()
    events = {
        name: [
            json.loads(line) for line in (output / name / "events.jsonl").read_text().splitlines()
        ]
        for name in ["control", "interact"]
    }
    calls_during_freeze = []
    for name, stream in events.items():
        frozen = False
        for event in stream:
            if event["kind"] == "cohort_pause_started":
                frozen = True
            elif event["kind"] == "cohort_pause_clock_resumed":
                frozen = False
            elif frozen and event["kind"] in {
                "provider_request_started",
                "tool_called",
                "submission",
            }:
                calls_during_freeze.append([name, event["sequence"], event["kind"]])
    receipts = [
        e for stream in events.values() for e in stream if e["kind"] == "provider_response_metadata"
    ]
    costs = [(e["metadata"].get("usage") or {}).get("cost") for e in receipts]
    summary = {
        "kind": "live paired native-tool recovery check; no scientific experiments",
        "model": cfg.harness.routes[0].model,
        "status": "passed"
        if failure is None
        and sum(r["reason"] == "submitted" for rs in reports.values() for r in rs) == 20
        and not calls_during_freeze
        else "failed",
        "agents": 20,
        "agent_reports": reports,
        "failure": failure,
        "pause_count": pause.pause_count,
        "paused_seconds": pause.paused_seconds,
        "pause_exercised": pause.pause_count > 0,
        "calls_during_freeze": calls_during_freeze,
        "experiments": sum(e["kind"] == "experiment_started" for es in events.values() for e in es),
        "request_failures": sum(
            e["kind"] == "provider_request_failed" for es in events.values() for e in es
        ),
        "reported_responses": sum(c is not None for c in costs),
        "missing_costs": sum(c is None for c in costs),
        "reported_cost_usd": sum(c for c in costs if c is not None),
        "condition_wall_seconds": {
            name: max(e["elapsed_seconds"] for e in es) for name, es in events.items()
        },
        "condition_active_seconds": {
            name: max(e["active_elapsed_seconds"] for e in es) for name, es in events.items()
        },
    }
    assert summary["experiments"] == 0
    write_json(output / "summary.json", summary)
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env", override=False)
    result = asyncio.run(check(args.config, args.output))
    raise SystemExit(0 if result["status"] == "passed" else 1)

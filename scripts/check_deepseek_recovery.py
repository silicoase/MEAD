"""Bounded live tool-validation diagnostics; no Docker or experimental measurements."""

import argparse
import asyncio
import json
import math
from pathlib import Path

from dotenv import load_dotenv

from mad.config import load_config
from mad.harness import OpenRouterHarness
from mad.recording import Recorder, write_json
from mad.task import OptimizationTask
from mad.tools import ToolService


async def probe(model, mode, repetition, root):
    cfg = load_config(Path("experiments/cross-provider-tinkering/deepseek/config.toml"))
    cfg.agents = 1
    cfg.start_stagger_seconds = 0
    cfg.start_offsets_seconds = [0]
    cfg.max_turns = 6
    cfg.experiment_budget = 0
    cfg.timeout_seconds = 90
    cfg.harness.routes[0].model = model
    cfg.harness.routes[0].provider = None
    cfg.harness.request_concurrency = 1
    valid = [0.5] * 8

    class Environment:
        def __init__(self):
            self.config = cfg
            self.author_ids = ["recovery-diagnostic-only"]

        async def file(self, agent, operation, **arguments):
            if operation != "read" or arguments.get("path") != "/workspace/task.md":
                raise ValueError("Only the diagnostic task file is available")
            if mode == "validation":
                return (
                    "This is a validator test. First deliberately call submit with "
                    "parameters [-0.5, -0.5, -0.5, -0.5, -0.5, -0.5, -0.5, -0.5]. "
                    "That call should fail because values must be in [0, 1]. "
                    f"After the rejection, correct the arguments and call submit with {valid}."
                )
            return f"Now call submit(parameters={valid})."

        async def python(self, agent, code):
            raise ValueError("Python is not executed in this diagnostic")

    directory = root / f"{model.rsplit('/', 1)[1]}-{mode}-{repetition}"
    directory.mkdir(parents=True)
    recorder = Recorder(directory)
    write_json(directory / "config.json", cfg.model_dump(mode="json"))
    environment = Environment()
    task = OptimizationTask(cfg, environment, recorder)
    service = ToolService(task, environment, recorder, 1)
    harness = OpenRouterHarness(cfg, service, recorder)
    report = {"model": model, "mode": mode, "repetition": repetition, "submitted": False}
    try:
        async with asyncio.timeout(90):
            instructions = (
                "This is a bounded API tool-validation diagnostic, not an optimization task. "
                "First call read_file with path /workspace/task.md, then follow its instructions. "
                "Use native tool calls, one per turn. Keep reasoning brief. Do not run experiments. "
                "If a tool returns a validation error, use its feedback to correct the arguments "
                "and try again within the remaining turn allowance."
            )
            if mode == "legacy":
                instructions = (
                    "This is a two-turn API compatibility check. First call read_file with "
                    "path /workspace/task.md. Then follow its instruction and call submit. "
                    "Use exactly one tool per turn. Keep reasoning brief. Do not optimize, "
                    "run experiments, or return a text-only answer."
                )
            result = await harness.run(0, instructions)
        report.update(
            reason=result["reason"],
            submitted=result["reason"] == "submitted",
            continuations_used=result["text_final_continuations_used"],
        )
    except Exception as error:
        report.update(
            reason="error",
            error_type=type(error).__name__,
            status_code=getattr(error, "status_code", None),
        )
    finally:
        await harness.close()
        recorder.close()
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    errors = [
        e
        for e in events
        if e["kind"] == "tool_result" and isinstance(e["result"], dict) and e["result"].get("error")
    ]
    bad_calls = []
    for e in events:
        if e["kind"] != "provider_response_metadata":
            continue
        for choice in e["metadata"].get("choices", []):
            for call in choice["message"].get("tool_calls") or []:
                if call["function"]["name"] != "submit":
                    continue
                raw = call["function"]["arguments"]
                try:
                    values = json.loads(raw)["parameters"]
                    valid_args = (
                        isinstance(values, list)
                        and len(values) == 8
                        and all(
                            isinstance(v, (int, float))
                            and not isinstance(v, bool)
                            and math.isfinite(v)
                            and 0 <= v <= 1
                            for v in values
                        )
                    )
                except (ValueError, KeyError, TypeError):
                    valid_args = False
                if not valid_args:
                    bad_calls.append(
                        {
                            "sequence": e["sequence"],
                            "provider": e["actual_provider"],
                            "arguments": raw,
                        }
                    )
    receipts = [e for e in events if e["kind"] == "provider_response_metadata"]
    costs = [e["metadata"].get("usage", {}).get("cost") for e in receipts]
    report.update(
        model_turns=sum(e["kind"] == "model_request" for e in events),
        tool_validation_errors=[e["result"] for e in errors],
        invalid_native_submit_calls=bad_calls,
        recovered_after_invalid_call=bool(bad_calls) and report["submitted"],
        actual_providers=sorted({e["actual_provider"] for e in receipts}),
        reported_cost_usd=sum(c for c in costs if c is not None),
        missing_cost_receipts=sum(c is None for c in costs),
        directory=str(directory.resolve()),
    )
    assert not any(e["kind"] == "experiment_started" for e in events)
    write_json(directory / "summary.json", report)
    print(json.dumps(report), flush=True)
    return report


async def main(args):
    load_dotenv(Path.cwd() / ".env", override=False)
    if args.output.exists():
        raise ValueError("Use a fresh output directory")
    reports = []
    for model in args.models:
        for mode in args.modes:
            for repetition in range(1, args.repetitions + 1):
                reports.append(await probe(model, mode, repetition, args.output))
                write_json(
                    args.output / "summary.json",
                    {
                        "reports": reports,
                        "reported_cost_usd": sum(r["reported_cost_usd"] for r in reports),
                    },
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--models", nargs="+", default=["deepseek/deepseek-v3.2", "deepseek/deepseek-v3.1-terminus"]
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["natural", "validation", "legacy"],
        default=["natural", "validation"],
    )
    parser.add_argument("--repetitions", type=int, choices=range(1, 4), default=2)
    asyncio.run(main(parser.parse_args()))

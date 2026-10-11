"""Two-turn native-tool compatibility checks; no sandbox or measurements."""

import asyncio
import json
import os
from pathlib import Path

from .config import RolloutConfig
from .harness import OpenAIHarness, OpenRouterHarness
from .recording import Recorder, write_json
from .task import OptimizationTask
from .tools import ToolService


async def preflight_model(config: RolloutConfig, output: Path, *, model=None) -> dict:
    if config.harness.kind not in {"openai", "openrouter"}:
        raise ValueError("preflight requires an API harness")
    if not {"read_file", "submit"}.issubset(config.tools):
        raise ValueError("preflight requires read_file and submit in the configured tools")
    key = "OPENROUTER_API_KEY" if config.harness.kind == "openrouter" else "OPENAI_API_KEY"
    if model is None and not os.environ.get(key):
        raise ValueError(f"{key} is required for preflight")
    if output.exists():
        raise ValueError("preflight output must be a new directory")
    cfg = config.model_copy(deep=True)
    cfg.agents = 1
    cfg.start_stagger_seconds = 0
    cfg.start_offsets_seconds = [0]
    cfg.experiment_budget = 0
    cfg.max_turns = 2
    cfg.harness.continue_after_text_final = False
    # Compatibility is a strict 90-second wall-time probe, not a paired episode.
    cfg.harness.coordinated_pause = False
    # Probe exactly one route; callers check each distinct route separately.
    cfg.harness.routes = cfg.harness.routes[:1]
    parameters = [(cfg.task.lower + cfg.task.upper) / 2] * cfg.task.dimensions

    class Environment:
        def __init__(self):
            self.config = cfg
            self.author_ids = ["preflight-only"]

        async def file(self, agent, operation, **arguments):
            if operation != "read" or arguments.get("path") != "/workspace/task.md":
                raise ValueError("preflight only provides /workspace/task.md")
            return f"Now call submit(parameters={json.dumps(parameters)})."

        async def python(self, agent, code):
            raise ValueError("Python is not executed during preflight")

    output.mkdir(parents=True)
    recorder = Recorder(output)
    environment = Environment()
    task = OptimizationTask(cfg, environment, recorder)
    service = ToolService(task, environment, recorder, 1)
    harness_class = OpenRouterHarness if cfg.harness.kind == "openrouter" else OpenAIHarness
    harness = harness_class(cfg, service, recorder, model=model)
    report = {
        "kind": "native-tool preflight; no scientific experiments",
        "model": harness.model_name(0),
        "status": "failed",
    }
    write_json(output / "config.json", cfg.model_dump(mode="json"))
    try:
        async with asyncio.timeout(min(90, cfg.timeout_seconds)):
            result = await harness.run(
                0,
                "This is a two-turn API compatibility check. First call read_file with "
                "path /workspace/task.md. Then follow its instruction and call submit. "
                "Use exactly one tool per turn. Keep reasoning brief. Do not optimize, "
                "run experiments, or return a text-only answer.",
            )
        report["termination_reason"] = result["reason"]
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["status_code"] = getattr(error, "status_code", None)
    finally:
        try:
            await harness.close()
        finally:
            recorder.close()
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    report["tool_sequence"] = [e["tool"] for e in events if e["kind"] == "tool_called"]
    tool_results = [e["result"] for e in events if e["kind"] == "tool_result"]
    receipts = [e for e in events if e["kind"] == "provider_response_metadata"]
    costs = [e["metadata"].get("usage", {}).get("cost") for e in receipts]
    report["reported_cost_usd"] = sum(c for c in costs if c is not None)
    report["receipts_missing_cost"] = sum(c is None for c in costs)
    report["actual_providers"] = sorted(
        {e["actual_provider"] for e in receipts if e.get("actual_provider")}
    )
    native_turns = [
        [item["name"] for item in e["output"] if item.get("type") == "function_call"]
        for e in events
        if e["kind"] == "model_response"
    ]
    report["model_turns"] = sum(e["kind"] == "model_request" for e in events)
    if (
        report.get("termination_reason") == "submitted"
        and report["model_turns"] == 2
        and native_turns == [["read_file"], ["submit"]]
        and report["tool_sequence"] == ["read_file", "submit"]
        and len(tool_results) == 2
        and not any(isinstance(r, dict) and "error" in r for r in tool_results)
    ):
        report["status"] = "passed"
    write_json(output / "summary.json", report)
    return report

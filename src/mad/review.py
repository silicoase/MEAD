"""Export recorded evidence as a self-contained, offline HTML run explorer."""

import json
import os
import tarfile
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

from .config import RolloutConfig
from .harness import sdk_tools
from .objective_reference import objective_reference
from .recording import timestamp, write_json


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def context_growth(events: list[dict]) -> list[dict]:
    """Per-call provider usage; cumulative input is spend, not context size."""
    pending = {}
    turns = {}
    totals = {}
    points = []
    for event in events:
        agent = event.get("agent")
        if event["kind"] == "model_request":
            pending[agent] = event
        elif event["kind"] == "model_response":
            request = pending.pop(agent, None)
            turns[agent] = turns.get(agent, 0) + 1
            usage = event.get("usage") or {}
            input_tokens = usage.get("input_tokens")
            if not isinstance(input_tokens, (int, float)) or isinstance(input_tokens, bool):
                continue
            totals[agent] = totals.get(agent, 0) + input_tokens
            details = usage.get("input_tokens_details")
            cached = details.get("cached_tokens") if isinstance(details, dict) else None
            points.append(
                {
                    "agent": agent,
                    "turn": turns[agent],
                    "sequence": event["sequence"],
                    "elapsed_seconds": (request or event).get("elapsed_seconds", 0),
                    "input_tokens": input_tokens,
                    "output_tokens": usage.get("output_tokens"),
                    "cached_tokens": cached,
                    "cumulative_input_tokens": totals[agent],
                }
            )
    return points


def collaboration_flags(events: list[dict], summary: dict, ownership: dict) -> list[dict]:
    """Observable candidates, never inferred intent or a collaboration score."""
    flags = []
    pending = {}
    measurements = {}
    for event in events:
        agent = event.get("agent")
        kind = event["kind"]
        if kind == "experiment_completed":
            record = event["record"]
            measurements[f"/lab/runs/{record['run_id']}.json"] = agent
        elif kind == "tool_called":
            pending[agent] = event
        elif kind == "tool_result":
            call = pending.pop(agent, None)
            result = event.get("result")
            if not call or (isinstance(result, dict) and "error" in result):
                continue
            path = call.get("arguments", {}).get("path", "")
            if call["tool"] == "read_file":
                owner = measurements.get(path)
                if path.startswith("/lab/notes/"):
                    filename = path.removeprefix("/lab/notes/")
                    # Creator ownership never changes in this implementation.
                    owner = ownership.get(f"notes/all/{filename}")
                if owner is not None and owner != agent:
                    flags.append(
                        {
                            "agent": agent,
                            "peer": owner,
                            "label": "Read a peer artifact",
                            "sequence": call["sequence"],
                            "detail": path,
                            "strength": "Observed access; intent unknown",
                        }
                    )
            elif call["tool"] in ("write_file", "append_file") and path.startswith("/lab/notes/"):
                text = call.get("arguments", {}).get("content", "")
                for owned_path, owner in ownership.items():
                    name = owned_path.rsplit("/", 1)[-1]
                    if owner != agent and name in text:
                        flags.append(
                            {
                                "agent": agent,
                                "peer": owner,
                                "label": "Note mentions a peer filename",
                                "sequence": call["sequence"],
                                "detail": name,
                                "strength": "Possible reference; inspect context",
                            }
                        )
    for event in events:
        if event["kind"] != "submission":
            continue
        agent = event["agent"]
        earlier = [
            e
            for e in events
            if e["kind"] == "experiment_completed" and e["sequence"] < event["sequence"]
        ]
        own = any(
            e["agent"] == agent and e["record"]["parameters"] == event["parameters"]
            for e in earlier
        )
        peers = {
            e["agent"]
            for e in earlier
            if e["agent"] != agent and e["record"]["parameters"] == event["parameters"]
        }
        if peers and not own:
            flags.append(
                {
                    "agent": agent,
                    "peer": sorted(peers),
                    "label": "Submitted a configuration measured only by peers",
                    "sequence": event["sequence"],
                    "detail": event["parameters"],
                    "strength": "Matching configuration; reuse not established",
                }
            )
    return flags


def load_run(directory: Path) -> dict:
    if not (directory / "config.json").exists():
        raise ValueError("run directory must contain config.json")
    config = read_json(directory / "config.json", {})
    events = []
    notices = []
    path = directory / "events.jsonl"
    if path.exists():
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                if index == len(lines) - 1:
                    notices.append(
                        "Ignored an incomplete final event line; the run may be in progress."
                    )
                else:
                    raise ValueError(f"invalid event JSON on line {index + 1}") from None
    summary = read_json(directory / "summary.json", {})
    runtime = read_json(directory / "runtime.json", {})
    ownership = read_json(directory / "note_ownership.json", {})
    interfaces = {
        str(e["agent"]): {"source": "Recorded at execution", **e}
        for e in events
        if e["kind"] == "agent_interface"
    }
    recovered = read_json(directory / "interfaces_recovered.json", {})
    for agent, interface in recovered.items():
        if agent not in interfaces:
            interfaces[agent] = interface
    missing = [agent for agent in range(config.get("agents", 0)) if str(agent) not in interfaces]
    if missing:
        parsed = RolloutConfig.model_validate(config)
        tools = sdk_tools(SimpleNamespace(environment=SimpleNamespace(config=parsed)), 0)
        manifest = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.params_json_schema,
            }
            for tool in tools
        ]
        for agent in missing:
            instructions = next(
                (
                    e.get("system_prompt") or e.get("instructions")
                    for e in events
                    if e.get("agent") == agent and e["kind"] in ("model_request", "agent_started")
                ),
                "Not recorded",
            )
            interfaces[str(agent)] = {
                "instructions": instructions,
                "tools": manifest,
                "source": "Prompts recorded; tools from current MAD (not recorded for this run)",
            }
        notices.append(
            "Tool definitions were not recorded for this run. Current definitions are shown; "
            "new runs record their exact interfaces."
        )
    if not summary:
        notices.append("No final summary exists. This is a snapshot of available events.")
    artifacts = []
    preview_budget = 5_000_000
    archive = directory / "artifacts.tar"
    if archive.exists():
        with tarfile.open(archive) as tar:
            for member in tar:
                if not member.isfile() and not member.issym():
                    continue
                artifact = {
                    "path": member.name.removeprefix("./"),
                    "bytes": member.size,
                    "uid": member.uid,
                    "symlink": member.linkname if member.issym() else None,
                }
                if member.isfile() and member.size <= 1_000_000 and member.size <= preview_budget:
                    data = tar.extractfile(member).read()
                    preview_budget -= len(data)
                    try:
                        text = data.decode("utf-8")
                        if "\x00" not in text:
                            artifact["text"] = text
                    except UnicodeDecodeError:
                        pass
                artifacts.append(artifact)
    return {
        "name": directory.name,
        "config": config,
        "runtime": runtime,
        "identities": read_json(directory / "identities.json", []),
        "summary": summary,
        "events": events,
        "interfaces": interfaces,
        "artifacts": artifacts,
        "notices": notices,
        "flags": collaboration_flags(events, summary, ownership),
        "context": context_growth(events),
        "objective_reference": read_json(directory / "objective_reference.json"),
    }


def recover_interfaces(directory: Path, client=None) -> dict:
    """Read stored provider responses; never generate new responses or rewrite events."""
    data = load_run(directory)
    destination = directory / "interfaces_recovered.json"
    recovered = read_json(destination, {})
    recorded = {
        str(event["agent"]) for event in data["events"] if event["kind"] == "agent_interface"
    }
    missing = [
        agent
        for agent in range(data["config"]["agents"])
        if str(agent) not in recorded and str(agent) not in recovered
    ]
    if not missing:
        return recovered
    owned_client = client is None
    if owned_client:
        from openai import OpenAI

        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required to retrieve stored response metadata")
        client = OpenAI(timeout=30, max_retries=0)
    try:
        for agent in missing:
            response_event = next(
                (
                    event
                    for event in data["events"]
                    if event.get("agent") == agent
                    and event["kind"] == "model_response"
                    and event.get("response_id")
                ),
                None,
            )
            if response_event is None:
                raise ValueError(f"agent {agent} has no recorded provider response ID")
            try:
                response = client.responses.retrieve(response_event["response_id"])
            except Exception as error:
                status = getattr(error, "status_code", "unavailable")
                raise ValueError(
                    f"could not retrieve agent {agent}'s stored response "
                    f"(status {status}); it may be unavailable or expired"
                ) from None
            if response.id != response_event["response_id"]:
                raise ValueError("provider response ID does not match recorded response")
            raw_tools = [tool.model_dump(mode="json") for tool in response.tools]
            tools = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                    "strict": tool.get("strict"),
                }
                for tool in raw_tools
                if tool.get("type") == "function"
            ]
            instructions = next(
                (
                    event["system_prompt"]
                    for event in data["events"]
                    if event.get("agent") == agent and event["kind"] == "model_request"
                ),
                response.instructions or "Not recorded",
            )
            recovered[str(agent)] = {
                "source": "Tools recovered from stored OpenAI response; prompts recorded",
                "instructions": instructions,
                "tools": tools,
                "provider_response_id": response.id,
                "provider_model": response.model,
                "provider_created_at": response.created_at,
                "retrieved_at": timestamp(),
                "provider_tools": raw_tools,
            }
            # Preserve partial recovery if a later response is unavailable.
            write_json(destination, recovered)
    finally:
        if owned_client:
            client.close()
    return recovered


def export_review(directory: Path, destination: Path | None = None) -> Path:
    data = load_run(directory)
    task = RolloutConfig.model_validate(data["config"]).task
    reference = data["objective_reference"]
    if (
        not reference
        or reference.get("task") != task.model_dump(mode="json")
        or reference.get("method")
        != "Synthetic objective v1: Taylor branch-and-bound (floating-point estimate)"
    ):
        reference = objective_reference(task)
        write_json(directory / "objective_reference.json", reference)
    data["objective_reference"] = reference
    destination = destination or directory / "review.html"
    # Escape HTML parser delimiters even inside a non-executable JSON script.
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    template = files("mad").joinpath("templates/review.html").read_text()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template.replace("__MAD_RUN_DATA__", payload))
    return destination

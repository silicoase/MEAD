import json

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI, RateLimitError
from pydantic import ValidationError

from mad.config import RolloutConfig, load_config
from mad.harness import OpenRouterHarness
from mad.recording import Recorder
from mad.rollout import run_rollout
from mad.task import OptimizationTask
from mad.tools import ToolService


def config(**kwargs):
    return RolloutConfig(
        agents=1,
        tools=["submit"],
        harness={
            "kind": "openrouter",
            "routes": [
                {
                    "model": "qwen/test-version",
                    "provider": "deepinfra/fp8",
                }
            ],
            "max_tokens": 4096,
        },
        **kwargs,
    )


@pytest.mark.parametrize(
    "harness,agents",
    [
        ({"kind": "openrouter"}, 1),
        ({"kind": "openrouter", "routes": [{"model": "qwen/test", "provider": ""}]}, 1),
        ({"kind": "openrouter", "routes": [{"model": "qwen/test", "provider": "x"}] * 2}, 3),
        ({"kind": "openai", "routes": [{"model": "qwen/test", "provider": "x"}]}, 1),
        (
            {
                "kind": "openrouter",
                "reasoning_summary": "auto",
                "routes": [{"model": "qwen/test", "provider": "x"}],
            },
            1,
        ),
    ],
)
def test_invalid_routes_fail_offline(harness, agents):
    with pytest.raises(ValidationError):
        RolloutConfig(agents=agents, harness=harness)


async def test_openrouter_requires_its_own_key_before_creating_output(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        await run_rollout(config(), output)
    assert not output.exists()


class Environment:
    def __init__(self, cfg):
        self.config = cfg
        self.author_ids = ["test-author"]


@pytest.mark.parametrize("pinned", [True, False])
@pytest.mark.parametrize("plain_reasoning", [None, "Choosing a configuration."])
async def test_pinned_http_request_runs_tool_loop_and_preserves_provenance(
    tmp_path, plain_reasoning, pinned
):
    requests = []
    reasoning_details = [
        {"type": "reasoning.text", "text": "Choosing a configuration.", "index": 0},
        {"type": "reasoning.encrypted", "data": "opaque-signed-payload", "index": 1},
    ]

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert body["model"] == "qwen/test-version"
        expected = {"allow_fallbacks": not pinned, "require_parameters": True}
        if pinned:
            expected["only"] = ["deepinfra/fp8"]
        assert body["provider"] == expected
        assert "models" not in body and "parallel_tool_calls" not in body
        assert body["max_tokens"] == 4096
        assert body["tools"][0]["function"]["name"] == "submit"
        if len(requests) == 2:
            assistant = next(m for m in body["messages"] if m["role"] == "assistant")
            assert assistant["reasoning_details"] == reasoning_details
            if plain_reasoning is None:
                assert "reasoning" not in assistant
            else:
                assert assistant["reasoning"] == plain_reasoning
            assert all(
                "reasoning_details" not in m for m in body["messages"] if m["role"] != "assistant"
            )
        # Reject first invalid submission, then finish on the valid one.
        parameters = [0.5] if len(requests) == 1 else [0.5] * 8
        return httpx.Response(
            200,
            headers={"x-request-id": "upstream-request"},
            json={
                "id": f"gen-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "qwen/resolved-version",
                "provider": "DeepInfra",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning": plain_reasoning,
                            "reasoning_details": reasoning_details,
                            "tool_calls": [
                                {
                                    "id": f"call-{len(requests)}",
                                    "type": "function",
                                    "function": {
                                        "name": "submit",
                                        "arguments": json.dumps({"parameters": parameters}),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 20,
                    "cost": 0.0001,
                    "completion_tokens_details": {"reasoning_tokens": 3},
                },
            },
        )

    async with AsyncOpenAI(
        api_key="test-secret",
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    ) as client:
        cfg = config()
        if not pinned:
            cfg.harness.routes[0].provider = None
        recorder = Recorder(tmp_path)
        env = Environment(cfg)
        task = OptimizationTask(cfg, env, recorder)
        service = ToolService(task, env, recorder, 1)
        harness = OpenRouterHarness(cfg, service, recorder, client=client)
        try:
            result = await harness.run(0, task.instructions(0))
        finally:
            await harness.close()
            recorder.close()
    assert result["reason"] == "submitted"
    assert len(requests) == 2
    assert requests[1]["messages"][-1]["role"] == "tool"
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    metadata = [e for e in events if e["kind"] == "provider_response_metadata"]
    assert len(metadata) == 2
    assert metadata[0]["actual_provider"] == "DeepInfra"
    assert metadata[0]["actual_model"] == "qwen/resolved-version"
    assert metadata[0]["metadata"]["usage"]["cost"] == 0.0001
    assert metadata[0]["metadata"]["usage"]["completion_tokens_details"]["reasoning_tokens"] == 3
    assert metadata[0]["latency_seconds"] >= 0
    responses = [e for e in events if e["kind"] == "model_response"]
    assert responses[-1]["response_id"] == "gen-2"
    assert metadata[0]["request_id"] == "upstream-request"
    assert "test-secret" not in json.dumps(events)


async def test_rate_limit_is_recorded_without_retry_or_fallback(tmp_path):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(429, json={"error": {"message": "host unavailable", "code": 429}})

    async with AsyncOpenAI(
        api_key="test-secret",
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    ) as client:
        cfg = config()
        recorder = Recorder(tmp_path)
        env = Environment(cfg)
        task = OptimizationTask(cfg, env, recorder)
        service = ToolService(task, env, recorder, 1)
        try:
            with pytest.raises(RateLimitError):
                await OpenRouterHarness(cfg, service, recorder, client=client).run(
                    0, task.instructions(0)
                )
        finally:
            recorder.close()
    assert len(requests) == 1
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    failure = next(e for e in events if e["kind"] == "provider_request_failed")
    assert failure["status_code"] == 429
    assert failure["route"]["provider"] == "deepinfra/fp8"
    assert not any(e["kind"] == "model_response" for e in events)


def test_mixed_routes_select_agent_model_and_host():
    routes = [
        {"model": "qwen/one", "provider": "together"},
        {"model": "deepseek/two", "provider": "deepinfra/fp8"},
    ]
    cfg = RolloutConfig(agents=2, harness={"kind": "openrouter", "routes": routes})
    harness = OpenRouterHarness(cfg, None, None)
    assert harness.model_name(0) == "qwen/one"
    assert harness.model_name(1) == "deepseek/two"
    assert harness.model_settings(1).extra_body["provider"]["only"] == ["deepinfra/fp8"]
    shared = OpenRouterHarness(config(), None, None)
    assert shared.model_name(0) == "qwen/test-version"


def test_pilot_config_is_valid():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / "examples/cross-provider/config.toml")
    assert cfg.agents == 10
    assert cfg.experiment_budget == 10
    assert len(cfg.harness.routes) == 1


async def test_reasoning_is_isolated_between_agents_sharing_http_client(tmp_path):
    import asyncio

    counts = {}

    def handle(request):
        body = json.loads(request.content)
        name = body["model"]
        counts[name] = counts.get(name, 0) + 1
        if counts[name] == 2:
            assistant = next(m for m in body["messages"] if m["role"] == "assistant")
            assert assistant["reasoning_details"][0]["data"] == name
        parameters = [0.5] if counts[name] == 1 else [0.5] * 8
        return httpx.Response(
            200,
            json={
                "id": f"gen-{name}-{counts[name]}",
                "object": "chat.completion",
                "created": 1,
                "model": name,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_details": [{"type": "reasoning.encrypted", "data": name}],
                            # Deliberately collide call IDs across agents to check session isolation.
                            "tool_calls": [
                                {
                                    "id": f"call-{counts[name]}",
                                    "type": "function",
                                    "function": {
                                        "name": "submit",
                                        "arguments": json.dumps({"parameters": parameters}),
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    cfg = RolloutConfig(
        agents=2,
        tools=["submit"],
        harness={
            "kind": "openrouter",
            "routes": [
                {"model": "minimax/test", "provider": "google-vertex"},
                {"model": "moonshotai/test", "provider": "google-vertex"},
            ],
        },
    )
    recorder = Recorder(tmp_path)
    env = Environment(cfg)
    task = OptimizationTask(cfg, env, recorder)
    service = ToolService(task, env, recorder, 2)
    try:
        async with AsyncOpenAI(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as client:
            harness = OpenRouterHarness(cfg, service, recorder, client=client)
            results = await asyncio.gather(
                harness.run(0, task.instructions(0)), harness.run(1, task.instructions(0))
            )
        assert all(r["reason"] == "submitted" for r in results)
        assert counts == {"minimax/test": 2, "moonshotai/test": 2}
    finally:
        recorder.close()


@pytest.mark.parametrize("status", [200, 429, 500, 502, 503, 504])
async def test_same_host_rate_retry_does_not_repeat_tool_actions(tmp_path, status):
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            if status == 200:
                return httpx.Response(
                    200,
                    json={
                        "id": "bad-upstream",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "qwen/test-version",
                        "choices": None,
                        "error": {"code": 400, "message": "Upstream error: unexpected end of data"},
                    },
                )
            return httpx.Response(status, json={"error": {"message": "temporary upstream failure"}})
        return httpx.Response(
            200,
            json={
                "id": "gen-success",
                "object": "chat.completion",
                "created": 1,
                "model": "qwen/test-version",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-submit",
                                    "type": "function",
                                    "function": {
                                        "name": "submit",
                                        "arguments": json.dumps({"parameters": [0.5] * 8}),
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    cfg = config()
    cfg.harness.request_retries = 1
    cfg.harness.retry_backoff_seconds = 0.01
    cfg.harness.request_concurrency = 1
    recorder = Recorder(tmp_path)
    env = Environment(cfg)
    task = OptimizationTask(cfg, env, recorder)
    service = ToolService(task, env, recorder, 1)
    try:
        async with AsyncOpenAI(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as client:
            result = await OpenRouterHarness(cfg, service, recorder, client=client).run(
                0, task.instructions(0)
            )
        assert result["reason"] == "submitted"
    finally:
        recorder.close()
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert sum(e["kind"] == "tool_called" for e in events) == 1
    assert sum(e["kind"] == "provider_request_retry" for e in events) == 1
    failure = next(e for e in events if e["kind"] == "provider_request_failed")
    assert failure["attempt"] == 1 and failure["will_retry"] is True
    metadata = next(e for e in events if e["kind"] == "provider_response_metadata")
    assert metadata["attempt"] == 2


async def test_empty_truncation_is_costed_and_not_retried(tmp_path):
    from mad.harness import EmptyTruncatedResponseError

    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "gen-truncated",
                "object": "chat.completion",
                "created": 1,
                "model": "qwen/test-version",
                "provider": "test-provider",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning": "Unfinished analysis.",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 4096,
                    "total_tokens": 4108,
                    "cost": 0.01,
                },
            },
        )

    async with AsyncOpenAI(
        api_key="test-secret",
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    ) as client:
        cfg = config()
        recorder = Recorder(tmp_path)
        env = Environment(cfg)
        task = OptimizationTask(cfg, env, recorder)
        service = ToolService(task, env, recorder, 1)
        harness = OpenRouterHarness(cfg, service, recorder, client=client)
        try:
            with pytest.raises(EmptyTruncatedResponseError):
                await harness.run(0, task.instructions(0))
        finally:
            await harness.close()
            recorder.close()
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert len(requests) == 1
    receipts = [e for e in events if e["kind"] == "provider_response_metadata"]
    assert len(receipts) == 1 and receipts[0]["metadata"]["usage"]["cost"] == 0.01
    assert sum(e["kind"] == "empty_truncated_response" for e in events) == 1
    assert not any(
        e["kind"] in {"tool_called", "submission", "provider_request_retry"} for e in events
    )

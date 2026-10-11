import asyncio
import json

import pytest
from agents import Model
from agents.items import ModelResponse
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseReasoningItem

from mad.config import RolloutConfig
from mad.harness import OpenAIHarness, sdk_tools
from mad.recording import Recorder
from mad.task import OptimizationTask
from mad.tools import ToolService


class Publisher:
    def __init__(self, config):
        self.config = config
        self.author_ids = ["opaque-test-author"] * config.agents

    async def publish_run(self, agent, record):
        pass


class FakeModel(Model):
    def __init__(self):
        self.calls = 0
        self.settings = []

    async def get_response(self, *args, **kwargs):
        self.calls += 1
        self.settings.append(kwargs.get("model_settings"))
        # Invalid submission must not end the session; then measure, then submit.
        name = "experiment" if self.calls == 2 else "submit"
        parameters = [0.5] if self.calls == 1 else [0.5] * 8
        return ModelResponse(
            output=[
                ResponseReasoningItem(
                    id=f"reason-{self.calls}",
                    type="reasoning",
                    summary=[{"type": "summary_text", "text": "Choosing the next tool."}],
                ),
                ResponseFunctionToolCall(
                    id=f"fc-{self.calls}",
                    call_id=f"call-{self.calls}",
                    type="function_call",
                    name=name,
                    arguments=json.dumps({"parameters": parameters}),
                ),
            ],
            usage=Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15),
            response_id=f"response-{self.calls}",
            request_id=f"request-{self.calls}",
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


async def test_real_sdk_loop_retries_invalid_submission_and_stops_on_success(tmp_path):
    recorder = Recorder(tmp_path)
    config = RolloutConfig(agents=1, experiment_budget=1, harness={"reasoning_summary": "auto"})
    task = OptimizationTask(config, Publisher(config), recorder)
    service = ToolService(task, Publisher(config), recorder, 1)
    model = FakeModel()
    # Host-only review data must not be forwarded into the SDK's agent context.
    private_reference = {"estimated_maximum": 987654321.125, "reviewer_note": "review-only-canary"}
    (tmp_path / "objective_reference.json").write_text(json.dumps(private_reference))
    try:
        harness = OpenAIHarness(config, service, recorder, model=model)
        result = await harness.run(0, task.instructions(1))
        assert result["reason"] == "submitted"
        assert model.calls == 3
        assert all(settings.reasoning.summary == "auto" for settings in model.settings)
        assert result["usage"]["requests"] == 3
        assert task.report(0)["experiments_used"] == 1
        # No tools execute after accepted submission.
        assert "error" in await service.call(0, "experiment", parameters=[0.5] * 8)
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        assert sum(e["kind"] == "model_request" for e in events) == 3
        assert sum(e["kind"] == "model_response" for e in events) == 3
        responses = [e for e in events if e["kind"] == "model_response"]
        assert [e["request_id"] for e in responses] == [f"request-{i}" for i in (1, 2, 3)]
        requests = [e for e in events if e["kind"] == "model_request"]
        assert all(e["model_settings"]["reasoning"]["summary"] == "auto" for e in requests)
        agent_context = json.dumps(
            [e for e in events if e["kind"] in ("model_request", "agent_interface")]
        )
        assert "review-only-canary" not in agent_context
        assert str(private_reference["estimated_maximum"]) not in agent_context
        assert all(
            e["output"][0]["summary"][0]["text"] == "Choosing the next tool."
            for e in events
            if e["kind"] == "model_response"
        )
    finally:
        recorder.close()


async def test_provider_metadata_survives_sdk_normalization(tmp_path, monkeypatch):
    from agents.models.openai_responses import OpenAIResponsesModel
    from openai.types.responses import Response

    response = Response.model_construct(
        id="response-test",
        model="provider-model-version",
        status="completed",
        reasoning={"effort": "medium", "summary": "auto"},
        temperature=None,
    )
    response._request_id = "provider-request-test"

    async def fake_fetch(self, *args, **kwargs):
        return response

    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setattr(OpenAIResponsesModel, "_fetch_response", fake_fetch)
    recorder = Recorder(tmp_path)
    try:
        model = OpenAIHarness(RolloutConfig(), None, recorder).recording_model(0)
        assert await model._fetch_response() is response
        event = json.loads((tmp_path / "events.jsonl").read_text())
        assert event["metadata"]["model"] == "provider-model-version"
        assert event["metadata"]["reasoning"]["effort"] == "medium"
        assert event["request_id"] == "provider-request-test"
        assert event["response_id"] == "response-test"
        assert "fake-test-key" not in json.dumps(event)
    finally:
        recorder.close()


async def test_tool_selection_is_enforced_in_adapter_and_dispatch(tmp_path):
    config = RolloutConfig(agents=1, tools=["submit"])
    recorder = Recorder(tmp_path)
    environment = Publisher(config)
    task = OptimizationTask(config, environment, recorder)
    service = ToolService(task, environment, recorder, 1)
    try:
        assert [tool.name for tool in sdk_tools(service, 0)] == ["submit"]
        result = await service.call(0, "experiment", parameters=[0.5] * 8)
        assert "error" in result
        assert task.report(0)["experiments_used"] == 0
    finally:
        recorder.close()


async def test_wait_allows_other_agents_and_is_cancelled_by_session_timeout(tmp_path, monkeypatch):
    config = RolloutConfig(agents=2)
    recorder = Recorder(tmp_path)
    environment = Publisher(config)
    task = OptimizationTask(config, environment, recorder)
    service = ToolService(task, environment, recorder, 2)

    started = asyncio.Event()
    original_emit = recorder.emit

    def emit(kind, *args, **kwargs):
        original_emit(kind, *args, **kwargs)
        if kind == "tool_called" and kwargs.get("tool") == "wait" and args == (0,):
            started.set()

    monkeypatch.setattr(recorder, "emit", emit)

    async def waiting_session():
        async with asyncio.timeout(0.05):
            await service.call(0, "wait", seconds=60)

    try:
        assert "wait" in [tool.name for tool in sdk_tools(service, 0)]
        waiting = asyncio.create_task(waiting_session())
        await asyncio.wait_for(started.wait(), timeout=1)
        other = await service.call(1, "wait", seconds=0)
        assert other["requested_seconds"] == 0
        assert other["actual_seconds"] >= 0
        assert not waiting.done()
        with pytest.raises(TimeoutError):
            await waiting
        assert task.report(0)["experiments_used"] == 0
        assert task.report(1)["experiments_used"] == 0
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        assert any(e["kind"] == "tool_cancelled" and e["agent"] == 0 for e in events)
    finally:
        recorder.close()


@pytest.mark.parametrize("seconds", [-1, 61, "10", True])
async def test_wait_rejects_invalid_duration(tmp_path, seconds):
    config = RolloutConfig(agents=1)
    recorder = Recorder(tmp_path)
    environment = Publisher(config)
    task = OptimizationTask(config, environment, recorder)
    service = ToolService(task, environment, recorder, 1)
    try:
        assert "error" in await service.call(0, "wait", seconds=seconds)
    finally:
        recorder.close()


class TextEndingModel(FakeModel):
    def __init__(self, endings):
        super().__init__()
        self.endings = endings
        self.inputs = []

    async def get_response(self, *args, **kwargs):
        from openai.types.responses import ResponseOutputMessage

        self.calls += 1
        self.inputs.append(kwargs["input"])
        if self.endings[self.calls - 1] == "text":
            output = [
                ResponseOutputMessage(
                    id=f"msg-{self.calls}",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        {
                            "type": "output_text",
                            "text": "Next I will use a tool.",
                            "annotations": [],
                            "logprobs": [],
                        }
                    ],
                )
            ]
        else:
            output = [
                ResponseFunctionToolCall(
                    id=f"fc-{self.calls}",
                    call_id=f"call-{self.calls}",
                    type="function_call",
                    name=self.endings[self.calls - 1],
                    arguments=json.dumps({"parameters": [0.5] * 8}),
                )
            ]
        return ModelResponse(
            output=output,
            usage=Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15),
            response_id=f"response-{self.calls}",
        )


@pytest.mark.parametrize(
    "endings,enabled,max_turns,reason,calls,reminders",
    [
        (["experiment", "text", "submit"], True, 3, "submitted", 3, 1),
        (["text", "text"], True, 3, "final_answer_without_submission", 2, 1),
        (["text"], False, 3, "final_answer_without_submission", 1, 0),
        (["text"], True, 1, "final_answer_without_submission", 1, 0),
    ],
)
async def test_text_final_continuation_is_bounded_and_preserves_history(
    tmp_path, endings, enabled, max_turns, reason, calls, reminders
):
    cfg = RolloutConfig(
        agents=1,
        experiment_budget=1,
        max_turns=max_turns,
        harness={"continue_after_text_final": enabled},
    )
    recorder = Recorder(tmp_path)
    environment = Publisher(cfg)
    task = OptimizationTask(cfg, environment, recorder)
    service = ToolService(task, environment, recorder, 1)
    model = TextEndingModel(endings)
    try:
        result = await OpenAIHarness(cfg, service, recorder, model=model).run(
            0, task.instructions(1)
        )
        assert result["reason"] == reason
        assert result["usage"]["requests"] == calls
        assert result["usage"]["total_tokens"] == calls * 15
        assert result["text_final_continuations_used"] == reminders
        assert model.calls == calls
        if endings[0] == "experiment":
            assert task.report(0)["experiments_used"] == 1
            assert any(i.get("type") == "function_call_output" for i in model.inputs[-1])
            assert any(i.get("type") == "message" for i in model.inputs[-1])
            assert model.inputs[-1][-1]["content"].endswith("submit(parameters).")
            assert result["initial_termination_reason"] == "final_answer_without_submission"
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        assert sum(e["kind"] == "text_final_continuation" for e in events) == reminders
    finally:
        recorder.close()


async def test_continuation_cannot_reset_turn_allowance(tmp_path):
    from agents import MaxTurnsExceeded

    cfg = RolloutConfig(
        agents=1, experiment_budget=1, max_turns=2, harness={"continue_after_text_final": True}
    )
    recorder = Recorder(tmp_path)
    environment = Publisher(cfg)
    task = OptimizationTask(cfg, environment, recorder)
    service = ToolService(task, environment, recorder, 1)
    model = TextEndingModel(["text", "experiment", "submit"])
    try:
        with pytest.raises(MaxTurnsExceeded):
            await OpenAIHarness(cfg, service, recorder, model=model).run(0, task.instructions(1))
        assert model.calls == 2
        assert task.report(0)["experiments_used"] == 1
        assert 0 not in task.submissions
    finally:
        recorder.close()


async def test_continuation_does_not_replenish_experiment_budget(tmp_path):
    cfg = RolloutConfig(
        agents=1, experiment_budget=1, max_turns=4, harness={"continue_after_text_final": True}
    )
    recorder = Recorder(tmp_path)
    environment = Publisher(cfg)
    task = OptimizationTask(cfg, environment, recorder)
    service = ToolService(task, environment, recorder, 1)
    model = TextEndingModel(["experiment", "text", "experiment", "submit"])
    try:
        result = await OpenAIHarness(cfg, service, recorder, model=model).run(
            0, task.instructions(1)
        )
        assert result["reason"] == "submitted"
        assert task.report(0)["experiments_used"] == 1
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        attempts = [e for e in events if e["kind"] == "tool_result" and e["tool"] == "experiment"]
        assert "budget exhausted" in attempts[-1]["result"]["error"]
    finally:
        recorder.close()


async def test_continuation_keeps_enclosing_deadline(tmp_path):
    class SlowSecondTurn(TextEndingModel):
        async def get_response(self, *args, **kwargs):
            if self.calls == 1:
                await asyncio.sleep(10)
            return await super().get_response(*args, **kwargs)

    cfg = RolloutConfig(agents=1, harness={"continue_after_text_final": True})
    recorder = Recorder(tmp_path)
    environment = Publisher(cfg)
    task = OptimizationTask(cfg, environment, recorder)
    service = ToolService(task, environment, recorder, 1)
    model = SlowSecondTurn(["text", "submit"])
    try:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await OpenAIHarness(cfg, service, recorder, model=model).run(
                    0, task.instructions(1)
                )
        assert 0 not in task.submissions
    finally:
        recorder.close()

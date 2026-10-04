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
        assert all(
            e["output"][0]["summary"][0]["text"] == "Choosing the next tool."
            for e in events
            if e["kind"] == "model_response"
        )
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


async def test_wait_allows_other_agents_and_is_cancelled_by_session_timeout(tmp_path):
    config = RolloutConfig(agents=2)
    recorder = Recorder(tmp_path)
    environment = Publisher(config)
    task = OptimizationTask(config, environment, recorder)
    service = ToolService(task, environment, recorder, 2)

    async def waiting_session():
        async with asyncio.timeout(0.05):
            await service.call(0, "wait", seconds=60)

    try:
        assert "wait" in [tool.name for tool in sdk_tools(service, 0)]
        waiting = asyncio.create_task(waiting_session())
        await asyncio.sleep(0)
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

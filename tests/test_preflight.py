import json

from agents import Model
from agents.items import ModelResponse
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall

from mad.config import RolloutConfig
from mad.preflight import preflight_model


class ProbeModel(Model):
    def __init__(self):
        self.calls = 0

    async def get_response(self, *args, **kwargs):
        self.calls += 1
        name = "read_file" if self.calls == 1 else "submit"
        arguments = {"path": "/workspace/task.md"} if self.calls == 1 else {"parameters": [0.5] * 8}
        return ModelResponse(
            output=[
                ResponseFunctionToolCall(
                    id=f"fc-{self.calls}",
                    call_id=f"call-{self.calls}",
                    type="function_call",
                    name=name,
                    arguments=json.dumps(arguments),
                )
            ],
            usage=Usage(requests=1),
            response_id=f"response-{self.calls}",
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


async def test_preflight_uses_actual_tools_without_experiments_or_mutating_config(tmp_path):
    cfg = RolloutConfig(
        agents=10,
        experiment_budget=10,
        start_stagger_seconds=1,
        harness={"continue_after_text_final": True},
    )
    original = cfg.model_dump()
    report = await preflight_model(cfg, tmp_path / "probe", model=ProbeModel())
    assert report["status"] == "passed"
    assert report["tool_sequence"] == ["read_file", "submit"]
    assert cfg.model_dump() == original
    events = [
        json.loads(line) for line in (tmp_path / "probe" / "events.jsonl").read_text().splitlines()
    ]
    assert not any(e["kind"] in {"experiment_started", "experiment_completed"} for e in events)
    interface = next(e for e in events if e["kind"] == "agent_interface")
    assert [t["name"] for t in interface["tools"]] == cfg.tools


async def test_preflight_rejects_submission_without_tool_result_followup(tmp_path):
    class BothAtOnce(ProbeModel):
        async def get_response(self, *args, **kwargs):
            first = await super().get_response(*args, **kwargs)
            second = await super().get_response(*args, **kwargs)
            first.output.extend(second.output)
            return first

    report = await preflight_model(RolloutConfig(), tmp_path / "probe", model=BothAtOnce())
    assert report["status"] == "failed"
    assert report["model_turns"] == 1

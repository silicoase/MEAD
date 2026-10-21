"""Independent harnesses; no cross-agent handoffs or messaging capabilities."""

import asyncio
import json
import os
import random
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from typing import Protocol

from .config import RolloutConfig
from .pause import new_account_reset_delay


class Harness(Protocol):
    async def run(self, agent: int, instructions: str) -> dict: ...


def sdk_tools(service, agent: int):
    from agents import function_tool

    @function_tool
    async def experiment(parameters: list[float]) -> dict:
        """Measure the objective at a configuration; consumes one experiment."""
        return await service.call(agent, "experiment", parameters=parameters)

    @function_tool
    async def submit(parameters: list[float]) -> dict:
        """Submit a valid final configuration and end the session without a measurement."""
        return await service.call(agent, "submit", parameters=parameters)

    @function_tool
    async def list_files(path: str) -> object:
        """List a workspace or lab directory."""
        return await service.call(agent, "list_files", path=path)

    @function_tool
    async def read_file(path: str) -> object:
        """Read a UTF-8 workspace or lab file, up to 65536 characters."""
        return await service.call(agent, "read_file", path=path)

    @function_tool
    async def write_file(path: str, content: str) -> object:
        """Create or revise a private file or a research note you created.

        Published notes use flat filenames immediately within /lab/notes.
        """
        return await service.call(agent, "write_file", path=path, content=content)

    @function_tool
    async def append_file(path: str, content: str) -> object:
        """Append text to a private file or a research note you created.

        Creates the file if missing. Adds content exactly, without extra newlines.
        Published notes use flat filenames within /lab/notes; maximum 65536 characters.
        """
        return await service.call(agent, "append_file", path=path, content=content)

    @function_tool
    async def search_files(path: str, query: str) -> object:
        """Search UTF-8 files for literal text under a workspace or lab directory."""
        return await service.call(agent, "search_files", path=path, query=query)

    @function_tool(name_override="python")
    async def execute_python(code: str) -> dict:
        """Execute Python with numpy, scipy, and pandas in /workspace.

        Use print(...) to return values in stdout; bare expressions are not displayed.
        Each call uses a fresh interpreter. Workspace files persist. Published lab
        artifacts are read-only here; use write_file or append_file to maintain notes.
        """
        return await service.call(agent, "python", code=code)

    @function_tool
    async def wait(seconds: float) -> dict:
        """Pause for the specified number of seconds before continuing (0–60 seconds)."""
        return await service.call(agent, "wait", seconds=seconds)

    return [
        tool
        for tool in [
            experiment,
            submit,
            list_files,
            read_file,
            write_file,
            append_file,
            search_files,
            execute_python,
            wait,
        ]
        if tool.name in service.environment.config.tools
    ]


class OpenAIHarness:
    def __init__(self, config: RolloutConfig, service, recorder, model=None):
        self.config, self.service, self.recorder, self.model = config, service, recorder, model

    def recording_model(self, agent: int):
        from agents.models.openai_provider import OpenAIProvider
        from agents.models.openai_responses import OpenAIResponsesModel

        recorder = self.recorder

        class RecordingResponsesModel(OpenAIResponsesModel):
            async def _fetch_response(self, *args, **kwargs):
                # The pinned SDK discards these fields when converting to ModelResponse.
                response = await super()._fetch_response(*args, **kwargs)
                if getattr(response, "id", None):
                    recorder.emit(
                        "provider_response_metadata",
                        agent,
                        response_id=response.id,
                        request_id=getattr(response, "_request_id", None),
                        metadata=response.model_dump(
                            mode="json",
                            include={
                                "model",
                                "reasoning",
                                "temperature",
                                "top_p",
                                "max_output_tokens",
                                "parallel_tool_calls",
                                "truncation",
                                "service_tier",
                                "text",
                                "tool_choice",
                                "status",
                                "created_at",
                            },
                        ),
                    )
                return response

        client = OpenAIProvider()._get_client()
        return RecordingResponsesModel(self.config.harness.model, client)

    def model_name(self, agent: int) -> str:
        return self.config.harness.model

    def model_settings(self, agent: int):
        from agents import ModelSettings
        from openai.types.shared import Reasoning

        return ModelSettings(
            parallel_tool_calls=False,
            max_tokens=self.config.harness.max_tokens,
            reasoning=Reasoning(summary=self.config.harness.reasoning_summary)
            if self.config.harness.reasoning_summary
            else None,
        )

    async def close(self):
        pass

    async def run(self, agent: int, instructions: str) -> dict:
        from agents import Agent, RunConfig, Runner
        from agents.agent import ToolsToFinalOutputResult
        from agents.lifecycle import RunHooksBase
        from agents.usage import Usage

        recorder = self.recorder
        model_name = self.model_name(agent)
        turns_used = 0

        class Hooks(RunHooksBase):
            async def on_llm_start(self, context, sdk_agent, system_prompt, input_items):
                nonlocal turns_used
                turns_used += 1
                recorder.emit(
                    "model_request",
                    agent,
                    model=model_name,
                    system_prompt=system_prompt,
                    input_items=input_items,
                    model_settings=sdk_agent.model_settings.to_json_dict(),
                )

            async def on_llm_end(self, context, sdk_agent, response):
                recorder.emit(
                    "model_response",
                    agent,
                    output=[item.model_dump(mode="json") for item in response.output],
                    usage=asdict(response.usage),
                    response_id=response.response_id,
                    raw_usage=getattr(response, "raw_usage", None),
                    request_id=getattr(response, "request_id", None),
                )

        async def finish_on_submission(context, results):
            submitted = agent in self.service.closed
            return ToolsToFinalOutputResult(
                is_final_output=submitted, final_output={"submitted": True} if submitted else None
            )

        tools = sdk_tools(self.service, agent)
        recorder.emit(
            "agent_interface",
            agent,
            instructions=instructions,
            tools=[
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.params_json_schema,
                }
                for tool in tools
            ],
            model=self.model_name(agent),
            reasoning_summary=self.config.harness.reasoning_summary,
        )
        model = self.model if self.model is not None else self.recording_model(agent)
        sdk_agent = Agent(
            name="Researcher",
            instructions=instructions,
            model=model,
            tools=tools,
            model_settings=self.model_settings(agent),
            tool_use_behavior=finish_on_submission,
        )
        inputs = "Begin the task described in /workspace/task.md."
        usage = Usage()
        continuations = 0
        initial_termination_reason = None
        reminder = (
            "Your session has not submitted a final configuration. "
            "Continue using the available tools, and finish by calling submit(parameters)."
        )
        while True:
            result = await Runner.run(
                sdk_agent,
                inputs,
                max_turns=self.config.max_turns - turns_used,
                hooks=Hooks(),
                run_config=RunConfig(tracing_disabled=True),
            )
            usage.add(result.context_wrapper.usage)
            if agent in self.service.closed:
                reason = "submitted"
                break
            reason = "final_answer_without_submission"
            if (
                not self.config.harness.continue_after_text_final
                or continuations == 1
                or turns_used >= self.config.max_turns
            ):
                break
            initial_termination_reason = reason
            continuations = 1
            recorder.emit(
                "text_final_continuation",
                agent,
                original_reason=reason,
                original_final_output=result.final_output,
                reminder=reminder,
                turns_used=turns_used,
                turns_remaining=self.config.max_turns - turns_used,
            )
            # Reuse the entire history and the same tool service/budget. The rollout's
            # enclosing timeout remains active; Runner gets only the remaining turns.
            inputs = result.to_input_list() + [{"role": "user", "content": reminder}]
        return dict(
            reason=reason,
            final_output=result.final_output,
            usage=asdict(usage),
            text_final_continuations_used=continuations,
            initial_termination_reason=initial_termination_reason,
        )


class EmptyTruncatedResponseError(RuntimeError):
    """A costed, token-limited response with no usable assistant output."""

    error_kind = "empty_truncated_response"


class TransientProviderResponseError(RuntimeError):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class ReasoningReplayClient:
    """Restore OpenRouter reasoning fields lost by the SDK's item conversion.

    One wrapper per agent/model keeps each session's signed reasoning isolated.
    Only replay fields on the assistant tool-call turn that originally produced them.
    """

    def __init__(self, client):
        self.client = client
        self.reasoning_by_calls = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def create(self, **kwargs):
        messages = deepcopy(kwargs["messages"])
        for message in messages:
            if message.get("role") != "assistant":
                continue
            calls = tuple(call["id"] for call in message.get("tool_calls", []))
            if calls in self.reasoning_by_calls:
                # Exact structured details include encrypted/signature blocks; don't flatten them.
                for field in ("reasoning", "reasoning_content", "reasoning_details"):
                    message.pop(field, None)
                message.update(deepcopy(self.reasoning_by_calls[calls]))
        kwargs["messages"] = messages
        response = await self.client.chat.completions.create(**kwargs)
        if response.choices:
            message = response.choices[0].message
            calls = tuple(call.id for call in message.tool_calls or [])
            if calls:
                self.reasoning_by_calls[calls] = {
                    field: deepcopy(getattr(message, field))
                    for field in ("reasoning", "reasoning_content", "reasoning_details")
                    if getattr(message, field, None) is not None
                }
        return response


class OpenRouterHarness(OpenAIHarness):
    """Fixed model/host routes through OpenRouter's Chat Completions API."""

    def __init__(self, config, service, recorder, model=None, client=None):
        super().__init__(config, service, recorder, model)
        self.client = client
        self.owns_client = client is None
        self.request_slots = asyncio.Semaphore(config.harness.request_concurrency or config.agents)

    def route(self, agent):
        routes = self.config.harness.routes
        return routes[0] if len(routes) == 1 else routes[agent]

    def model_name(self, agent):
        return self.route(agent).model

    def model_settings(self, agent):
        from agents import ModelSettings

        provider = {
            "allow_fallbacks": self.route(agent).provider is None,
            "require_parameters": True,
        }
        if self.route(agent).provider is not None:
            provider["only"] = [self.route(agent).provider]
        return ModelSettings(
            max_tokens=self.config.harness.max_tokens,
            preserve_raw_usage=True,
            extra_body={
                "provider": provider,
            },
        )

    @asynccontextmanager
    async def request_admission(self):
        if self.recorder.pause:
            async with self.recorder.pause.operation():
                yield
        else:
            yield

    def recording_model(self, agent):
        from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
        from openai import APIConnectionError, AsyncOpenAI

        if self.client is None:
            self.client = AsyncOpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url="https://openrouter.ai/api/v1",
                max_retries=0,
            )
        recorder, route = self.recorder, self.route(agent)
        settings, slots = self.config.harness, self.request_slots
        self_harness = self

        class RecordingChatModel(OpenAIChatCompletionsModel):
            response_id = None

            async def _fetch_response(self, *args, **kwargs):
                started = time.monotonic()
                attempt = 0
                ordinary_failures = 0
                while True:
                    attempt += 1
                    coordinated = False
                    async with slots, self_harness.request_admission():
                        attempt_started = time.monotonic()
                        recorder.emit(
                            "provider_request_started",
                            agent,
                            route=route.model_dump(),
                            attempt=attempt,
                        )
                        try:
                            response = await super()._fetch_response(*args, **kwargs)
                            error_payload = getattr(response, "error", None)
                            if not response.choices and isinstance(error_payload, dict):
                                code = error_payload.get("code")
                                message = str(error_payload.get("message", ""))
                                if code in {429, 500, 502, 503, 504} or (
                                    code == 400 and "unexpected end of data" in message.lower()
                                ):
                                    recorder.emit(
                                        "provider_response_invalid",
                                        agent,
                                        route=route.model_dump(),
                                        attempt=attempt,
                                        response_id=response.id,
                                        metadata=response.model_dump(mode="json"),
                                    )
                                    failure = TransientProviderResponseError(message, code)
                                    failure.body = error_payload
                                    raise failure
                            break
                        except Exception as error:
                            status = getattr(error, "status_code", None)
                            delay = new_account_reset_delay(error) if recorder.pause else None
                            coordinated = delay is not None
                            if coordinated:
                                recorder.pause.request(delay, model=route.model, agent=agent,
                                                       source_run=recorder.directory.name)
                            else:
                                ordinary_failures += 1
                            will_retry = coordinated or (
                                status in {429, 500, 502, 503, 504}
                                or isinstance(
                                    error, (APIConnectionError, TransientProviderResponseError)
                                )
                            ) and ordinary_failures <= settings.request_retries
                            recorder.emit(
                                "provider_request_failed",
                                agent,
                                route=route.model_dump(),
                                attempt=attempt,
                                will_retry=will_retry,
                                latency_seconds=time.monotonic() - attempt_started,
                                error_type=type(error).__name__,
                                status_code=status,
                                coordinated_pause=coordinated,
                            )
                            if not will_retry:
                                raise
                    if coordinated:
                        await recorder.pause.wait_open()
                        continue
                    delay = min(60, settings.retry_backoff_seconds * 2 ** (ordinary_failures - 1))
                    delay *= random.uniform(0.8, 1.2)
                    recorder.emit(
                        "provider_request_retry",
                        agent,
                        route=route.model_dump(),
                        next_attempt=attempt + 1,
                        backoff_seconds=delay,
                    )
                    if recorder.pause:
                        await recorder.pause.sleep(delay)
                    else:
                        await asyncio.sleep(delay)
                self.response_id = response.id
                recorder.emit(
                    "provider_response_metadata",
                    agent,
                    response_id=response.id,
                    request_id=getattr(response, "_request_id", None),
                    route=route.model_dump(),
                    actual_provider=getattr(response, "provider", None),
                    actual_model=response.model,
                    attempt=attempt,
                    latency_seconds=time.monotonic() - started,
                    metadata=response.model_dump(mode="json"),
                )
                if recorder.pause:
                    await recorder.pause.wait_open()
                if response.choices:
                    choice = response.choices[0]
                    message = choice.message
                    if (choice.finish_reason == "length" and not message.content
                            and not message.tool_calls and not message.refusal):
                        recorder.emit("empty_truncated_response", agent,
                                      response_id=response.id, max_tokens=settings.max_tokens)
                        raise EmptyTruncatedResponseError(
                            "Token limit reached with no assistant text, tool call, or refusal."
                        )
                return response

            async def get_response(self, *args, **kwargs):
                result = await super().get_response(*args, **kwargs)
                # Chat adapter normally discards the generation ID; retain it for audit.
                result.response_id = self.response_id
                return result

        return RecordingChatModel(route.model, ReasoningReplayClient(self.client))

    async def close(self):
        if self.owns_client and self.client is not None:
            await self.client.close()


class ScriptedHarness:
    """Deterministic plumbing exercise, never evidence of emergent discovery."""

    def __init__(self, config: RolloutConfig, service, recorder):
        self.config, self.service, self.recorder = config, service, recorder

    async def run(self, agent: int, instructions: str) -> dict:
        rng = random.Random(f"smoke:{agent}")
        count = 0

        async def call(name, **kwargs):
            nonlocal count
            if count >= self.config.max_turns:
                raise ScriptedTurnLimit("scripted action limit reached")
            count += 1
            return await self.service.call(agent, name, **kwargs)

        await call("read_file", path="/workspace/task.md")
        await call("python", code="import numpy as np; print(np.arange(3).sum())")
        best = None
        for _ in range(self.config.experiment_budget):
            parameters = [
                rng.uniform(self.config.task.lower, self.config.task.upper)
                for _ in range(self.config.task.dimensions)
            ]
            result = await call("experiment", parameters=parameters)
            if "observed" in result and (best is None or result["observed"] > best["observed"]):
                best = result
        notes = await call("list_files", path="/lab/notes")
        if isinstance(notes, list):
            for note in notes[:1]:
                await call("read_file", path="/lab/notes/" + note["name"])
        runs = await call("list_files", path="/lab/runs")
        if isinstance(runs, list):
            for entry in runs:
                data = await call("read_file", path="/lab/runs/" + entry["name"])
                if isinstance(data, str):
                    record = json.loads(data)
                    if best is None or record["observed"] > best["observed"]:
                        best = record
        await call(
            "write_file",
            path=f"/lab/notes/sweep-{self.service.environment.author_ids[agent]}.md",
            content="Smoke-test observation: " + json.dumps(best),
        )
        parameters = (
            best["parameters"] if best else [self.config.task.lower] * self.config.task.dimensions
        )
        await call("submit", parameters=parameters)
        return dict(reason="submitted", scripted_actions=count)


class ScriptedTurnLimit(RuntimeError):
    pass

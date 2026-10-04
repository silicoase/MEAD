"""Independent harnesses; no cross-agent handoffs or messaging capabilities."""

import json
import random
from dataclasses import asdict
from typing import Protocol

from .config import RolloutConfig


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

    async def run(self, agent: int, instructions: str) -> dict:
        from agents import Agent, ModelSettings, RunConfig, Runner
        from agents.agent import ToolsToFinalOutputResult
        from agents.lifecycle import RunHooksBase
        from openai.types.shared import Reasoning

        recorder = self.recorder

        class Hooks(RunHooksBase):
            async def on_llm_start(self, context, sdk_agent, system_prompt, input_items):
                recorder.emit(
                    "model_request", agent, system_prompt=system_prompt, input_items=input_items
                )

            async def on_llm_end(self, context, sdk_agent, response):
                recorder.emit(
                    "model_response",
                    agent,
                    output=[item.model_dump(mode="json") for item in response.output],
                    usage=asdict(response.usage),
                    response_id=response.response_id,
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
            model=str(self.model or self.config.harness.model),
            reasoning_summary=self.config.harness.reasoning_summary,
        )
        sdk_agent = Agent(
            name="Researcher",
            instructions=instructions,
            model=self.model or self.config.harness.model,
            tools=tools,
            model_settings=ModelSettings(
                parallel_tool_calls=False,
                reasoning=Reasoning(summary=self.config.harness.reasoning_summary)
                if self.config.harness.reasoning_summary
                else None,
            ),
            tool_use_behavior=finish_on_submission,
        )
        result = await Runner.run(
            sdk_agent,
            "Begin the task described in /workspace/task.md.",
            max_turns=self.config.max_turns,
            hooks=Hooks(),
            run_config=RunConfig(tracing_disabled=True),
        )
        return dict(
            reason="submitted"
            if agent in self.service.closed
            else "final_answer_without_submission",
            final_output=result.final_output,
            usage=asdict(result.context_wrapper.usage),
        )


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

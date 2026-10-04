import asyncio
import os
import platform
import sys
from importlib.metadata import version
from pathlib import Path

from .config import RolloutConfig
from .environment import DockerEnvironment, docker
from .harness import OpenAIHarness, ScriptedHarness, ScriptedTurnLimit
from .recording import Recorder, write_json
from .task import OptimizationTask
from .tools import ToolService


async def run_rollout(config: RolloutConfig, output: Path) -> dict:
    if config.harness.kind == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError(
            "OPENAI_API_KEY is required for the openai harness; scripted mode needs no key"
        )
    extra_instructions = (
        config.task.instructions_file.read_text() if config.task.instructions_file else ""
    )
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "config.json", config.model_dump(mode="json"))
    recorder = Recorder(output)
    environment = DockerEnvironment(config)
    task = OptimizationTask(config, environment, recorder)
    service = ToolService(task, environment, recorder, config.agents)
    harness = (OpenAIHarness if config.harness.kind == "openai" else ScriptedHarness)(
        config, service, recorder
    )
    instructions = task.instructions(config.experiment_budget)
    if extra_instructions:
        instructions += "\n\n" + extra_instructions
    agent_instructions = [
        environment.agent_instructions(instructions, i) for i in range(config.agents)
    ]
    write_json(
        output / "identities.json",
        [
            dict(agent=i, author_id=author_id, docker_uid=10000 + i)
            for i, author_id in enumerate(environment.author_ids)
        ],
    )
    summary = {"harness": config.harness.kind, "agents": []}
    started = False
    reports = {}

    async def run_agent(agent: int):
        await asyncio.sleep(config.start_offsets_seconds[agent])
        recorder.emit(
            "agent_started",
            agent,
            instructions=agent_instructions[agent],
            author_id=environment.author_ids[agent],
        )
        result = {}
        try:
            async with asyncio.timeout(config.timeout_seconds):
                result = await harness.run(agent, agent_instructions[agent])
        except TimeoutError:
            result = {"reason": "time_limit"}
        except ScriptedTurnLimit:
            result = {"reason": "turn_limit"}
        except asyncio.CancelledError:
            result = {"reason": "cancelled"}
            raise
        except Exception as error:
            from agents import MaxTurnsExceeded

            result = {
                "reason": "turn_limit" if isinstance(error, MaxTurnsExceeded) else "error",
                "error": str(error),
            }
        finally:
            # Kill remaining Python processes before archiving, including escaped descendants.
            await environment.stop_agent(agent)
            report = dict(
                agent=agent,
                author_id=environment.author_ids[agent],
                **result,
                **task.report(agent),
                **service.report(agent),
            )
            reports[agent] = report
            recorder.emit("agent_finished", agent, report=report)
        return report

    try:
        await environment.start(agent_instructions)
        started = True
        image = await docker("image", "inspect", "--format", "{{.Id}}", config.environment.image)
        write_json(
            output / "runtime.json",
            dict(
                python=sys.version,
                platform=platform.platform(),
                sdk_version=version("openai-agents"),
                image_id=image.decode().strip(),
            ),
        )
        recorder.emit("rollout_started", config=config.model_dump(mode="json"))
        async with asyncio.TaskGroup() as group:
            jobs = [group.create_task(run_agent(i)) for i in range(config.agents)]
        summary["agents"] = [job.result() for job in jobs]
    except BaseException as error:
        recorder.emit("rollout_failed", error=str(error), error_type=type(error).__name__)
        raise
    finally:
        try:
            if started:
                # Stop all containers before final snapshot even on interruption.
                for i in environment.containers:
                    await environment.stop_agent(i)
                await environment.snapshot(output)
                summary["agents"] = [reports[i] for i in sorted(reports)]
                summary["experiment_records"] = task.records
                summary["submissions"] = task.submissions
                write_json(output / "summary.json", summary)
        finally:
            try:
                await environment.close()
            finally:
                recorder.close()
    return summary

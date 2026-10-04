import asyncio
import math

from .recording import Recorder
from .task import Task


class ToolService:
    def __init__(self, task: Task, environment, recorder: Recorder, agents: int):
        self.task, self.environment, self.recorder = task, environment, recorder
        self.locks = [asyncio.Lock() for _ in range(agents)]
        self.closed: set[int] = set()
        self.accesses: list[list[dict]] = [[] for _ in range(agents)]

    async def call(self, agent: int, name: str, **arguments):
        async with self.locks[agent]:
            self.recorder.emit("tool_called", agent, tool=name, arguments=arguments)
            try:
                if agent in self.closed:
                    raise ValueError("session already submitted")
                if name not in self.environment.config.tools:
                    raise ValueError("tool is not available in this rollout")
                if name == "experiment":
                    result = await self.task.experiment(agent, arguments["parameters"])
                elif name == "submit":
                    result = self.task.submit(agent, arguments["parameters"])
                    self.closed.add(agent)
                elif name == "python":
                    result = await self.environment.python(agent, arguments["code"])
                elif name == "wait":
                    seconds = arguments["seconds"]
                    if (
                        isinstance(seconds, bool)
                        or not isinstance(seconds, (int, float))
                        or not math.isfinite(seconds)
                        or not 0 <= seconds <= 60
                    ):
                        raise ValueError("seconds must be a finite number between 0 and 60")
                    started = asyncio.get_running_loop().time()
                    await asyncio.sleep(seconds)
                    result = {
                        "requested_seconds": seconds,
                        "actual_seconds": asyncio.get_running_loop().time() - started,
                    }
                elif name in (
                    "list_files",
                    "read_file",
                    "write_file",
                    "append_file",
                    "search_files",
                ):
                    operation = dict(
                        list_files="list",
                        read_file="read",
                        write_file="write",
                        append_file="append",
                        search_files="search",
                    )[name]
                    result = await self.environment.file(agent, operation, **arguments)
                    self.accesses[agent].append(dict(operation=operation, **arguments))
                else:
                    raise ValueError("unknown tool")
            except (ValueError, OSError, RuntimeError) as error:
                result = {"error": str(error)}
            except asyncio.CancelledError:
                self.recorder.emit("tool_cancelled", agent, tool=name)
                raise
            self.recorder.emit("tool_result", agent, tool=name, result=result)
            return result

    def report(self, agent: int):
        return {"file_tool_accesses": self.accesses[agent]}

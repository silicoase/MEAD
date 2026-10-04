import asyncio
import math
import random
import uuid
from typing import Protocol

from .config import RolloutConfig, TaskConfig
from .recording import Recorder, timestamp


class Task(Protocol):
    def instructions(self, budget: int) -> str: ...
    async def experiment(self, agent: int, parameters: list[float]) -> dict: ...
    def submit(self, agent: int, parameters: list[float]) -> dict: ...
    def report(self, agent: int) -> dict: ...


class SyntheticObjective:
    def __init__(self, config: TaskConfig):
        self.config = config
        rng = random.Random(config.objective_seed)
        self.center = [rng.uniform(0.15, 0.85) for _ in range(config.dimensions)]
        self.phase = [rng.uniform(0, math.tau) for _ in range(config.dimensions)]

    def validate(self, parameters: list[float]) -> list[float]:
        if len(parameters) != self.config.dimensions:
            raise ValueError(f"expected {self.config.dimensions} parameters")
        if any(
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(x)
            or not self.config.lower <= x <= self.config.upper
            for x in parameters
        ):
            raise ValueError(
                f"parameters must be finite numbers in [{self.config.lower}, {self.config.upper}]"
            )
        return [float(x) for x in parameters]

    def evaluate(self, parameters: list[float]) -> float:
        x = [
            (v - self.config.lower) / (self.config.upper - self.config.lower)
            for v in self.validate(parameters)
        ]
        # Three strong variables, weak variables, and a final irrelevant variable.
        value = 0.0
        for i, v in enumerate(x[:-1]):
            weight = 1.0 if i < 3 else 0.05
            value += weight * (
                -((v - self.center[i]) ** 2) + 0.15 * math.cos(6 * math.pi * v + self.phase[i])
            )
        value += 0.25 * math.sin(math.tau * x[0] * x[1])
        value -= 0.3 * (x[1] - x[2]) ** 2
        return value


class OptimizationTask:
    def __init__(self, config: RolloutConfig, environment, recorder: Recorder):
        self.config, self.environment, self.recorder = config, environment, recorder
        self.objective = SyntheticObjective(config.task)
        self.records: list[list[dict]] = [[] for _ in range(config.agents)]
        self.submissions: dict[int, list[float]] = {}
        self.locks = [asyncio.Lock() for _ in range(config.agents)]
        self.random = [random.Random(f"{config.task.noise_seed}:{i}") for i in range(config.agents)]

    def instructions(self, budget: int) -> str:
        task = self.config.task
        return (
            f"Maximize the unknown objective using {task.dimensions} numeric parameters, "
            f"each in [{task.lower}, {task.upper}]. Observations contain independent noise. "
            f"You may run at most {budget} experiments. Repeated configurations use budget. "
            "The experiment budget applies only to calls to `experiment`. "
            "You can use your other tools to inform your calls to `experiment`. "
            "Use experiment(parameters) for measurements. Your working directory is "
            "/workspace. Lab notes and experiments are logged in `/lab/notes` and "
            "`/lab/runs`, respectively. You may read files, create files, and revise "
            "files you created. "
            "Use Python for computation and file tools to inspect and maintain artifacts. "
            "After the experiment budget is exhausted you may continue analysis and writing. "
            "Finish by calling submit(parameters) with your chosen configuration; it need "
            "not have been tested. Submission ends your session and returns no measurement."
        )

    async def experiment(self, agent: int, parameters: list[float]) -> dict:
        async with self.locks[agent]:
            if agent in self.submissions:
                raise ValueError("session already submitted")
            values = self.objective.validate(parameters)
            if len(self.records[agent]) >= self.config.experiment_budget:
                raise ValueError(
                    "experiment budget exhausted; analysis and submission remain available"
                )
            observed = self.objective.evaluate(values) + self.random[agent].gauss(
                0, self.config.task.noise_std
            )
            record = dict(
                run_id=f"measurement-{uuid.uuid4().hex}",
                author_id=self.environment.author_ids[agent],
                parameters=values,
                observed=observed,
                started_at=timestamp(),
            )
            # A valid accepted call consumes budget even if interrupted during latency.
            self.records[agent].append(record)
            self.recorder.emit("experiment_started", agent, record=record)
            await asyncio.sleep(self.config.experiment_duration_seconds)
            record["completed_at"] = timestamp()
            await self.environment.publish_run(agent, record)
            self.recorder.emit("experiment_completed", agent, record=record)
            return dict(
                record,
                experiments_remaining=self.config.experiment_budget - len(self.records[agent]),
            )

    def submit(self, agent: int, parameters: list[float]) -> dict:
        if agent in self.submissions:
            raise ValueError("session already submitted")
        values = self.objective.validate(parameters)
        self.submissions[agent] = values
        self.recorder.emit("submission", agent, parameters=values)
        return {"submitted": True}

    def report(self, agent: int) -> dict:
        records = self.records[agent]
        completed = [r for r in records if "completed_at" in r]
        parameters = self.submissions.get(agent)
        return dict(
            parameters=parameters,
            true_objective=self.objective.evaluate(parameters) if parameters is not None else None,
            experiments_used=len(records),
            experiments_completed=len(completed),
            best_observed=max((r["observed"] for r in completed), default=None),
            duplicate_experiments=len(records) - len({tuple(r["parameters"]) for r in records}),
        )

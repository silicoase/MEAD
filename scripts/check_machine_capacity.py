"""Offline 20-agent Docker load check; no model requests or scientific experiments."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from mad.config import load_config
from mad.environment import DockerEnvironment, docker
from mad.recording import write_json

CODE = """
import json, resource, time
import numpy as np
import pandas as pd
import scipy.linalg
started = time.monotonic()
rng = np.random.default_rng(1)
a = rng.normal(size=(1400, 1400))
b = a @ a.T
print(json.dumps({"compute_seconds": time.monotonic() - started,
                  "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "finite": bool(np.isfinite(b).all())}), flush=True)
time.sleep(3)
"""


def bytes_used(text):
    units = {
        "B": 1,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "kB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
    }
    value = text.split("/")[0].strip()
    for unit in sorted(units, key=len, reverse=True):
        if value.endswith(unit):
            return float(value[: -len(unit)]) * units[unit]
    raise ValueError(f"Unknown Docker memory unit: {value}")


async def check(config_path, output):
    cfg = load_config(config_path)
    if cfg.agents != 10:
        raise ValueError("This check expects ten agents per condition")
    envs = [DockerEnvironment(cfg), DockerEnvironment(cfg)]
    samples, results = [], []
    try:
        await asyncio.gather(*(env.start(["Offline capacity check"] * 10) for env in envs))
        names = [name for env in envs for name in env.containers.values()]

        async def probe(env, agent):
            started = time.monotonic()
            result = await env.python(agent, CODE)
            return {"elapsed_seconds": time.monotonic() - started, **result}

        pending = asyncio.gather(*(probe(env, agent) for env in envs for agent in range(10)))
        while not pending.done():
            raw = await docker("stats", "--no-stream", "--format", "{{json .}}", *names)
            rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
            samples.append(
                {
                    "agent_memory_bytes": sum(bytes_used(row["MemUsage"]) for row in rows),
                    "containers": rows,
                }
            )
            if not pending.done():
                await asyncio.sleep(0.5)
        results = await pending
    finally:
        await asyncio.gather(*(env.close() for env in envs))
    report = {
        "kind": "Offline capacity check; no model calls",
        "agents": 20,
        "config": cfg.model_dump(mode="json"),
        "results": results,
        "memory_samples": samples,
        "max_sampled_agent_memory_bytes": max(
            (s["agent_memory_bytes"] for s in samples), default=0
        ),
        "status": "passed"
        if all(r["exit_code"] == 0 and not r["timed_out"] for r in results)
        else "failed",
    }
    write_json(output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "agents": 20,
                "max_sampled_agent_memory_gib": report["max_sampled_agent_memory_bytes"] / 1024**3,
                "max_python_call_seconds": max(r["elapsed_seconds"] for r in results),
                "output": str(output.resolve()),
            }
        )
    )
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("experiments/cross-provider-tinkering/glm53/config.toml"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/machine-capacity.json"))
    args = parser.parse_args()
    asyncio.run(check(args.config, args.output))

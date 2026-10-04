"""Matched batches with immutable input snapshots and publication provenance."""

import asyncio
import hashlib
import html
import json
import os
import shutil
import statistics
import subprocess
import tomllib
import uuid
from datetime import datetime, timezone
from importlib.metadata import distributions
from pathlib import Path

from pydantic import Field

from .config import StrictModel, load_config
from .recording import timestamp
from .review import export_review
from .rollout import run_rollout

REPOSITORY = Path(__file__).resolve().parents[2]


class ExperimentConfig(StrictModel):
    schema_version: int = Field(default=2, ge=2, le=2)
    name: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    conditions: list[str]
    repetitions: int = Field(ge=1)
    config_file: str
    prompts: dict[str, str]
    concurrent_runs: int = Field(ge=1)
    objective_seed_start: int
    noise_seed_start: int


def validate_experiment(path: Path) -> dict:
    spec = ExperimentConfig.model_validate(tomllib.loads(path.read_text()))
    if not spec.conditions or len(set(spec.conditions)) != len(spec.conditions):
        raise ValueError("conditions must be nonempty and unique")
    if any(not c.replace("-", "").isalnum() for c in spec.conditions):
        raise ValueError("condition names must be alphanumeric with optional hyphens")
    if spec.concurrent_runs != len(spec.conditions):
        raise ValueError("concurrent_runs must equal the number of matched conditions")
    if set(spec.prompts) != set(spec.conditions):
        raise ValueError("provide exactly one prompt file for each condition")
    config_path = (path.parent / spec.config_file).resolve()
    if not config_path.is_relative_to(path.parent.resolve()):
        raise ValueError("config path must stay inside the experiment directory")
    config = load_config(config_path)
    if config.task.instructions_file:
        raise ValueError("set condition instructions in the experiment prompts mapping")
    for source in config.task.initial_files.values():
        if not source.is_file() or not source.is_relative_to(path.parent.resolve()):
            raise ValueError("initial files must be within the experiment directory")
    entries = []
    for repetition in range(1, spec.repetitions + 1):
        for condition in spec.conditions:
            prompt_path = (path.parent / spec.prompts[condition]).resolve()
            if not prompt_path.is_file() or not prompt_path.is_relative_to(path.parent.resolve()):
                raise ValueError("prompt files must be within the experiment directory")
            entries.append(
                dict(
                    run_id=f"{condition}-{repetition:03d}",
                    condition=condition,
                    repetition=repetition,
                    config=spec.config_file,
                    prompt=spec.prompts[condition],
                    objective_seed=spec.objective_seed_start + repetition - 1,
                    noise_seed=spec.noise_seed_start + repetition - 1,
                    agents=config.agents,
                    experiment_budget=config.experiment_budget,
                    status="pending",
                )
            )
    return dict(**spec.model_dump(), runs=entries)


def config_for_run(root: Path, entry: dict):
    config = load_config(root / entry["config"])
    config.task.objective_seed = entry["objective_seed"]
    config.task.noise_seed = entry["noise_seed"]
    config.task.instructions_file = (root / entry["prompt"]).resolve()
    return config


def save_json(path: Path, value):
    """Replace manifests atomically so live readers never see half a JSON document."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checksums(root: Path) -> dict:
    return {
        str(path.relative_to(root)): checksum(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "checksums.json"
    }


def git(*args) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY), *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def snapshot_inputs(experiment: Path, root: Path) -> dict:
    destination = root / "inputs"
    destination.mkdir()
    definition = destination / "experiment"
    definition.mkdir()
    sources = {experiment.resolve()}
    for entry in validate_experiment(experiment)["runs"]:
        sources.add((experiment.parent / entry["prompt"]).resolve())
        config_path = (experiment.parent / entry["config"]).resolve()
        sources.add(config_path)
        config = load_config(config_path)
        sources.update(config.task.initial_files.values())
        if config.task.instructions_file:
            sources.add(config.task.instructions_file)
    for filename in ("README.md", "DATASET_CARD.md"):
        source = experiment.parent / filename
        if source.exists():
            sources.add(source.resolve())
    for source in sorted(sources):
        target = definition / source.relative_to(experiment.parent.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    code = destination / "code"
    code.mkdir()
    # Explicit source allowlist: never copy .env, .git, virtualenvs, or old outputs.
    for directory in ("src", "docker", "scripts"):
        shutil.copytree(
            REPOSITORY / directory,
            code / directory,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*"),
        )
    for filename in ("pyproject.toml", "uv.lock", "LICENSE", "README.md", "DESIGN.md"):
        shutil.copyfile(REPOSITORY / filename, code / filename)
    save_json(destination / "checksums.json", checksums(destination))
    return dict(
        git_commit=git("rev-parse", "HEAD"),
        git_dirty=bool(git("status", "--porcelain")),
        source_snapshot="inputs/code",
        experiment_snapshot="inputs/experiment",
        input_checksums="inputs/checksums.json",
        packages={d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]},
    )


def export_index(root: Path, manifest: dict):
    rows = []
    for run in manifest["runs"]:
        agents = run.get("agents_results", [])
        scores = [a["true_objective"] for a in agents if a.get("true_objective") is not None]
        values = [
            run["repetition"],
            run["condition"],
            run["status"],
            f"{sum(a.get('reason') == 'submitted' for a in agents)}/{run['agents']}",
            f"{statistics.mean(scores):.4f}" if scores else "—",
            f"{max(scores):.4f}" if scores else "—",
        ]
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in values)
        link = (
            f'<a href="{run["run_id"]}/review.html">Open run</a>'
            if (root / run["run_id"] / "review.html").exists()
            else "—"
        )
        rows.append(f"<tr>{cells}<td>{link}</td></tr>")
    title = html.escape(manifest["name"])
    (root / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        f"<title>{title}</title><style>body{{font:14px/1.6 system-ui;margin:32px}}"
        "td,th{padding:10px;text-align:left;border-bottom:1px solid #ccc}"
        f"</style><h1>{title}</h1><p>Status: {manifest['status']}. "
        "Mean and best scores exclude agents without a submission; submission counts "
        "are shown separately.</p><table><thead><tr>"
        + "".join(
            f"<th>{h}</th>"
            for h in (
                "Repetition",
                "Condition",
                "Status",
                "Submitted",
                "Mean score",
                "Best score",
                "Explorer",
            )
        )
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></html>"
    )


async def run_experiment(experiment: Path, output: Path | None = None) -> Path:
    if output is not None and output.exists():
        raise FileExistsError(f"batch output already exists: {output}")
    plan = validate_experiment(experiment)
    first = load_config(experiment.parent / plan["runs"][0]["config"])
    if first.harness.kind == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is required for this experiment")
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    root = output or Path("outputs") / plan["name"] / batch_id
    root.mkdir(parents=True, exist_ok=False)
    provenance = snapshot_inputs(experiment, root)
    snapshot = root / "inputs" / "experiment" / experiment.name
    # Execute saved inputs, so edits to the original configs cannot affect later repetitions.
    validate_experiment(snapshot)
    manifest = dict(
        **plan,
        batch_id=batch_id,
        status="running",
        started_at=timestamp(),
        provenance=provenance,
        matching="Objective/noise seeds and settings matched by repetition; noise streams "
        "matched by internal agent index. UUIDs, model outputs and timing are not matched.",
    )
    card = experiment.parent / "DATASET_CARD.md"
    if card.exists():
        shutil.copyfile(card, root / "README.md")
    shutil.copyfile(REPOSITORY / "LICENSE", root / "LICENSE")

    def update():
        save_json(root / "manifest.json", manifest)
        export_index(root, manifest)

    update()
    print(f"Experiment: {root.resolve()}", flush=True)

    async def run(entry):
        directory = root / entry["run_id"]
        entry.update(status="running", started_at=timestamp())
        update()
        print(f"Starting {entry['run_id']}", flush=True)
        try:
            config = config_for_run(snapshot.parent, entry)
            summary = await run_rollout(config, directory)
            entry["agents_results"] = summary["agents"]
            reasons = [a["reason"] for a in summary["agents"]]
            entry["status"] = "error" if "error" in reasons else "finished"
            if "cancelled" in reasons:
                entry["status"] = "cancelled"
        except asyncio.CancelledError:
            entry["status"] = "cancelled"
            raise
        except Exception as error:
            entry.update(status="error", error_type=type(error).__name__, error=str(error))
        finally:
            entry["finished_at"] = timestamp()
            if (directory / "config.json").exists():
                save_json(
                    directory / "run_metadata.json",
                    dict(
                        schema_version=1,
                        experiment=plan["name"],
                        batch_id=batch_id,
                        **{k: v for k, v in entry.items() if k != "agents_results"},
                    ),
                )
                try:
                    export_review(directory)
                except Exception as error:
                    entry["review_error"] = str(error)
                save_json(directory / "checksums.json", checksums(directory))
            update()
            print(f"Finished {entry['run_id']}: {entry['status']}", flush=True)

    try:
        for repetition in range(1, plan["repetitions"] + 1):
            entries = [e for e in manifest["runs"] if e["repetition"] == repetition]
            async with asyncio.TaskGroup() as group:
                for entry in entries:
                    group.create_task(run(entry))
            # Avoid spending on later waves if the current wave has infrastructure/API errors.
            if any(e["status"] != "finished" for e in entries):
                raise RuntimeError(f"repetition {repetition} failed; remaining runs not launched")
        manifest["status"] = "finished"
    except BaseException as error:
        manifest.update(
            status="cancelled"
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt))
            else "error",
            error_type=type(error).__name__,
            error=str(error),
        )
        raise
    finally:
        manifest["finished_at"] = timestamp()
        update()
        save_json(root / "checksums.json", checksums(root))
    print(f"Experiment explorer: {(root / 'index.html').resolve()}", flush=True)
    return root

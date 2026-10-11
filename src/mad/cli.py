import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .config import load_config
from .environment import docker
from .review import export_review, recover_interfaces
from .rollout import run_rollout


def main():
    parser = argparse.ArgumentParser(prog="mad")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build the local Python sandbox image")
    build.add_argument("--image", default="mad-python:local")
    build.add_argument("--context", type=Path, default=Path("docker"))
    run = commands.add_parser("run", help="launch a configured rollout")
    run.add_argument("config", type=Path)
    run.add_argument("--output", type=Path)
    validate = commands.add_parser(
        "validate", help="validate and print a config without launching agents"
    )
    validate.add_argument("config", type=Path)
    batch = commands.add_parser("batch", help="run a matched experiment from its manifest")
    batch.add_argument("experiment", type=Path)
    batch.add_argument("--output", type=Path)
    batch.add_argument("--dry-run", action="store_true", help="validate without model calls")
    preflight = commands.add_parser("preflight", help="two-turn native-tool check; no experiments")
    preflight.add_argument("config", type=Path)
    preflight.add_argument("--batch", action="store_true", help="check each model in an experiment")
    preflight.add_argument("--output", type=Path)
    review = commands.add_parser("review", help="export an offline HTML explorer for a saved run")
    review.add_argument("run", type=Path)
    review.add_argument("--output", type=Path)
    review.add_argument(
        "--recover-tools",
        action="store_true",
        help="retrieve missing initial tool schemas from stored OpenAI responses",
    )
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            from .preflight import preflight_model

            load_dotenv(Path.cwd() / ".env", override=False)
            directory = args.output or Path("outputs") / (
                "preflight-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + "-"
                + uuid.uuid4().hex[:8]
            )
            if args.batch:
                from .experiment import validate_experiment

                plan = validate_experiment(args.config)
                filenames = plan["model_configs"] or {"model": plan["config_file"]}
            else:
                filenames = {"model": args.config.name}
            reports = []
            for label, filename in filenames.items():
                cfg = load_config(args.config.parent / filename)
                if len(cfg.harness.routes) > 1:
                    raise ValueError("preflight accepts one shared route per model config")
                report = asyncio.run(preflight_model(cfg, directory / label))
                reports.append(dict(model_key=label, **report))
            print(json.dumps(dict(output=str(directory.resolve()), models=reports), indent=2))
            if any(report["status"] != "passed" for report in reports):
                raise SystemExit(1)
        elif args.command == "batch":
            from .experiment import run_experiment, validate_experiment

            plan = validate_experiment(args.experiment)
            if args.dry_run:
                print(json.dumps(plan, indent=2))
            else:
                load_dotenv(Path.cwd() / ".env", override=False)
                asyncio.run(run_experiment(args.experiment, args.output))
        elif args.command == "build":
            print(
                asyncio.run(
                    docker("build", "-t", args.image, str(args.context), timeout=600)
                ).decode()
            )
        elif args.command == "validate":
            print(load_config(args.config).model_dump_json(indent=2))
        elif args.command == "review":
            if args.recover_tools:
                load_dotenv(Path.cwd() / ".env", override=False)
                recover_interfaces(args.run)
            destination = export_review(args.run, args.output)
            print(destination.resolve())
        else:
            # Explicit location avoids searching ancestors or unrelated projects.
            # Shell-provided values take precedence over the local file.
            load_dotenv(Path.cwd() / ".env", override=False)
            config = load_config(args.config)
            directory = args.output or Path("outputs") / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
            )
            summary = asyncio.run(run_rollout(config, directory))
            print(
                json.dumps(
                    dict(
                        output=str(directory.resolve()),
                        agents=[
                            {
                                k: a[k]
                                for k in ("agent", "reason", "true_objective", "experiments_used")
                            }
                            for a in summary["agents"]
                        ],
                    ),
                    indent=2,
                )
            )
            if any(a["reason"] == "error" for a in summary["agents"]):
                raise SystemExit(1)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"MAD: {error}\n")

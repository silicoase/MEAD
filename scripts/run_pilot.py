"""Run the six matched pilot configurations and export their explorers."""

import asyncio
import html
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from mad.config import load_config
from mad.recording import write_json
from mad.review import export_review, load_run
from mad.rollout import run_rollout


async def main():
    load_dotenv(Path.cwd() / ".env", override=False)
    root = Path("outputs") / (
        "pilot-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    root.mkdir()
    print(f"Pilot: {root.resolve()}", flush=True)
    entries = []
    write_json(root / "manifest.json", dict(concurrent_runs=3, runs=entries))
    for repetition in (1, 2):
        # Each matched set launches together; every run has isolated Docker storage.
        async def run(condition):
            config_path = Path("examples/pilot") / f"{condition}-{repetition}.toml"
            config = load_config(config_path)
            directory = root / f"{condition}-{repetition}"
            entry = dict(
                condition=condition,
                repetition=repetition,
                objective_seed=config.task.objective_seed,
                noise_seed=config.task.noise_seed,
                config=str(config_path),
                directory=str(directory),
                status="running",
            )
            entries.append(entry)
            write_json(root / "manifest.json", dict(concurrent_runs=3, runs=entries))
            print(f"Starting {condition}, repetition {repetition}", flush=True)
            try:
                summary = await run_rollout(config, directory)
                entry["status"] = "finished"
                entry["agents"] = summary["agents"]
            except Exception as error:
                entry.update(status="error", error=str(error))
            finally:
                if (directory / "config.json").exists():
                    export_review(directory)
                    data = load_run(directory)
                    entry["flags"] = data["flags"]
                write_json(root / "manifest.json", dict(concurrent_runs=3, runs=entries))
                print(
                    f"Finished {condition}, repetition {repetition}: {entry['status']}", flush=True
                )

        await asyncio.gather(*(run(c) for c in ("control", "aware", "interact")))
    rows = []
    for entry in sorted(entries, key=lambda e: (e["repetition"], e["condition"])):
        agents = entry.get("agents", [])
        scores = [a["true_objective"] for a in agents if a.get("true_objective") is not None]
        cells = [
            str(entry["repetition"]),
            entry["condition"],
            entry["status"],
            f"{sum(a['reason'] == 'submitted' for a in agents)}/4",
            f"{statistics.mean(scores):.4f}" if scores else "—",
            f"{max(scores):.4f}" if scores else "—",
            str(len(entry.get("flags", []))),
        ]
        rows.append(
            "<tr>"
            + "".join(f"<td>{html.escape(c)}</td>" for c in cells)
            + f'<td><a href="{entry["condition"]}-{entry["repetition"]}/review.html">Open run</a></td></tr>'
        )
    title = "MAD pilot"
    settings = load_config(Path(entries[0]["config"]))
    offsets = ", ".join(f"{offset:g}" for offset in settings.start_offsets_seconds)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{background:#18181b;color:#f7f6f0;font:14px/1.6 system-ui;margin:32px}}
a{{color:#b3e2f4}}table{{border-collapse:collapse}}td,th{{padding:12px;border-bottom:1px solid #353e43;text-align:left}}h1{{font-size:16px}}</style></head>
<body><h1>{title}</h1><p>{settings.agents} agents per run, {settings.experiment_budget} experiments each. Start offsets: {offsets} seconds. Session timeout: {settings.timeout_seconds / 60:g} minutes.</p>
<table><thead><tr>{"".join("<th>" + h + "</th>" for h in ["Repetition", "Condition", "Status", "Submitted", "Mean score", "Best score", "Flags", "Explorer"])}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></body></html>"""
    (root / "index.html").write_text(page)
    print(f"Pilot explorer: {(root / 'index.html').resolve()}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

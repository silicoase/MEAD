"""Collect a frozen results snapshot, then render three figure options.

Run collect with MAD's Python and plot with a Python containing seaborn,
matplotlib, numpy, Pillow and fontTools. Outputs stay outside the raw batch.
"""

import argparse
import json
from pathlib import Path


def collect(batch, output):
    import sys

    # Evaluate candidates with the objective implementation frozen at collection.
    sys.path.insert(0, str(batch / "inputs/code/src"))
    from mad.config import TaskConfig
    from mad.task import SyntheticObjective

    manifest = json.loads((batch / "manifest.json").read_text())
    conditions = manifest["conditions"]
    repetitions = sorted({r["repetition"] for r in manifest["runs"]})
    matched = [
        rep for rep in repetitions
        if all(
            r["status"] == "finished"
            for r in manifest["runs"] if r["repetition"] == rep
        )
    ]
    runs = []
    for entry in manifest["runs"]:
        if entry["repetition"] not in matched:
            continue
        directory = batch / entry["run_id"]
        config = json.loads((directory / "config.json").read_text())
        summary = json.loads((directory / "summary.json").read_text())
        objective = SyntheticObjective(TaskConfig.model_validate(config["task"]))
        events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
        start = min(e["elapsed_seconds"] for e in events if e["kind"] == "agent_started")
        end = max(e["elapsed_seconds"] for e in events if e["kind"] == "agent_finished")
        measurements = [e for e in events if e["kind"] == "experiment_completed"]
        points = []
        best = float("-inf")
        for event in measurements:
            best = max(best, objective.evaluate(event["record"]["parameters"]))
            points.append([(event["elapsed_seconds"] - start) / (end - start), best])
        if not points:
            raise ValueError(f"No measurements in {entry['run_id']}")
        runs.append(dict(run_id=entry["run_id"], condition=entry["condition"],
                         repetition=entry["repetition"], duration_seconds=end - start,
                         final_scores=[a["true_objective"] for a in summary["agents"]],
                         points=points))
    if not runs:
        raise ValueError("No complete matched repetitions yet")
    output.mkdir(parents=True, exist_ok=True)
    (output / "performance.json").write_text(json.dumps(dict(
        batch=str(batch.resolve()), conditions=conditions, repetitions=matched,
        metric="Best true objective among completed measurements, pooled across agents; "
               "final submissions excluded. Equal weight per run. No value before first measurement.",
        time="First agent_started to last agent_finished in each run; setup/cleanup excluded.",
        runs=runs,
    ), indent=2) + "\n")
    print(f"Collected {len(runs)} runs / {len(matched)} matched repetitions")


def plot(output, brand):
    import matplotlib
    matplotlib.use("Agg")
    import numpy as np
    from figure_style import COLORS, LINE_STYLES, Chart, style_axes

    data = json.loads((output / "performance.json").read_text())
    conditions = data["conditions"]
    grid = np.linspace(0, 1, 201)
    matrices = {}
    for condition in conditions:
        rows = []
        for run in data["runs"]:
            if run["condition"] != condition:
                continue
            points = np.asarray(run["points"])
            indices = np.searchsorted(points[:, 0], grid, side="right") - 1
            values = points[np.maximum(indices, 0), 1].copy()
            values[indices < 0] = np.nan
            rows.append(values)
        matrices[condition] = np.asarray(rows)
    # A fixed sample for each mean: no changing denominator during early time.
    visible = np.all(np.isfinite(np.concatenate(list(matrices.values()))), axis=0)
    x = grid[visible]
    all_scores = np.concatenate([np.asarray(r["points"])[:, 1] for r in data["runs"]])
    lower, upper = float(all_scores.min()), float(all_scores.max())
    padding = max(.04, (upper - lower) * .08)
    n = len(data["repetitions"])
    colors = ["#18181B", "#075C78", "#4B9AB5"]
    shades = COLORS
    styles = LINE_STYLES

    def chart(subtitle, *, panels=1, sharey=False, legend=True):
        return Chart(output, brand, title="Performance throughout 10-experiment runs",
                     subtitle=subtitle, panels=panels, sharey=sharey, legend=legend,
                     status="")

    for name, palette, bands in [("a_mean_curves", shades, False),
                                 ("b_variation_bands", colors, True)]:
        layout = chart("Best (noiseless) score across all 4 agents, mean across runs"
                       + (" · ±1 SD" if bands else ""))
        ax = layout.axes[0]
        for condition, color, style in zip(conditions, palette, styles):
            values = matrices[condition][:, visible]
            mean = values.mean(axis=0)
            if bands:
                spread = values.std(axis=0, ddof=1) if n > 1 else np.zeros_like(mean)
                ax.fill_between(x, mean - spread, mean + spread, color=color, alpha=.12, linewidth=0)
            ax.plot(x, mean, color=color, linestyle=style, linewidth=2.3,
                    label=condition.capitalize())
        style_axes(ax)
        ax.set_ylim(lower - padding, upper + padding)
        # Make room for the descriptive bands even if their bounds exceed raw values.
        if bands:
            ax.relim()
            lo = min((matrices[c][:, visible].mean(0) - matrices[c][:, visible].std(0, ddof=1)).min()
                     for c in conditions) if n > 1 else lower
            hi = max((matrices[c][:, visible].mean(0) + matrices[c][:, visible].std(0, ddof=1)).max()
                     for c in conditions) if n > 1 else upper
            ax.set_ylim(min(lower, lo) - padding, max(upper, hi) + padding)
        ax.set_ylabel("Best tested score")
        layout.legend(ax)
        layout.save(output, name)

    layout = chart("Pale lines: individual runs · dark line: condition mean",
                   panels=3, sharey=True, legend=False)
    axes = layout.axes
    for condition, ax in zip(conditions, axes):
        for row in matrices[condition]:
            ax.plot(grid, row, color="#84BDCF", alpha=.65, linewidth=.8)
        ax.plot(x, matrices[condition][:, visible].mean(0), color="#075C78", linewidth=2.3)
        style_axes(ax, panels=3)
        ax.set_ylim(lower - padding, upper + padding)
        ax.set_title(condition.capitalize(), fontsize=12)
    axes[0].set_ylabel("Best tested score")
    layout.save(output, "c_individual_runs")
    print(f"Rendered three PNG/SVG options in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["collect", "plot"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--brand", type=Path)
    args = parser.parse_args()
    if args.mode == "collect":
        if args.batch is None:
            parser.error("collect requires --batch")
        collect(args.batch, args.output)
    else:
        if args.brand is None:
            parser.error("plot requires --brand")
        plot(args.output, args.brand)

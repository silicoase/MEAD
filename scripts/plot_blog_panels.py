"""Render paired-model budget-axis blog drafts from collected figure data."""
import argparse
import html
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from blog_figure_layout import BlogFigure


def render(source, batch, output):
    output.mkdir(parents=True, exist_ok=True)
    data = json.loads((source / "chart-data.json").read_text())
    outcomes = json.loads((source / "outcomes.json").read_text())
    manifest = json.loads((batch / "manifest.json").read_text())
    models = [m for m in ["haiku", "luna6", "sol61"] if m in data["models"]]
    models += [m for m in data["models"] if m not in models]
    references = {}
    for model in models:
        runs = [r for r in outcomes["runs"] if r["model"] == model and r["condition"] == "control"]
        values = []
        for run in runs:
            ref = json.loads((batch / run["run_id"] / "objective_reference.json").read_text())
            entry = next(r for r in manifest["runs"] if r["run_id"] == run["run_id"])
            assert ref["task"]["objective_seed"] == entry["objective_seed"]
            values.append(ref)
        references[model] = {
            "sets": len(values),
            "mean_estimated_optimum": statistics.mean(r["estimated_maximum"] for r in values),
            "mean_upper_bound": statistics.mean(r["upper_bound"] for r in values),
            "max_bound_gap": max(r["bound_gap"] for r in values),
        }
    (output / "optimum-reference.json").write_text(json.dumps(references, indent=2) + "\n")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "figure.facecolor": "#F7F6F0", "axes.facecolor": "#F7F6F0",
                         "savefig.facecolor": "#F7F6F0", "svg.fonttype": "path"})
    colors = {"control": "#075C78", "interact": "#4B9AB5"}
    titles = {'mean_agent_best': 'Average agent performance throughout run', 'maximum_agent_best': 'Frontier performance throughout run', 'peer_reads': 'Reading peers’ work', 'peer_mentions': 'References to peers in lab notes', 'specific_mentions': 'References to specific peers in lab notes', 'discovered_peer_result': 'Discovering peers’ experiment records', 'discovered_peer_note': 'Discovering peers’ notebooks', 'discovered_either': 'Discovering peers’ work', 'wait_calls': 'Waiting during the run', 'cost_usd': 'API spending throughout run', 'reasoning_mentions': 'References to peers in internal reasoning', 'reasoning_specific_mentions': 'References to specific peers in internal reasoning', 'assistant_message_mentions': 'References to peers in assistant messages', 'assistant_message_specific_mentions': 'References to specific peers in assistant messages'}
    subtitles = {'mean_agent_best': 'Each agent’s best noiseless experiment score, averaged across agents and runs', 'maximum_agent_best': 'Best noiseless score across all 10 agents, mean across runs', 'peer_reads': 'Cumulative successful reads of peers’ files, mean across runs', 'peer_mentions': 'Cumulative shared-note writes mentioning other agents, mean across runs', 'specific_mentions': 'Cumulative shared-note writes mentioning an identifiable peer, mean across runs', 'discovered_peer_result': 'Share of agents that listed a peer’s experiment record, mean across runs', 'discovered_peer_note': 'Share of agents that listed a peer’s notebook, mean across runs', 'discovered_either': 'Share of agents that listed a peer’s experiment record or notebook, mean across runs', 'wait_calls': 'Cumulative wait-tool calls, mean across runs; API cooldowns excluded', 'cost_usd': 'Cumulative provider-reported cost, mean across runs', 'reasoning_mentions': 'Cumulative responses with peer mentions in available reasoning text, mean across runs', 'reasoning_specific_mentions': 'Cumulative responses naming an identifiable peer in available reasoning text, mean across runs', 'assistant_message_mentions': 'Cumulative private assistant messages mentioning other agents, mean across runs', 'assistant_message_specific_mentions': 'Cumulative private assistant messages mentioning an identifiable peer, mean across runs'}
    ylabels = {"peer_reads": "Cumulative reads", "peer_mentions": "Cumulative mentions",
               "specific_mentions": "Cumulative mentions", "wait_calls": "Cumulative wait calls",
               "cost_usd": "Cumulative API cost (USD)"}
    files = []
    for metric, label in data["metrics"].items():
        performance = metric in {"mean_agent_best", "maximum_agent_best"}
        discovery = metric.startswith("discovered_")
        layout = BlogFigure(titles.get(metric, label), subtitles[metric],
                            [data["model_labels"][m] for m in models],
                            width=max(12, 4.8 * len(models)), sharey=True)
        fig, axes = layout.fig, layout.axes
        limits = data["scales"][metric]["limits"]
        if performance:
            limits = [min(0, limits[0]), max(r["mean_upper_bound"] for r in references.values()) * 1.08]
        for ax, model in zip(axes, models):
            unavailable_reasoning = "reasoning" in metric and not any(
                r.get("reasoning_text_coverage", {}).get("responses_with_reasoning_text", 0)
                for r in outcomes["runs"] if r["model"] == model)
            for condition in ["control", "interact"]:
                curve = next(s for s in data["series"] if s["metric"] == metric
                             and s["model"] == model and s["axis"] == "budget"
                             and s["condition"] == condition and s.get("mode", "levels") == "levels")
                if not unavailable_reasoning:
                    ax.step(curve["x"], curve["y"], where="post", color=colors[condition],
                            linestyle="-" if condition == "control" else "--", linewidth=2.3,
                            label=condition.capitalize())
            if unavailable_reasoning:
                ax.text(.5, .5, "Reasoning text unavailable", transform=ax.transAxes,
                        ha="center", color="#666666")
            if performance:
                optimum = references[model]["mean_estimated_optimum"]
                ax.axhline(optimum, color="#8A7153", linestyle=":", linewidth=1.8,
                           label="Mean estimated optimum")
            ax.set_xlim(0, 1)
            ax.set_ylim(*limits)
            ax.xaxis.set_major_formatter(PercentFormatter(1))
            if discovery:
                ax.yaxis.set_major_formatter(PercentFormatter(1))
            ax.set_xlabel("Share of experimental budget consumed", labelpad=9,
                          fontsize=9 if len(models) > 2 else 10)
            ax.grid(axis="y", color="#DEE3E6", linewidth=.7)
            for spine in ax.spines.values():
                spine.set_visible(False)
        ylabel = "Noiseless experiment score" if performance else (
            "Share of agents" if discovery else ylabels.get(metric, "Cumulative mentions"))
        axes[0].set_ylabel(ylabel, labelpad=10)
        handles, labels = axes[0].get_legend_handles_labels()
        if not handles:
            handles, labels = axes[1].get_legend_handles_labels()
        note = "Notes:"
        if performance:
            note += " Completed experiments only; final submissions excluded."
        elif discovery:
            note += "\nFirst successful peer-artifact listing per agent."
        elif metric == "cost_usd":
            note = ""
        elif metric == "peer_reads":
            note += " Successful peer-file reads, including repeated reads. Direct Python reads are not recorded."
        elif metric in {"peer_mentions", "specific_mentions"}:
            note += " Successful shared-note writes/appends containing a peer mention; each operation counts once."
        elif "reasoning" in metric:
            note += " Available reasoning text/summaries only; each response counts once. Coverage varies by provider."
        elif "assistant_message" in metric:
            note += " Private assistant transcript messages only; each response counts once."
        else:
            note += " The wait tool pauses an agent for the requested duration."
        if all(r["sets"] == 1 for r in references.values()):
            note = "Pilot: one matched pair per model. " + note
        layout.finish(handles, labels, note)
        name = metric + "-budget-panels"
        fig.savefig(output / (name + ".png"), dpi=200)
        fig.savefig(output / (name + ".svg"))
        plt.close(fig)
        files.append({"name": name, "title": titles.get(metric, label)})
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>MEAD figure drafts</title><style>body{font:16px system-ui;background:#F7F6F0;color:#18181B;max-width:1450px;margin:30px auto;padding:20px}img{width:100%}section{margin:40px 0}a{color:#075C78}</style><h1>MEAD · Model comparison drafts</h1><p>Budget consumed is the default axis. Descriptive curves; uncertainty intervals have not yet been added.</p>'
    for item in files:
        name = item["name"]
        page += f'<section><h2>{html.escape(item["title"])}</h2><a href="{name}.png">PNG</a> · <a href="{name}.svg">SVG</a><img src="{name}.png" alt="{html.escape(item["title"])}" loading="lazy"></section>'
    if (output / "final-scores-and-variation-panels.png").exists():
        page += '<section><h2>Final scores and within-run variation</h2><a href="final-scores-and-variation-panels.svg">SVG</a><img src="final-scores-and-variation-panels.png" alt="Final scores and within-run variation"></section>'
    (output / "index.html").write_text(page + "</html>")
    print(json.dumps({"figures": len(files), "references": references, "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("batch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.source, args.batch, args.output)

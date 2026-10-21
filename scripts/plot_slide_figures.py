"""Render slide versions of the cross-provider blog figures.

No figure title, subtitle or notes (the slide title carries them), larger text,
a transparent background and the slide deck's font. Reads the data behind the
blog figures: blog-panels/final-scores-and-variation-data.json (written by
plot_final_scores.py) and figures/chart-data.json.
"""
import argparse
import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

root = Path(__file__).resolve().parents[1]
MODELS = ["haiku", "luna6", "sol61"]
LABELS = {"haiku": "Haiku", "luna6": "Luna", "sol61": "Sol"}
CONDITIONS = ["control", "interact"]
COLORS = {"control": "#075C78", "interact": "#4B9AB5"}
FOREGROUND = "#18181B"
WIDTH = .36
# Inches. About the slide's content width, so text sizes read as points on the slide.
SIZE_WIDE, SIZE_SINGLE = (10.4, 3.9), (6.8, 3.9)


def bar_label(value):
    return f"{value:.0f}" if value >= 10 else f"{value:.2g}"


def bar_panel(ax, title, values, ylabel=None, optimum=None):
    xs = range(len(MODELS))
    for i, condition in enumerate(CONDITIONS):
        bars = ax.bar([x + (i - .5) * WIDTH for x in xs], [values[m, condition] for m in MODELS],
                      WIDTH, color=COLORS[condition], label=condition.capitalize())
        ax.bar_label(bars, labels=[bar_label(v) for v in bars.datavalues], padding=4, fontsize=12)
    if optimum is not None:
        ax.axhline(optimum, color="#8A7153", linestyle=":", linewidth=2,
                   label="Mean estimated optimum")
        ax.set_ylim(0, .7)
    else:
        ax.set_ylim(0, max(values.values()) * 1.18)
    ax.set_xticks(list(xs), [LABELS[m] for m in MODELS])
    ax.set_title(title, loc="left", fontsize=15, pad=12)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#DEE3E6", linewidth=.8)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)


def figure(panels, size):
    fig, axes = plt.subplots(1, len(panels), figsize=size, layout="constrained", squeeze=False)
    for ax, panel in zip(axes[0], panels):
        bar_panel(ax, **panel)
    handles, labels = axes[0][0].get_legend_handles_labels()
    # Legend order: conditions, then the optimum line when present.
    order = sorted(range(len(labels)), key=lambda i: labels[i] == "Mean estimated optimum")
    fig.legend([handles[i] for i in order], [labels[i] for i in order],
               loc="outside lower center", ncol=len(labels), frameon=False)
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", nargs="?", type=Path,
                        default=root / "outputs/cross-provider-review/three-model-25-full")
    parser.add_argument("--font", type=Path, help="TTF/OTF file for all text (default DejaVu Sans)")
    parser.add_argument("--output", type=Path, help="default: <base>/slide-figures")
    args = parser.parse_args()
    output = args.output or args.base / "slide-figures"
    output.mkdir(parents=True, exist_ok=True)

    family = "DejaVu Sans"
    if args.font:
        font_manager.fontManager.addfont(args.font)
        family = font_manager.FontProperties(fname=args.font).get_name()
        # A single-weight font makes every lookup warn that it fell back to that weight.
        logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    plt.rcParams.update({"font.family": family, "font.size": 14, "text.color": FOREGROUND,
                         "axes.labelcolor": FOREGROUND, "xtick.color": FOREGROUND,
                         "ytick.color": FOREGROUND, "xtick.labelsize": 14,
                         "ytick.labelsize": 13, "legend.fontsize": 14,
                         "svg.fonttype": "path", "savefig.transparent": True})

    scores = json.loads((args.base / "blog-panels/final-scores-and-variation-data.json").read_text())
    optimum = scores["mean_estimated_optimum"]
    final = {metric: {(g["model"], g["condition"]): g[metric] for g in scores["groups"]}
             for metric in ["mean", "maximum", "sd"]}

    chart = json.loads((args.base / "figures/chart-data.json").read_text())

    def end_of_run(metric):
        # Final point of each budget-axis curve the blog plots: mean count per run.
        return {(s["model"], s["condition"]): s["y"][-1] for s in chart["series"]
                if s["metric"] == metric and s["axis"] == "budget"
                and s.get("mode", "levels") == "levels" and s["model"] in MODELS}

    figures = {
        "slide-mean-final-score": figure([
            dict(title="Mean final score", values=final["mean"], ylabel="Final score",
                 optimum=optimum),
        ], SIZE_SINGLE),
        "slide-max-and-sd": figure([
            dict(title="Maximum final score", values=final["maximum"], ylabel="Final score",
                 optimum=optimum),
            dict(title="Within-run variation in final scores", values=final["sd"],
                 ylabel="Standard deviation"),
        ], SIZE_WIDE),
        "slide-interactions": figure([
            dict(title="Peer-file reads", values=end_of_run("peer_reads"),
                 ylabel="Mean count per run"),
            dict(title="Other-agent mentions", values=end_of_run("peer_mentions")),
            dict(title="Specific-agent mentions", values=end_of_run("specific_mentions")),
        ], SIZE_WIDE),
    }
    for name, fig in figures.items():
        fig.savefig(output / f"{name}.svg")
        fig.savefig(output / f"{name}.png", dpi=200)
        plt.close(fig)
    print(json.dumps({"output": str(output), "figures": sorted(figures), "font": family}))


if __name__ == "__main__":
    main()

"""Render final submitted score and within-run SD panels."""
import argparse
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from blog_figure_layout import BlogFigure

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('base', nargs='?', type=Path, default=root / 'outputs/cross-provider-review/full-haiku-luna')
base = parser.parse_args().base
data = json.loads((base / 'figures/outcomes.json').read_text())
ref = json.loads((base / 'blog-panels/optimum-reference.json').read_text())
out = base / 'blog-panels'
colors = ['#075C78', '#4B9AB5']
conditions = ['control', 'interact']
models = [m for m in ['haiku', 'luna6', 'sol61'] if any(r['model'] == m for r in data['runs'])]
labels = {'haiku': 'Haiku', 'luna6': 'Luna', 'sol61': 'Sol'}
stats = {}
for model in models:
    for condition in conditions:
        runs = [r for r in data['runs'] if r['model'] == model and r['condition'] == condition]
        assert runs and all(len(r['final_scores']) == 10 for r in runs)
        stats[model, condition] = {
            'mean': statistics.mean(s for r in runs for s in r['final_scores']),
            'maximum': statistics.mean(max(r['final_scores']) for r in runs),
            'sd': statistics.mean(statistics.stdev(r['final_scores']) for r in runs),
        }
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                     'figure.facecolor': '#F7F6F0', 'axes.facecolor': '#F7F6F0',
                     'savefig.facecolor': '#F7F6F0', 'svg.fonttype': 'path'})
panel_titles = ['Panel A. Mean final score', 'Panel B. Maximum final score',
                'Panel C. Within-run variation in final scores']
layout = BlogFigure('Final performance and convergence',
    'Mean score, maximum score, and between-agent standard deviation within each run, averaged across runs',
    panel_titles)
fig, axes = layout.fig, layout.axes
width = .34
optimum = ref['haiku']['mean_estimated_optimum']
for ax, metric in zip(axes, ['mean', 'maximum', 'sd']):
    for i, condition in enumerate(conditions):
        bars = ax.bar([x + (i-.5)*width for x in range(len(models))],
                      [stats[m, condition][metric] for m in models],
                      width, color=colors[i], label=condition.capitalize())
        ax.bar_label(bars, fmt='%.2g', padding=4, fontsize=9)
    ax.set_xticks(range(len(models)), [labels[m] for m in models])
    if metric != 'sd':
        ax.axhline(optimum, color='#8A7153', linestyle=':', linewidth=1.8,
                   label='Mean estimated optimum')
        ax.set_ylim(0, .7)
        ax.set_ylabel('Final Score')
    else:
        ax.set_ylim(0, max(v['sd'] for v in stats.values())*1.25)
        ax.set_ylabel('Standard Deviation')
for ax in axes:
    ax.set_axisbelow(True)
    ax.grid(axis='y', color='#DEE3E6', linewidth=.7)
    for spine in ax.spines.values():
        spine.set_visible(False)
handles, labels = axes[0].get_legend_handles_labels()
layout.finish(handles, labels,
    "Notes: 'Mean estimated optimum' reports the mean of estimated optima for the generated objective functions.")
for ext in ['png', 'svg']:
    fig.savefig(out / ('final-scores-and-variation-panels.' + ext), dpi=200)
(out / 'final-scores-and-variation-data.json').write_text(json.dumps({
    'groups': [{'model': m, 'condition': c, **v} for (m, c), v in stats.items()],
    'mean_estimated_optimum': optimum,
}, indent=2) + '\n')

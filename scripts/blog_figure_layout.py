"""Shared structural layout for publication figures.

Rows own their space: title, subtitle, panel headings, plots, legend, notes.
All dimensions are inches; text wraps to its allocated width before layout.
"""
import textwrap
import matplotlib.pyplot as plt

BACKGROUND = '#F7F6F0'


def wrapped(text, width_inches, font_size):
    # Conservative average character width for DejaVu Sans, measured in points.
    columns = max(12, int(width_inches * 72 / (font_size * .55)))
    return '\n'.join(textwrap.fill(line, columns) for line in text.splitlines())


class BlogFigure:
    def __init__(self, title, subtitle, panel_titles, width=14.4, sharey=False):
        self.title, self.subtitle = title, subtitle
        self.width = width
        self.panel_titles = panel_titles
        self.fig = plt.figure(figsize=(width, 6))
        self.sharey = sharey
        self.axes = []
        # Plot axes are placed into the final grid after notes and legend are known.
        for _ in panel_titles:
            self.axes.append(self.fig.add_subplot(1, len(panel_titles), len(self.axes)+1,
                sharey=self.axes[0] if sharey and self.axes else None))
        if sharey:
            for ax in self.axes[1:]:
                ax.tick_params(labelleft=False)

    def finish(self, handles, labels, notes=''):
        content_width = self.width - 1.15
        title = wrapped(self.title, content_width, 19)
        subtitle = wrapped(self.subtitle, content_width, 10)
        notes = wrapped(' '.join(notes.split()), content_width, 8) if notes else ''
        headings = [wrapped(t, content_width / len(self.axes) - .3, 12)
                    for t in self.panel_titles]
        rows = [.30 * len(title.splitlines()), .19 * len(subtitle.splitlines()),
                .23 * max(len(t.splitlines()) for t in headings), 3.2, .38]
        if notes:
            rows.append(.16 * len(notes.splitlines()))
        gap = .17
        height = sum(rows) + gap * (len(rows)-1) + .65
        self.fig.set_size_inches(self.width, height)
        grid = self.fig.add_gridspec(len(rows), 1, height_ratios=rows,
            left=.85/self.width, right=1-.3/self.width,
            bottom=.3/height, top=1-.35/height,
            hspace=gap/(sum(rows)/len(rows)))
        def text_row(row, text, size, color='#18181B'):
            ax = self.fig.add_subplot(grid[row]); ax.set_axis_off()
            ax.text(0, 1, text, transform=ax.transAxes, va='top', fontsize=size, color=color)
        text_row(0, title, 19)
        text_row(1, subtitle, 10, '#555555')
        head_grid = grid[2].subgridspec(1, len(self.axes), wspace=.25)
        plot_region = grid[3].subgridspec(2, 1, height_ratios=[2.78, .42], hspace=0)
        plots = plot_region[0].subgridspec(1, len(self.axes), wspace=.25)
        for i, (ax, heading) in enumerate(zip(self.axes, headings)):
            header = self.fig.add_subplot(head_grid[i]); header.set_axis_off()
            header.text(0, 0, heading, transform=header.transAxes, va='bottom', fontsize=12)
            ax.set_subplotspec(plots[i])
        legend_ax = self.fig.add_subplot(grid[4]); legend_ax.set_axis_off()
        legend_ax.legend(handles, labels, loc='center', ncol=len(labels), frameon=False)
        if notes:
            text_row(5, notes, 8, '#555555')
        return self.fig

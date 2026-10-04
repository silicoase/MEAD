"""Shared Seaborn theme and GridSpec layout for MAD figures."""

from pathlib import Path

COLORS = ["#075C78", "#4B9AB5", "#84BDCF"]
LINE_STYLES = ["-", "--", ":"]


def configure_theme(output):
    import seaborn as sns
    from fontTools.ttLib import TTCollection
    from matplotlib import font_manager

    font_path = output / "AvenirNext-Medium.ttf"
    if not font_path.exists():
        with TTCollection("/System/Library/Fonts/Avenir Next.ttc") as collection:
            font = next(f for f in collection.fonts
                        if f["name"].getDebugName(6) == "AvenirNext-Medium")
            font.save(font_path)
    font_manager.fontManager.addfont(font_path)
    family = font_manager.FontProperties(fname=font_path).get_name()
    sns.set_theme(style="whitegrid", font=family, rc={
        "text.color": "#18181B", "axes.labelcolor": "#18181B",
        "xtick.color": "#18181B", "ytick.color": "#18181B",
        "grid.color": "#E6EAED", "grid.linewidth": .7,
        "axes.labelsize": 11, "xtick.labelsize": 10, "ytick.labelsize": 10,
        "svg.fonttype": "none",
    })
    return family


def style_axes(ax, *, panels=1):
    import seaborn as sns
    from matplotlib.ticker import PercentFormatter

    ax.grid(axis="x", visible=False)
    sns.despine(ax=ax, left=True, bottom=True)
    ax.set_xlim(0, 1)
    if panels > 1:
        ax.set_xticks([0, .5, 1])
    ax.xaxis.set_major_formatter(PercentFormatter(1))


class Chart:
    """Named layout rows; note height and wrapping follow rendered text width."""

    def __init__(self, output, brand, *, title, subtitle, status, panels=1,
                 note="", sharey=False, legend=True):
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties

        family = configure_theme(output)
        self.fig = plt.figure(figsize=(8, 4.5), dpi=200)
        self.fig.canvas.draw()
        renderer = self.fig.canvas.get_renderer()
        properties = FontProperties(family=family, size=7.2)
        # Reserve only the actual icon column, rather than a large footer gap.
        note_width = 8 * 200 * (.965 - .095) * .935
        lines = []
        for word in note.split():
            proposed = (lines[-1] + " " + word) if lines else word
            width = renderer.get_text_width_height_descent(proposed, properties, False)[0]
            if not lines or width > note_width:
                lines.append(word)
            else:
                lines[-1] = proposed
        footer_height = max(.32, len(lines) * .12 + .08)
        # Header rows reserve text height and explicit gaps, independent of plot data.
        header_heights = [17 / 72 * 1.35, .08, 10 / 72 * 1.35, .26]
        top, bottom = .985, .035
        heights = [sum(header_heights), 0, .50, .27 if legend else .04,
                   .23 if status else .04, footer_height]
        heights[1] = 4.5 * (top - bottom) - sum(heights)
        if heights[1] < 1.2:
            raise ValueError("Technical note is too long for the standard 16:9 figure")
        rows = self.fig.add_gridspec(6, 1, height_ratios=heights, hspace=.08,
                                    left=.095, right=.965, top=top, bottom=bottom)

        def component(cell):
            ax = self.fig.add_subplot(cell)
            ax.axis("off")
            return ax

        header = rows[0].subgridspec(4, 1, height_ratios=header_heights, hspace=0)
        title_ax = component(header[0])
        title_ax.text(0, 1, title, fontsize=17, va="top", transform=title_ax.transAxes)
        subtitle_ax = component(header[2])
        subtitle_ax.text(0, 1, subtitle, fontsize=10, va="top", transform=subtitle_ax.transAxes)
        plot_cells = rows[1].subgridspec(1, panels, wspace=.32)
        self.axes = []
        for i in range(panels):
            self.axes.append(self.fig.add_subplot(
                plot_cells[i], sharey=self.axes[0] if sharey and i else None
            ))
        xlabel = component(rows[2])
        xlabel.text(.5, .15, "Share of run elapsed", ha="center", va="center",
                    fontsize=11, transform=xlabel.transAxes)
        self.legend_ax = component(rows[3])
        metadata = component(rows[4])
        if status:
            metadata.text(0, .5, status, fontsize=8, va="center", transform=metadata.transAxes)
        footer = rows[5].subgridspec(1, 2, width_ratios=[.935, .045], wspace=.02)
        notes = component(footer[0])
        if lines:
            notes.text(0, 1, "\n".join(lines), fontsize=7.2, va="top",
                       linespacing=1.2, transform=notes.transAxes)
        mark = component(footer[1])
        mark.imshow(plt.imread(Path(brand) / "assets/png/regular-transparent/logo-128.png"))
        mark.set_anchor("S")

    def legend(self, ax):
        self.legend_ax.legend(*ax.get_legend_handles_labels(), loc="center", ncol=3,
                              frameon=False, fontsize=9)

    def save(self, output, name):
        import matplotlib.pyplot as plt

        for extension in ("png", "svg"):
            self.fig.savefig(output / f"{name}.{extension}", dpi=200, facecolor="white")
        plt.close(self.fig)

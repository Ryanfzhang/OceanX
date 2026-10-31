"""OceanX's one publication style for matplotlib.

The figures agents draw (expert_execution.py points MATPLOTLIBRC at these settings) and the drawing of
every interactive figure (the renderer in figure_reproduction.py, which analysis notebooks also carry)
use the same values, so that they look alike. Text is stored as TrueType, not as matplotlib's default
Type 3, so that a PDF opens in Illustrator with text that can be edited, and an SVG keeps its text.
"""
from __future__ import annotations

# How fonts are stored; nothing on the page changes. Benchmark runs use only these (figure_delivery.py).
EDITABLE: dict[str, object] = {"pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none"}

FONT_SIZE = 9  # points, readable at two-column publication width
# Each text size as an offset from the base size, so that one number scales them all.
FONT_SIZES: dict[str, int] = {"font.size": 0, "axes.labelsize": 0, "axes.titlesize": 1,
                              "xtick.labelsize": -1, "ytick.labelsize": -1, "legend.fontsize": -1}
COLORS = ["#147D78", "#245F82", "#8BCF8B", "#9A4D8E", "#B64342", "#767676"]  # successive lines and bars
STYLE: dict[str, object] = {
    **EDITABLE,
    # A font the machine that edits the figure has (Arial on macOS and Windows), its metric twin, then
    # the font matplotlib ships; matplotlib takes the first one installed, without a warning.
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"],
    "axes.titleweight": "bold",
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
    "legend.frameon": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.dpi": 300,
}


def publication_style(font_size: int = FONT_SIZE) -> dict[str, object]:
    """Every setting but the colour cycle, with text sizes scaled from *font_size*."""
    return {**STYLE, **{key: font_size + offset for key, offset in FONT_SIZES.items()}}


def rc_text(settings: dict[str, object], colors: list[str] | None = None) -> str:
    """Settings as the lines of a matplotlibrc file."""
    def value(item: object) -> str:
        return ", ".join(map(str, item)) if isinstance(item, list) else str(item)
    lines = [f"{key}: {value(item)}" for key, item in settings.items()]
    if colors:
        lines.append("axes.prop_cycle: cycler('color', [{}])".format(
            ", ".join(f"'{color.lstrip('#')}'" for color in colors)))
    return "\n".join(lines) + "\n"


__all__ = ["COLORS", "EDITABLE", "FONT_SIZE", "FONT_SIZES", "STYLE", "publication_style", "rc_text"]

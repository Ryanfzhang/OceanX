"""Draw the six indicators of the trial as one six-axis chart per task type.

Reads results.json in this folder (the trial's own numbers; nothing is recomputed here) and writes
six-indicators.png and six-indicators.svg next to it.

    python plot_indicators.py
"""
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patheffects import withStroke

HERE = Path(__file__).resolve().parent
# (key in results.json, axis label), clockwise from the top
CHARTS = [
    ("open_problem", "开放题", [
        ("Framing", "问题拆解"), ("Correctness", "正确性"), ("Depth", "深度"),
        ("Breadth", "广度"), ("Robustness", "稳健性"), ("Rigor", "严谨性")]),
    ("paper_reproduction", "论文验证题", [
        ("Finding tests", "命题检验"), ("Right verdicts", "判定正确"), ("Method fidelity", "方法忠实"),
        ("Differences explained", "差异归因"), ("Traceability", "可追溯"), ("Robustness", "稳健性")]),
]
# Drawn in this order, so the method of interest lies on top. Told apart by marker and line as well as colour.
METHODS = [
    ("Finch", "Finch", "#7b7a75", (0, (4, 2.5)), "s", 1.4, 0.05),
    ("Claude", "Claude Code", "#d9642c", "-", "^", 1.6, 0.08),
    ("OceanX", "OceanX", "#1f6fb2", "-", "o", 2.3, 0.16),
]
RINGS = (20, 40, 60, 80, 100)


def value(cell: dict) -> float:
    """An indicator's value; the midpoint where the trial gives a lower and an upper bound."""
    return (cell["combined"] + cell["combined_lower"]) / 2


def shown(number: float) -> str:
    """One decimal, halves rounded up (56.25 reads 56.3, as in the trial's table to two decimals)."""
    text = str(Decimal(repr(number)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return "100" if text == "100.0" else text


def point(angle: float, radius: float) -> tuple[float, float]:
    return radius * np.sin(angle), radius * np.cos(angle)


def draw(ax, title: str, axes: list[tuple[str, str]], scores: dict, tasks: int) -> None:
    angles = np.linspace(0, 2 * np.pi, len(axes), endpoint=False)
    closed = np.append(angles, angles[0])
    for ring in RINGS:
        ax.plot(*point(closed, ring), color="0.55" if ring == 100 else "0.82", linewidth=0.8 if ring == 100 else 0.6,
                zorder=1)
        x, y = point(np.pi / len(axes), ring * np.cos(np.pi / len(axes)))
        # Above the polygons and with a white edge, so a line passing behind does not hide the number.
        ax.text(x + 2, y + 2, str(ring), fontsize=7.5, color="0.45", ha="left", va="bottom", zorder=6,
                path_effects=[withStroke(linewidth=2.2, foreground="white")])
    for angle in angles:
        ax.plot(*zip((0, 0), point(angle, 100)), color="0.82", linewidth=0.6, zorder=1)
    for key, _label, colour, style, marker, width, fill in METHODS:
        values = np.array([value(scores[key][name]) for name, _ in axes])
        x, y = point(closed, np.append(values, values[0]))
        ax.fill(x, y, color=colour, alpha=fill, zorder=3)
        ax.plot(x, y, color=colour, linestyle=style, linewidth=width, marker=marker, markersize=5.5,
                markerfacecolor=colour, markeredgecolor="white", markeredgewidth=0.6, zorder=4)
    order = [m for m in reversed(METHODS)]  # the numbers read OceanX, Claude Code, Finch
    for angle, (name, label) in zip(angles, axes):
        side = np.sin(angle)
        x, y = point(angle, 100)
        if abs(side) < 0.3:  # top or bottom axis: label above or below the chart
            up = np.cos(angle) > 0
            ax.text(0, y + (24 if up else -13), label, fontsize=12.5, ha="center", va="center", color="0.1")
            base, anchors, align = y + (12 if up else -25), (-22, 0, 22), "center"
        else:
            align = "left" if side > 0 else "right"
            start = x + (9 if side > 0 else -9)
            ax.text(start, y + 7, label, fontsize=12.5, ha=align, va="center", color="0.1")
            base = y - 6
            anchors = (start, start + 22, start + 44) if side > 0 else (start - 44, start - 22, start)
        for anchor, (key, _l, colour, *_rest) in zip(anchors, order):
            ax.text(anchor, base, shown(value(scores[key][name])), fontsize=9, color=colour, ha=align, va="center")
    ax.set_title(f"{title}（{tasks} 题）", fontsize=14, pad=12, color="0.1")
    ax.set_xlim(-172, 172)
    ax.set_ylim(-138, 140)
    ax.set_aspect("equal")
    ax.axis("off")


def main() -> None:
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    tasks = {kind: len({a["query"] for a in results["attempts"] if a["type"] == kind}) for kind, _, _ in CHARTS}
    plt.rcParams.update({"font.sans-serif": ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"],
                         "font.family": "sans-serif", "axes.unicode_minus": False})
    fig, panels = plt.subplots(1, 2, figsize=(13, 6.6))
    for ax, (kind, title, axes) in zip(panels, CHARTS):
        draw(ax, title, axes, results["summary"][kind], tasks[kind])
    handles = [Line2D([0], [0], color=colour, linestyle=style, linewidth=width, marker=marker, markersize=6,
                      markeredgecolor="white", markeredgewidth=0.6, label=label)
               for _key, label, colour, style, marker, width, _fill in reversed(METHODS)]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=11.5,
               bbox_to_anchor=(0.5, 0.085), handlelength=2.6, columnspacing=2.4)
    fig.text(0.5, 0.035,
             "2026-10-06 审阅批次的只读试算：每题每方法一次运行，rubric 为草稿，不是正式成绩。\n"
             "每个指标 0–100，由判分、计数和运行记录混合（ASPECT_SCORES.md v1.0）。"
             "轴旁数字依次为 OceanX、Claude Code、Finch；有上下界的取中点。",
             ha="center", va="center", fontsize=8.5, color="0.4", linespacing=1.6)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.92, bottom=0.15, wspace=0.04)
    fig.savefig(HERE / "six-indicators.png", dpi=200)
    fig.savefig(HERE / "six-indicators.svg")
    print("wrote", HERE / "six-indicators.png", "and .svg")


if __name__ == "__main__":
    main()

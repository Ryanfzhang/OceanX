"""The six indicators per task type on the review of 2026-10-08 (r2), and their chart.

Reads ../scores.json (the review's own criterion levels; nothing is rejudged) and, for the first
attempts, ../../2026-10-06-three-methods/aspect-trial/results.json. Writes results.json,
six-indicators.png and six-indicators.svg next to this file.

    python six_indicators.py

What is computed here and what is not (evaluation/ASPECT_SCORES.md):
- the judged part of every indicator, for all 51 attempts;
- robustness, with delivery taken from each question's first attempt (see FIRST_ATTEMPT_NOT_DELIVERED);
- NOT the counted parts (probes, candidate causes, findings with a verdict, traceable evidence): the
  judge has recorded them for the 40 attempts that did not change since 2026-10-06, not for the 11 new ones.
"""
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import fmean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patheffects import withStroke

HERE = Path(__file__).resolve().parent
SCORES = HERE.parent / "scores.json"
FIRST = HERE.parents[1] / "2026-10-06-three-methods/aspect-trial/results.json"
METHODS = ("OceanX", "Claude", "Finch")
PAPER = ("Q07", "Q08", "Q09", "Q10")
# indicator -> rubric criteria of its judged part, and the rubric points they hold
OPEN = {"Framing": ("F", 10), "Correctness": ("Q", 20), "Depth": ("M", 20), "Breadth": ("B", 15),
        "Robustness": ("R", 15), "Rigor": ("AI", 20)}
PAPER_POINTS = {"Finding tests": 35, "Right verdicts": 35, "Method fidelity": 10,
                "Differences explained": 10, "Traceability": 10}
# First attempts that ended without a report resting on executed analysis. The review of 2026-10-06
# scored each of them 0 or 2.5; the review of 2026-10-08 calls the completed ones "empty deliveries".
FIRST_ATTEMPT_NOT_DELIVERED = {
    ("Q27", "OceanX"): "failed",
    ("Q25", "Claude"): "completed, but the final message says preprocessing is still running",
    ("Q08", "Finch"): "failed at the step limit", ("Q20", "Finch"): "failed at the step limit",
    ("Q23", "Finch"): "timed out",
    ("Q09", "Finch"): "completed without any executed analysis",
    ("Q15", "Finch"): "completed without any executed analysis",
    ("Q24", "Finch"): "completed without any executed analysis",
    ("Q27", "Finch"): "completed without any executed analysis",
}


def letter(criterion: dict) -> str:
    return criterion["id"].rsplit("-", 1)[-1]


def share(criteria: list[dict], level=lambda c: c["level"] / 4) -> float:
    return 100 * sum(c["weight"] * level(c) for c in criteria) / sum(c["weight"] for c in criteria)


def judged_parts(query: str, criteria: list[dict]) -> dict[str, float]:
    if query not in PAPER:
        return {name: share([c for c in criteria if letter(c) in letters]) for name, (letters, _) in OPEN.items()}
    findings = [c for c in criteria if letter(c).startswith("K")]
    return {"Finding tests": share(findings, lambda c: min(c["level"], 2) / 2),
            "Right verdicts": share(findings, lambda c: max(c["level"] - 2, 0) / 2),
            **{name: share([c for c in criteria if letter(c) == key])
               for name, key in (("Method fidelity", "M"), ("Differences explained", "D"), ("Traceability", "R"))}}


def compute() -> dict:
    review = json.loads(SCORES.read_text(encoding="utf-8"))
    first = {(a["query"], a["method"]): a for a in json.loads(FIRST.read_text(encoding="utf-8"))["attempts"]}
    attempts = []
    for query, entry in review["queries"].items():
        for method in METHODS:
            record = entry["methods"][method]
            judged = judged_parts(query, record["criteria"])
            points = PAPER_POINTS if query in PAPER else {name: p for name, (_, p) in OPEN.items()}
            # The judged parts are a division of the rubric total: together they give it back.
            assert abs(sum(judged[k] * w / 100 for k, w in points.items()) - record["score"]) < 1e-9, (query, method)
            earlier = first[(query, method)]
            delivered = (query, method) not in FIRST_ATTEMPT_NOT_DELIVERED
            # Every first attempt counted as not delivered had no scored scientific product in the first review.
            assert delivered or earlier["original_primary_score"] <= 2.5, (query, method)
            assert not delivered or earlier["original_criterion_total"] > 2.5, (query, method)
            delivery = 100.0 if delivered else 0.0
            if query in PAPER:
                indicators = {name: {"judged": value, "run": None, "combined": value} for name, value in judged.items()}
                indicators["Robustness"] = {"judged": None, "run": delivery, "combined": delivery}
            else:
                indicators = {name: {"judged": value, "run": None, "combined": value} for name, value in judged.items()}
                indicators["Robustness"] = {"judged": judged["Robustness"], "run": delivery,
                                            "combined": 0.75 * judged["Robustness"] + 0.25 * delivery}
            attempts.append({"query": query, "method": method,
                             "type": "paper_reproduction" if query in PAPER else "open_problem",
                             "score": record["score"], "attempt": record["attempt"],
                             "same_attempt_as_first_review": record["attempt"] == earlier["attempt"],
                             "first_attempt": {"status": earlier["status"], "delivered": delivered,
                                               "why_not": FIRST_ATTEMPT_NOT_DELIVERED.get((query, method))},
                             "indicators": indicators})
    summary = {}
    for kind in ("open_problem", "paper_reproduction"):
        summary[kind] = {}
        for method in METHODS:
            rows = [a["indicators"] for a in attempts if a["type"] == kind and a["method"] == method]
            summary[kind][method] = {
                name: {part: (fmean(r[name][part] for r in rows) if rows[0][name][part] is not None else None)
                       for part in ("judged", "run", "combined")} for name in rows[0]}
    return {"status": "provisional_not_official",
            "source": {"scores": str(SCORES.relative_to(HERE.parents[2])), "first_attempts": str(FIRST.relative_to(HERE.parents[2]))},
            "parts": {"judged": "all 51 attempts", "counted": "not included: recorded for 40 of 51 attempts only",
                      "run": "delivery of each question's first attempt; repeated failures are not part of the indicator"},
            "new_attempts_without_counts": sorted(f"{a['query']} {a['method']}" for a in attempts
                                                  if not a["same_attempt_as_first_review"]),
            "attempts": attempts, "summary": summary}


# ---------------------------------------------------------------------------------- the chart
CHARTS = [
    ("open_problem", "开放题", [
        ("Framing", "问题拆解"), ("Correctness", "正确性"), ("Depth", "深度"),
        ("Breadth", "广度"), ("Robustness", "稳健性"), ("Rigor", "严谨性")]),
    ("paper_reproduction", "论文验证题", [
        ("Finding tests", "命题检验"), ("Right verdicts", "判定正确"), ("Method fidelity", "方法忠实"),
        ("Differences explained", "差异归因"), ("Traceability", "可追溯"), ("Robustness", "稳健性")]),
]
# Drawn in this order, so the method of interest lies on top. Told apart by marker and line as well as colour.
STYLES = [
    ("Finch", "Finch", "#7b7a75", (0, (4, 2.5)), "s", 1.4, 0.05),
    ("Claude", "Claude Code", "#d9642c", "-", "^", 1.6, 0.08),
    ("OceanX", "OceanX", "#1f6fb2", "-", "o", 2.3, 0.16),
]
RINGS = (20, 40, 60, 80, 100)


def shown(number: float) -> str:
    """One decimal, halves rounded up."""
    text = str(Decimal(repr(number)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return "100" if text == "100.0" else text


def point(angle, radius):
    return radius * np.sin(angle), radius * np.cos(angle)


def draw(ax, title, axes, scores, tasks):
    angles = np.linspace(0, 2 * np.pi, len(axes), endpoint=False)
    closed = np.append(angles, angles[0])
    for ring in RINGS:
        ax.plot(*point(closed, ring), color="0.55" if ring == 100 else "0.82",
                linewidth=0.8 if ring == 100 else 0.6, zorder=1)
        x, y = point(np.pi / len(axes), ring * np.cos(np.pi / len(axes)))
        # Above the polygons and with a white edge, so a line passing behind does not hide the number.
        ax.text(x + 2, y + 2, str(ring), fontsize=7.5, color="0.45", ha="left", va="bottom", zorder=6,
                path_effects=[withStroke(linewidth=2.2, foreground="white")])
    for angle in angles:
        ax.plot(*zip((0, 0), point(angle, 100)), color="0.82", linewidth=0.6, zorder=1)
    for key, _label, colour, style, marker, width, fill in STYLES:
        values = np.array([scores[key][name]["combined"] for name, _ in axes])
        x, y = point(closed, np.append(values, values[0]))
        ax.fill(x, y, color=colour, alpha=fill, zorder=3)
        ax.plot(x, y, color=colour, linestyle=style, linewidth=width, marker=marker, markersize=5.5,
                markerfacecolor=colour, markeredgecolor="white", markeredgewidth=0.6, zorder=4)
    order = list(reversed(STYLES))  # the numbers read OceanX, Claude Code, Finch
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
            ax.text(anchor, base, shown(scores[key][name]["combined"]), fontsize=9, color=colour,
                    ha=align, va="center")
    ax.set_title(f"{title}（{tasks} 题）", fontsize=14, pad=12, color="0.1")
    ax.set_xlim(-172, 172)
    ax.set_ylim(-138, 140)
    ax.set_aspect("equal")
    ax.axis("off")


def plot(results: dict) -> None:
    tasks = {kind: len({a["query"] for a in results["attempts"] if a["type"] == kind}) for kind, _, _ in CHARTS}
    plt.rcParams.update({"font.sans-serif": ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"],
                         "font.family": "sans-serif", "axes.unicode_minus": False})
    fig, panels = plt.subplots(1, 2, figsize=(13, 6.6))
    for ax, (kind, title, axes) in zip(panels, CHARTS):
        draw(ax, title, axes, results["summary"][kind], tasks[kind])
    handles = [Line2D([0], [0], color=colour, linestyle=style, linewidth=width, marker=marker, markersize=6,
                      markeredgecolor="white", markeredgewidth=0.6, label=label)
               for _key, label, colour, style, marker, width, _fill in reversed(STYLES)]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=11.5,
               bbox_to_anchor=(0.5, 0.085), handlelength=2.6, columnspacing=2.4)
    fig.text(0.5, 0.035,
             "2026-10-08 审阅批次 r2：每题取最新一次运行，rubric 为草稿，不是正式成绩。各轴为判分部分（0–100），"
             "计数部分尚未计入（11 次新运行还没有计数）。\n"
             "稳健性：开放题 = 0.75 × 判分 + 0.25 × 首次运行的交付率，论文题 = 首次运行的交付率。"
             "轴旁数字依次为 OceanX、Claude Code、Finch。",
             ha="center", va="center", fontsize=8.5, color="0.4", linespacing=1.6)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.92, bottom=0.15, wspace=0.04)
    fig.savefig(HERE / "six-indicators.png", dpi=200)
    fig.savefig(HERE / "six-indicators.svg")


def main() -> None:
    results = compute()
    (HERE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for kind, title, axes in CHARTS:
        print(f"{title}: 指标 = OceanX / Claude / Finch")
        for name, label in axes:
            cells = " / ".join(shown(results["summary"][kind][m][name]["combined"]) for m in METHODS)
            print(f"  {label}: {cells}")
    plot(results)
    print("wrote", HERE / "results.json", "and six-indicators.png, .svg")


if __name__ == "__main__":
    main()

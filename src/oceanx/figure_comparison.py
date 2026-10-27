"""A reproduced figure beside its original.

A figure saved under a name that starts with a paper's figure number, such as fig2_layer_vorticity.pdf
for Fig. 2, reproduces that figure of a paper attached to the task. After the run that saved it, its
picture and the original are put side by side in one image beside it, ``_compare_<name>.png`` (a
draft, never delivered), and the agent is asked to compare them there. Left to reopen the original
itself, an agent drew from a look taken some fifty calls earlier and afterwards opened only its own
figure (2026-10-27). Each figure is compared at most MAX_COMPARISONS times in one request.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from oceanx.figure_delivery import preview_path
from oceanx.pdf_text import paper_figure

FIGURE_NAME = re.compile(r"^fig(?:ure)?[_\- ]?(\d+)(?!\d)", re.IGNORECASE)
MAX_COMPARISONS = 2
COMPARISON_LEDGER = "figure-comparisons.json"  # in the agent's .runtime folder: comparisons per request
SIDE_HEIGHT = 900  # pixels of each figure in the comparison
MAX_SIDE_WIDTH = 1500
LABEL_HEIGHT = 44


def _picture(figure: Path) -> Path | None:
    """The image of a saved figure: itself, or the preview drawn beside a PDF (figure_delivery.py)."""
    suffix = figure.suffix.lower()
    if suffix == ".pdf":
        preview = preview_path(figure)
        return preview if preview.is_file() else None
    return figure if suffix in {".png", ".jpg", ".jpeg"} else None


def side_by_side(original: Path, reproduced: Path, target: Path, *, left: str, right: str) -> Path:
    """Write ``original`` and ``reproduced`` at one height into one PNG, each under its label."""
    from PIL import Image, ImageDraw, ImageFont

    sides = []
    for path in (original, reproduced):
        with Image.open(path) as image:
            image = image.convert("RGB")
            scale = min(SIDE_HEIGHT / image.height, MAX_SIDE_WIDTH / image.width)
            sides.append(image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale)))))
    gap = 30
    canvas = Image.new("RGB", (sum(side.width for side in sides) + gap * 3,
                               max(side.height for side in sides) + LABEL_HEIGHT + gap), "white")
    try:
        font = ImageFont.load_default(size=26)
    except TypeError:  # Pillow before 10.1 has one bitmap size
        font = ImageFont.load_default()
    draw, x = ImageDraw.Draw(canvas), gap
    for side, label in zip(sides, (left, right), strict=True):
        draw.text((x, 8), label, fill="black", font=font)
        canvas.paste(side, (x, LABEL_HEIGHT))
        x += side.width + gap
    staging = target.with_name(f".{target.name}.{os.getpid()}.tmp.png")
    canvas.save(staging, format="PNG")
    os.replace(staging, target)
    return target


def compare_reproduced_figures(output_root: Path, saved: list[tuple[str, Path]], papers: tuple[Path, ...],
                               ledger: Path, request: str) -> tuple[str, ...]:
    """Put each figure in ``saved`` that is named after a figure of one of ``papers`` (extracted texts,
    pdf_text.py) beside that original, and say so to the agent."""
    try:
        counts = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        counts = {}
    done = counts.setdefault(request, {})
    notes = []
    for name, figure in saved:
        match = FIGURE_NAME.match(figure.name)
        picture = _picture(figure) if match else None
        if picture is None or done.get(name, 0) >= MAX_COMPARISONS:
            continue
        number = int(match.group(1))
        original = next((image for image in (paper_figure(text, number) for text in papers) if image), None)
        if original is None:
            continue
        target = figure.with_name(f"_compare_{figure.stem}.png")
        try:
            side_by_side(original, picture, target, left=f"Original: Fig. {number} of the paper",
                         right=f"Yours: {figure.name}")
        except Exception:  # noqa: BLE001, S112 - an image that cannot be read leaves the figure as it is
            continue
        done[name] = done.get(name, 0) + 1
        notes.append(
            f"outputs/{name} reproduces Fig. {number} of the paper: open "
            f"outputs/{target.relative_to(output_root).as_posix()}, the original on the left and yours on the "
            "right. Write down every difference in panels, axes and their ranges, curves, fills, colours and "
            "text, then fix those your data allow."
            + (" This was the last comparison of this figure." if done[name] >= MAX_COMPARISONS else ""))
    if notes:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps(counts, sort_keys=True), encoding="utf-8")
    return tuple(notes)


__all__ = ["COMPARISON_LEDGER", "FIGURE_NAME", "MAX_COMPARISONS", "compare_reproduced_figures", "side_by_side"]

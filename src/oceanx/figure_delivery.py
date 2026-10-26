"""How a run delivers its figures.

``interactive`` (the default, the desktop's behavior): an Expert publishes a figure through the
Figure API and the desktop opens it; a figure the API cannot draw (bars, stippling, a polar diagram,
another projection, a schematic, a paper figure reproduced as published) the Expert saves as an image
under its own outputs folder, and that image is delivered too. ``static``: every final figure is such
an image file, and no plotting interface is described anywhere a model reads. Benchmark runs use
``static`` so that every arm delivers the same kind of figure.
"""
from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path

FIGURE_DELIVERY_ENV = "OCEANX_FIGURE_DELIVERY"
FIGURE_DELIVERY_MODES = ("interactive", "static")
STATIC_FIGURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".svg", ".pdf"})
# A PDF figure is shown through a PNG drawn from its first page: the desktop and the browser show images,
# while the vector file is what Download returns. Pixels along the longer edge, sharp on a large screen.
PDF_PREVIEW_EDGE = 2000
# Skills that teach the plotting interface; a static run does not put them in the skill library.
INTERACTIVE_FIGURE_SKILLS = frozenset({"scientific-figure-design"})


def figure_delivery() -> str:
    """This process's delivery mode. The only place the environment variable is read."""
    mode = os.environ.get(FIGURE_DELIVERY_ENV, "").strip().lower() or "interactive"
    if mode not in FIGURE_DELIVERY_MODES:
        raise ValueError(f"{FIGURE_DELIVERY_ENV} must be one of {', '.join(FIGURE_DELIVERY_MODES)}; got {mode!r}")
    return mode


def static_figures() -> bool:
    return figure_delivery() == "static"


def static_figure_files(task_root: Path) -> Iterator[tuple[str, Path]]:
    """Each delivered image of a task as (agent folder name, file).

    An image of any depth under an agent's ``outputs`` folder is delivered. A file whose name starts
    with ``_`` or ``.`` is a draft and is skipped, as is anything reached through a symlink and the
    ``.preview.png`` an interactive figure keeps beside its NetCDF file.
    """
    agents = task_root / "agents"
    if agents.is_symlink() or not agents.is_dir():
        return
    for agent in sorted(agents.iterdir()):
        outputs = agent / "outputs"
        if agent.is_symlink() or not agent.is_dir() or outputs.is_symlink() or not outputs.is_dir():
            continue
        for directory, subfolders, names in os.walk(outputs, followlinks=False):
            subfolders.sort()
            for name in sorted(names):
                path = Path(directory) / name
                if is_delivered_figure(path):
                    yield agent.name, path


def is_delivered_figure(path: Path) -> bool:
    """Whether a file under an agent's ``outputs`` folder is a delivered image (static_figure_files)."""

    name = path.name
    return not (name.startswith(("_", ".")) or path.suffix.lower() not in STATIC_FIGURE_SUFFIXES
                or name.lower().endswith(".preview.png") or path.is_symlink() or not path.is_file())


def pdf_preview_png(pdf: Path) -> bytes | None:
    """The first page of a PDF figure drawn as PNG bytes (PDF_PREVIEW_EDGE); None when it cannot be drawn,
    and the figure is then still delivered as its file."""
    try:
        import pypdfium2 as pdfium  # also draws the pages of the PDFs a researcher attaches (pdf_text.py)

        document = pdfium.PdfDocument(str(pdf))
        try:
            page = document[0]
            scale = PDF_PREVIEW_EDGE / max(*page.get_size(), 1.0)
            image = page.render(scale=scale).to_pil().convert("RGB")
        finally:
            document.close()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 - an unreadable or empty PDF keeps its download
        return None

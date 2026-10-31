"""How a run delivers its figures.

``interactive`` (the default, the desktop's behavior): an Expert publishes a figure through the
Figure API and the desktop opens it; a figure the API cannot draw (bars, stippling, a polar diagram,
another projection, a schematic, a paper figure reproduced as published) the Expert saves as an image
under its own outputs folder, and that image is delivered too. ``static``: every final figure is such
an image file, and no plotting interface is described anywhere a model reads. Benchmark runs use
``static`` so that every arm delivers the same kind of figure.

Every delivered figure that is not itself a picture has its screen picture beside it, a file whose
name ends in ``.preview.png``: the renderer of an interactive figure ``<name>.nc`` writes
``<name>.preview.png`` when the figure is saved, and after each run a PDF figure ``<name>.pdf`` gets
``<name>.pdf.preview.png`` drawn from its first page (preview_path), small enough for the agent that
saved the figure to open. The desktop shows a sharper picture, ``<name>.pdf.display.png``
(display_path), drawn when an interactive run's results are listed. After each run a PDF figure is also
checked for Type 3 fonts (pdf_problems), and the agent is told if it uses them.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from oceanx.figure_preview import DISPLAY_EDGE, MAX_PREVIEW_BYTES, display_png, preview_png
from oceanx.figure_preview import PREVIEW_EDGE as PDF_PREVIEW_EDGE
from oceanx.figure_style import COLORS, EDITABLE, publication_style, rc_text
from oceanx.pdf_text import PDFIUM_LOCK

FIGURE_DELIVERY_ENV = "OCEANX_FIGURE_DELIVERY"
FIGURE_DELIVERY_MODES = ("interactive", "static")
STATIC_FIGURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".svg", ".pdf"})
# Files derived from a figure beside it, never figures of their own: its pictures for agents and for the
# desktop, and the print version of an interactive figure (figure_preview.figure_pdf_path).
DERIVED_SUFFIXES = (".preview.png", ".display.png", ".print.pdf")
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


def matplotlib_settings() -> str:
    """The matplotlibrc of this process's code runs (figure_style.py). Static runs (the benchmark) keep
    matplotlib's look and change only how fonts are stored, which changes nothing on the page."""
    return rc_text(EDITABLE) if static_figures() else rc_text(publication_style(), COLORS)


def static_figure_files(task_root: Path) -> Iterator[tuple[str, Path]]:
    """Each delivered image of a task as (agent folder name, file).

    An image of any depth under an agent's ``outputs`` folder is delivered. A file whose name starts
    with ``_`` or ``.`` is a draft and is skipped, as is anything reached through a symlink and a file
    derived from a figure (DERIVED_SUFFIXES).
    """
    for agent, path in agent_output_files(task_root):
        if is_delivered_figure(path):
            yield agent, path


def agent_output_files(task_root: Path) -> Iterator[tuple[str, Path]]:
    """Saved outputs only; never follow symlinks or include private draft folders."""
    agents = task_root / "agents"
    if agents.is_symlink() or not agents.is_dir():
        return
    for agent in sorted(agents.iterdir()):
        outputs = agent / "outputs"
        if agent.is_symlink() or not agent.is_dir() or outputs.is_symlink() or not outputs.is_dir():
            continue
        for directory, subfolders, names in os.walk(outputs, followlinks=False):
            subfolders[:] = sorted(name for name in subfolders if not name.startswith(("_", ".")))
            for name in sorted(names):
                path = Path(directory) / name
                if not name.startswith(("_", ".")) and not path.is_symlink() and path.is_file():
                    yield agent.name, path


def is_delivered_figure(path: Path) -> bool:
    """Whether a file under an agent's ``outputs`` folder is a delivered image (static_figure_files)."""

    name = path.name
    return not (name.startswith(("_", ".")) or path.suffix.lower() not in STATIC_FIGURE_SUFFIXES
                or name.lower().endswith(DERIVED_SUFFIXES) or path.is_symlink() or not path.is_file())


def preview_path(figure: Path) -> Path:
    """The screen picture of a PDF figure beside it, named after the whole file name so that
    ``sst.pdf`` never shares ``sst.preview.png`` with an interactive figure ``sst.nc``."""
    figure = Path(figure)
    return figure.with_name(f"{figure.name}.preview.png")


def display_path(figure: Path) -> Path:
    """The picture of a PDF figure the desktop shows, beside it (write_pdf_display)."""
    figure = Path(figure)
    return figure.with_name(f"{figure.name}.display.png")


def write_pdf_preview(pdf: Path) -> Path | None:
    """Draw the first page of a PDF figure beside it (preview_path) unless a preview at least as new is
    there; None when the PDF cannot be drawn, and the figure is then still delivered as its file."""
    return _draw_first_page(pdf, preview_path(pdf), PDF_PREVIEW_EDGE, preview_png, MAX_PREVIEW_BYTES)


def write_pdf_display(pdf: Path) -> Path | None:
    """Draw the first page of a PDF figure as large as the desktop shows it (display_path), unless a
    picture at least as new is there; None when the PDF cannot be drawn."""
    return _draw_first_page(pdf, display_path(pdf), DISPLAY_EDGE, display_png, None)


def _draw_first_page(pdf: Path, target: Path, edge: int, encode, max_bytes: int | None) -> Path | None:
    try:
        if (target.is_file() and target.stat().st_mtime_ns >= pdf.stat().st_mtime_ns
                and (max_bytes is None or target.stat().st_size <= max_bytes)):
            return target
        import pypdfium2 as pdfium  # also draws the pages of the PDFs a researcher attaches (pdf_text.py)

        with PDFIUM_LOCK, pdfium.PdfDocument(str(pdf)) as document:
            page = document[0]
            bitmap = page.render(scale=edge / max(*page.get_size(), 1.0))
            try:
                data = encode(bitmap.to_pil())
            finally:
                bitmap.close()
        staging = target.with_name(f".{target.name}.{uuid4().hex}.tmp.png")
        staging.write_bytes(data)
        os.replace(staging, target)
        return target
    except Exception:  # noqa: BLE001 - an unreadable or empty PDF keeps its download
        return None


def pdf_problems(pdf: Path) -> list[str]:
    """Report Type 3 fonts; image shapes and path counts do not establish editability."""
    try:
        from pypdf import PdfReader

        fonts: set[str] = set()
        for page in PdfReader(pdf).pages:
            resources = page.get("/Resources") or {}
            for font in (resources.get("/Font") or {}).values():
                font = font.get_object()
                fonts.add(str(font.get("/Subtype")))
                fonts.update(str(item.get_object().get("/Subtype")) for item in font.get("/DescendantFonts") or [])
    except Exception:  # noqa: BLE001 - a PDF that cannot be read is reported by its preview instead
        return []
    problems = []
    if "/Type3" in fonts:
        problems.append("its text is stored in Type 3 fonts; use pdf.fonttype=42 for TrueType text export")
    return problems

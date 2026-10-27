"""Create a static preview beside a saved OceanX scientific figure.

The NetCDF file remains the canonical interactive result.  This module is an
internal persistence helper, not a model-visible tool: vision-capable agents
read the generated PNG with Deep Agents' native ``read_file`` capability.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from oceanx.figure_reproduction import _FIXED_RENDERER_SOURCE

PREVIEW_EDGE = 2000
# read_file accepts at most 500 KiB, including for previews from dense fields.
MAX_PREVIEW_BYTES = 480_000


def preview_png(image) -> bytes:
    """Encode a PDF or interactive preview within read_file's limit, preserving RGB colours."""
    from PIL import Image

    image = image.convert("RGB")
    image.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
    while True:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()
        if len(data) <= MAX_PREVIEW_BYTES:
            return data
        image = image.resize(tuple(max(1, int(size * 0.8)) for size in image.size),
                             Image.Resampling.LANCZOS)


@lru_cache(maxsize=1)
def _renderer() -> tuple[Callable[[Path], Any], Any]:
    import matplotlib

    matplotlib.use("Agg")
    namespace: dict[str, Any] = {}
    exec(compile(_FIXED_RENDERER_SOURCE, "<oceanx-fixed-renderer>", "exec"), namespace)
    return namespace["render_oceanmind_view"], namespace["plt"]


def figure_pdf_path(source: Path) -> Path:
    """The editable print version a saved interactive figure keeps beside its NetCDF file. Like its
    ``.preview.png`` it is derived from the figure, so it is never a figure of its own
    (figure_delivery.is_delivered_figure)."""
    return Path(source).with_suffix(".print.pdf")


def _write_pdf(figure: Any, target: Path) -> None:
    """Save the drawing as a PDF that Illustrator can edit: the renderer stores text as TrueType and
    keeps lines and colour bars vector. A PDF that cannot be written leaves none behind, so that an
    earlier figure's PDF never stands for this one; the preview is kept either way."""
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp.pdf")
    try:
        figure.savefig(temporary, bbox_inches="tight", facecolor="white")
        os.replace(temporary, target)
    except Exception:  # noqa: BLE001 - the interactive figure and its preview are already saved
        target.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)


def write_figure_preview(source: Path, target: Path | None = None, *, pdf: bool = False) -> Path:
    """Render *source* to an atomic PNG preview and return its path. With ``pdf`` the same drawing is
    also saved as an editable PDF beside the figure (figure_pdf_path)."""

    source = Path(source)
    if source.suffix.lower() != ".nc":
        raise ValueError("OceanX previews require a saved .nc scientific figure")
    target = Path(target) if target is not None else source.with_suffix(".preview.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp.png")
    render, pyplot = _renderer()
    figure = render(source)
    try:
        if pdf:
            _write_pdf(figure, figure_pdf_path(source))
        from PIL import Image

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=120, bbox_inches="tight", facecolor="white")
        buffer.seek(0)
        with Image.open(buffer) as image:
            temporary.write_bytes(preview_png(image))
        os.replace(temporary, target)
    finally:
        pyplot.close(figure)
        if temporary.exists():
            temporary.unlink()
    return target


__all__ = ["figure_pdf_path", "write_figure_preview"]

"""Create a static preview beside a saved OceanX scientific figure.

The NetCDF file remains the canonical interactive result.  This module is an
internal persistence helper, not a model-visible tool: vision-capable agents
read the generated PNG with Deep Agents' native ``read_file`` capability.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from oceanx.figure_reproduction import _FIXED_RENDERER_SOURCE


@lru_cache(maxsize=1)
def _renderer() -> tuple[Callable[[Path], Any], Any]:
    import matplotlib

    matplotlib.use("Agg")
    namespace: dict[str, Any] = {}
    exec(compile(_FIXED_RENDERER_SOURCE, "<oceanx-fixed-renderer>", "exec"), namespace)
    return namespace["render_oceanmind_view"], namespace["plt"]


def write_figure_preview(source: Path, target: Path | None = None) -> Path:
    """Render *source* to an atomic PNG preview and return its path."""

    source = Path(source)
    if source.suffix.lower() != ".nc":
        raise ValueError("OceanX previews require a saved .nc scientific figure")
    target = Path(target) if target is not None else source.with_suffix(".preview.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp.png")
    render, pyplot = _renderer()
    figure = render(source)
    try:
        figure.savefig(temporary, dpi=120, bbox_inches="tight", facecolor="white")
        data = temporary.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Generated figure preview is not a PNG image")
        if len(data) > 8_000_000:
            raise ValueError("Generated figure preview exceeds 8 MB")
        os.replace(temporary, target)
    finally:
        pyplot.close(figure)
        if temporary.exists():
            temporary.unlink()
    return target


__all__ = ["write_figure_preview"]

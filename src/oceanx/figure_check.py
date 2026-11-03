"""A check of each figure an agent's code saves with matplotlib, for faults its own look at the figure missed.

Runs of 2026-11-03 delivered figures whose agents had read the figure rules: a smoothed curve squashed under
the light raw series that set its y axis, maps whose colour range was copied from a paper, budget bars on a
symlog axis, notes in 5.6 pt type. One agent opened the preview of the squashed figure not at all.

This file is also the ``sitecustomize`` of every agent's Python (expert_execution.py writes it into the
agent's runtime folder and puts that folder on PYTHONPATH), so it imports nothing of OceanX and loads
matplotlib only when the agent's code does. After each ``savefig`` to a file it writes what it found, as
one JSON line, to the file OCEAN_FIGURE_CHECK_LOG names; the run reports the last check of each delivered
figure among its figure notes. A check that fails never stops the code that saved the figure.
"""
from __future__ import annotations

import json
import os
import re
import sys

LOG_ENV = "OCEAN_FIGURE_CHECK_LOG"
SMALLEST_TEXT = 6.5  # points; the publication style's smallest text is 8 (figure_style.py)
_LETTER = re.compile(r"^\(?([a-z])\)?$", re.IGNORECASE)


def problems(figure) -> list[str]:
    """What a reader of ``figure`` could not see, or would read wrongly."""
    found = []
    for index, ax in enumerate(figure.axes):
        if getattr(ax, "_colorbar", None) is not None:
            continue
        name = _panel(ax, index)
        for problem in (_squashed(ax), *_colour_ranges(ax), _log_bars(ax)):
            if problem:
                found.append(f"{name}: {problem}")
    small = _small_text(figure)
    if small:
        found.append(small)
    return found


def _panel(ax, index: int) -> str:
    for text in [*ax.texts, ax.title]:
        letter = _LETTER.match(text.get_text().strip())
        if letter:
            return f"panel ({letter.group(1)})"
    label = ax.get_ylabel().strip()
    return f"the panel whose y axis reads '{label}'" if label else f"axes {index + 1}"


def _squashed(ax) -> str | None:
    """A main curve flattened because a light background series sets the y axis."""
    import numpy as np
    from matplotlib.colors import to_rgba

    lines = [line for line in ax.get_lines()
             if line.get_visible() and line.get_linestyle() not in ("None", "", " ")]
    low, high = sorted(ax.get_ylim())
    if len(lines) < 2 or not high > low:
        return None
    widest = max(line.get_linewidth() for line in lines)

    def light(line) -> bool:
        red, green, blue, alpha = to_rgba(line.get_color(), line.get_alpha())
        grey = max(red, green, blue) - min(red, green, blue) < 0.12 and (red + green + blue) / 3 > 0.45
        return alpha < 0.6 or grey or line.get_linewidth() < 0.6 * widest

    def extent(line) -> float:
        try:
            values = np.asarray(line.get_ydata(), dtype=float)
        except (TypeError, ValueError):
            return 0.0
        values = values[np.isfinite(values)]
        return float(values.max() - values.min()) if values.size else 0.0

    background = [extent(line) for line in lines if light(line)]
    main = [extent(line) for line in lines if not light(line)]
    if not background or not main or max(background) < 0.8 * (high - low):
        return None
    share = max(main) / (high - low)
    if share >= 0.3:
        return None
    return (f"the main curve spans {share:.0%} of the y range, which a light background series sets; set the y "
            "limits from the main curve after drawing it and let the background series run off the axis")


def _colour_ranges(ax) -> list[str]:
    """A colour range much wider or much narrower than the field it colours."""
    import numpy as np
    from matplotlib.contour import ContourSet

    found = []
    for mappable in [*ax.collections, *ax.images]:
        if isinstance(mappable, ContourSet):
            if not mappable.filled:
                continue
            low, high = float(mappable.levels[0]), float(mappable.levels[-1])
            field_low, field_high = float(mappable.zmin), float(mappable.zmax)
        else:
            norm, array = getattr(mappable, "norm", None), getattr(mappable, "get_array", lambda: None)()
            if norm is None or array is None or norm.vmin is None or norm.vmax is None:
                continue
            try:
                values = np.ma.masked_invalid(np.ma.asarray(array, dtype=float)).compressed()
            except (TypeError, ValueError):
                continue
            if not values.size:
                continue
            low, high, field_low, field_high = float(norm.vmin), float(norm.vmax), values.min(), values.max()
        width = high - low
        if not width > 0 or not field_high > field_low:
            continue
        if field_low < low - 0.1 * width or field_high > high + 0.1 * width:
            found.append(f"the field reaches {field_low:.3g} to {field_high:.3g}, beyond its colour range "
                         f"{low:.3g} to {high:.3g}; set the colour range from the field")
        elif field_high - field_low < 0.35 * width:
            found.append(f"the field spans {field_low:.3g} to {field_high:.3g}, "
                         f"{(field_high - field_low) / width:.0%} of its colour range {low:.3g} to {high:.3g}; "
                         "set the colour range from the field")
    return found


def _log_bars(ax) -> str | None:
    from matplotlib.container import BarContainer

    scales = {ax.get_xscale(), ax.get_yscale()} & {"log", "symlog"}
    if not scales or not any(isinstance(container, BarContainer) for container in ax.containers):
        return None
    return (f"the bars are on a {scales.pop()} axis, which hides their sizes; give groups of very different "
            "size their own axes instead")


def _small_text(figure) -> str | None:
    from matplotlib.text import Text

    small = [f"'{text.get_text().strip()[:40]}' at {text.get_fontsize():.1f} pt"
             for text in figure.findobj(Text)
             if text.get_visible() and text.get_text().strip() and text.get_fontsize() < SMALLEST_TEXT]
    if not small:
        return None
    more = f" and {len(small) - 3} more" if len(small) > 3 else ""
    return f"text too small to read: {', '.join(small[:3])}{more}; use at least {SMALLEST_TEXT:g} pt"


def install() -> None:
    """Check each figure the code saves to a file, after saving it."""
    from functools import wraps

    from matplotlib import rcParams
    from matplotlib.figure import Figure

    if getattr(Figure.savefig, "_oceanx_checked", False):
        return
    save = Figure.savefig

    @wraps(save)  # pyplot copies its savefig from Figure.savefig and checks that name
    def savefig(self, fname, *args, **kwargs):
        result = save(self, fname, *args, **kwargs)
        log = os.environ.get(LOG_ENV)
        if log and isinstance(fname, (str, os.PathLike)):
            try:
                path = os.path.abspath(os.fspath(fname))
                if not os.path.splitext(path)[1]:  # matplotlib adds the format's suffix
                    path += "." + str(kwargs.get("format") or rcParams["savefig.format"])
                with open(log, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"path": path, "problems": problems(self)}) + "\n")
            except Exception:  # noqa: BLE001, S110 - the figure is saved; a failed check must not undo that
                pass
        return result

    savefig._oceanx_checked = True
    Figure.savefig = savefig


class _WhenImported:
    """Install the check when the code first imports matplotlib's figures, not before."""

    def find_spec(self, name, path=None, target=None):
        if name != "matplotlib.figure":
            return None
        sys.meta_path.remove(self)
        import importlib.util

        spec = importlib.util.find_spec(name)
        if spec is None or spec.loader is None:
            return spec
        loader = spec.loader

        class _Loader:
            def create_module(self, spec):
                return loader.create_module(spec)

            def exec_module(self, module):
                loader.exec_module(module)
                try:
                    install()
                except Exception:  # noqa: BLE001, S110 - figures are drawn unchecked rather than not at all
                    pass

        spec.loader = _Loader()
        return spec


def install_when_imported() -> None:
    """What the agent's Python runs at its start (sitecustomize)."""
    if "matplotlib.figure" in sys.modules:
        install()
    elif not any(isinstance(finder, _WhenImported) for finder in sys.meta_path):
        sys.meta_path.insert(0, _WhenImported())


def sitecustomize() -> str:
    """This file as the sitecustomize of an agent's Python."""
    with open(__file__, encoding="utf-8") as stream:
        return stream.read() + "\n\ninstall_when_imported()\n"

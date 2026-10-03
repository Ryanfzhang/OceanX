"""How a run delivers its figures.

``interactive`` (the default, the desktop's behavior): an Expert publishes a figure through the
Figure API and the desktop opens it. ``static``: the final figure is an ordinary image file the
Expert saves under its own outputs folder, and no plotting interface is described anywhere a model
reads. Benchmark runs use ``static`` so that every arm delivers the same kind of figure.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

FIGURE_DELIVERY_ENV = "OCEANX_FIGURE_DELIVERY"
FIGURE_DELIVERY_MODES = ("interactive", "static")
STATIC_FIGURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".svg", ".pdf"})
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
    with ``_`` or ``.`` is a draft and is skipped, as is anything reached through a symlink.
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
                if (name.startswith(("_", ".")) or path.suffix.lower() not in STATIC_FIGURE_SUFFIXES
                        or path.is_symlink() or not path.is_file()):
                    continue
                yield agent.name, path

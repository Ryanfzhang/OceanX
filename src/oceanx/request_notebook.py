"""One notebook per request: the code every agent ran for it, in order, with what it printed.

Each code run already saves its own executed notebook under its agent's folder
(`.runtime/executions/<id>/code/analysis.ipynb`, see expert_execution.py), and a shell run its
command beside it. When a request ends, these are joined into one `analysis.ipynb`, a section
per agent and a cell per run, which the conversation lists at the end of the answer so a
researcher can read and download the analysis of one query. It holds code, printed output and
the delivered images each run saved (embedded by expert_execution.py), never the data the code read.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARACTERS = 20_000  # a longer printed output keeps its head and tail
MAX_IMAGE_CHARACTERS = 18_000_000  # base64 of all images in one notebook; a result file opens up to 25 MB
NOTEBOOK_NAME = "analysis.ipynb"
NOTEBOOK_ROLE = "analysis_notebook"

# The prefix of an agent folder's key (research/services.py expert_agent_key) and its name.
_AGENT_NAMES = {
    "single-agent": "OceanX",
    "helper": "Helper",
    "ocean-process": "Ocean process Expert",
    "statistics": "Statistics Expert",
    "literature": "Literature Expert",
    "discussion": "Discussion partner",
}


def _agent_name(key: str) -> str:
    prefix = key.rsplit("-", 1)[0] if "-" in key else key
    return _AGENT_NAMES.get(prefix, prefix.replace("-", " ").capitalize())


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _bounded(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARACTERS:
        return text
    half = MAX_OUTPUT_CHARACTERS // 2
    return f"{text[:half]}\n... [{len(text) - MAX_OUTPUT_CHARACTERS} characters left out] ...\n{text[-half:]}"


def _stream_text(output: dict[str, Any]) -> str:
    text = output.get("text", "")
    return "".join(text) if isinstance(text, list) else str(text)


def _outputs(outputs: list[dict[str, Any]], budget: list[int]) -> list[dict[str, Any]]:
    """A run's printed streams and images; an image beyond the notebook's budget is named instead."""

    kept: list[dict[str, Any]] = []
    for output in outputs:
        if output.get("output_type") == "stream":
            kept.append({"name": output.get("name", "stdout"), "output_type": "stream",
                         "text": _lines(_bounded(_stream_text(output)))})
            continue
        data = (output.get("data") or {}) if output.get("output_type") in ("display_data", "execute_result") else {}
        images = {mime: value for mime, value in data.items() if mime.startswith("image/")}
        if not images:
            continue
        label = _stream_text({"text": data.get("text/plain", "an image")})
        size = sum(len(_stream_text({"text": value})) for value in images.values())
        if size > budget[0]:
            kept.append({"name": "stdout", "output_type": "stream",
                         "text": [f"[{label} left out: this notebook holds as many images as it can]\n"]})
            continue
        budget[0] -= size
        kept.append({"output_type": "display_data", "metadata": {}, "data": {**images, "text/plain": [label]}})
    return kept


def _seconds(started: str, ended: str | None) -> float | None:
    try:
        return (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds() if ended else None
    except ValueError:
        return None


def _run_cells(record: Any, agent_root: Path, number: int, budget: list[int]) -> list[dict[str, Any]]:
    """A heading and the code of one run, with what it printed and the images it saved."""

    code_root = agent_root / ".runtime" / "executions" / record.execution_id / "code"
    request = record.request or {}
    command = code_root / "command.sh"
    try:
        executed = json.loads((code_root / NOTEBOOK_NAME).read_text(encoding="utf-8"))
        code_cell = executed["cells"][-1]
        source = "".join(code_cell.get("source", []))
        outputs = list(code_cell.get("outputs", []))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        try:
            source, outputs = (code_root / "analysis.py").read_text(encoding="utf-8"), []
        except OSError:
            source, outputs = None, []
    if command.is_file():  # a shell run: its command, not the wrapper that ran it
        source = "%%bash\n" + command.read_text(encoding="utf-8")
    seconds = _seconds(record.started_at, record.ended_at)
    status = record.state + (f", {seconds:.0f} s" if seconds is not None else "")
    heading = {"cell_type": "markdown", "metadata": {},
               "source": _lines(f"### Run {number}: {request.get('purpose') or 'Code'}\n{status}, started {record.started_at}\n")}
    if source is None:
        heading["source"].append("\nThe code of this run is no longer in the task folder.\n")
        return [heading]
    return [heading, {
        "cell_type": "code", "execution_count": number, "metadata": {},
        "source": _lines(source),
        "outputs": _outputs(outputs, budget),
    }]


def request_notebook(records: Iterable[Any], agent_root, *, request_id: str) -> tuple[bytes, int] | None:
    """The notebook of one request and how many runs it holds; None when no code ran for it.

    ``records`` are the task's code executions; ``agent_root`` maps an agent's key to its folder.
    """

    runs = sorted((record for record in records
                   if (record.request or {}).get("origin_request_id") == request_id),
                  key=lambda record: record.started_at)
    if not runs:
        return None
    by_agent: dict[str, list[Any]] = {}
    for record in runs:
        by_agent.setdefault(record.agent_thread_id, []).append(record)
    cells: list[dict[str, Any]] = [{"cell_type": "markdown", "metadata": {}, "source": _lines(
        "# Analysis notebook\n"
        "The code OceanX ran for this request, a section per agent and a cell per run, with what each "
        "run printed and the figures it saved. Runs of one agent shared its Python session, so a cell can "
        "use what an earlier cell of its section defined. The data the code read are not included.\n")}]
    number, budget = 0, [MAX_IMAGE_CHARACTERS]
    for key, records_of_agent in by_agent.items():
        cells.append({"cell_type": "markdown", "metadata": {},
                      "source": _lines(f"## {_agent_name(key)}\nFolder: agents/{key}\n")})
        for record in records_of_agent:
            number += 1
            cells.extend(_run_cells(record, agent_root(key), number, budget))
    notebook = {
        "cells": cells,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 4,
    }
    return json.dumps(notebook, ensure_ascii=False, indent=1).encode("utf-8"), number


__all__ = ["MAX_IMAGE_CHARACTERS", "MAX_OUTPUT_CHARACTERS", "NOTEBOOK_NAME", "NOTEBOOK_ROLE", "request_notebook"]

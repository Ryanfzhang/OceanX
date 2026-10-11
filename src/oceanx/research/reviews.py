"""A reviewer's notes on a finished task's final answer, for the meta-agent.

OceanX's own reading of a final answer (``referee.py``) is made by the kind of model that did
the work. It finds what an answer left out of the question and where it overstates, but it does
not know what a complete answer to such a question holds. On the first twelve answers it found
nothing missing in depth or breadth, while an outside judge took most points exactly there:
analyses that the answers did not contain and that nothing in the question named (2026-10-11).
A reviewer does know: the owner, a colleague, or a stronger model the owner trusts.

A review is a short list of notes. Each names one aspect of the answer (``referee.ASPECTS``),
says in a sentence or two what the answer lacks, gets wrong or overstates, and says whether
answers to questions of this kind are generally expected to hold it or whether it is particular
to this question. The system's own reading ends with notes of the same form, written by its
model in a reviewer's place (``referee.read_expected``); a project nobody reviews learns from
those alone. The lesson review reads a reviewer's notes with the task's record and weighs them
above the system's own. Nothing in a research task reads them.

Layout under ``<project>/.oceanx/research/reviews/``::

    <task_key>.json   the notes on one task's final answer
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from oceanx.research.memory import ResearchMemory
from oceanx.research.referee import check_notes, note_lines
from oceanx.research.tree_store import atomic_write_text

REVIEW_SCHEMA = "oceanx-answer-review/v1"


def review_lines(review: dict) -> list[str]:
    """One review as the meta-agent sees it in a task record."""
    notes = review.get("notes") or []
    return [f"Reviewer's notes on the final answer ({len(notes)}, by {review.get('reviewer') or 'a reviewer'}):",
            *note_lines(notes)]


class Reviews:
    def __init__(self, memory: ResearchMemory):
        self.memory = memory
        self.root = memory.root / "reviews"

    def all(self) -> dict[str, dict]:
        """Every review the project holds, by task key."""
        found = {}
        for path in sorted(self.root.glob("*.json")) if self.root.is_dir() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("schema") == REVIEW_SCHEMA:
                found[data["task_key"]] = data
        return found

    def record(self, task_key: str, notes, *, reviewer: str) -> dict:
        """Keep a reviewer's notes on one finished task. A later review of the same task
        replaces the earlier one, and the next lesson review reads it."""
        finished = {d["task_key"] for d in self.memory.load_digests() if d.get("finished")}
        if task_key not in finished:
            raise ValueError("No finished task has this key; run consolidate first.")
        if not reviewer.strip():
            raise ValueError("A review names its reviewer.")
        review = {"schema": REVIEW_SCHEMA, "task_key": task_key, "reviewer": reviewer.strip(),
                  "noted_at": datetime.now(UTC).isoformat(), "notes": check_notes(notes)}
        atomic_write_text(self.root / f"{task_key}.json", json.dumps(review, ensure_ascii=False, indent=1))
        return review


__all__ = ["REVIEW_SCHEMA", "Reviews", "review_lines"]

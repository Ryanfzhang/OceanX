"""What someone who knows better than the model that did the work tells the meta-agent: a
critic's outline for a research question, and a reviewer's notes on a finished task's final answer.

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

An outline is the lighter way to say the same, and the one a user would choose: a few sentences
in plain language on what should be done for one research question and how to investigate it.
The critic who writes it is a person, usually the owner, or a stronger model the owner asks. It
holds no result, and the critic need not read any answer. The meta-agent, which stays the model
of the tasks, does the rest: at the next update it compares every finished answer to that
question with the outline (``referee.read_against``), and the lesson review reads the outline
and the points the answers did not do, above everything else in a record. It exists because the
system's own notes, and a reviewer's free notes too, left out three of the four kinds of
analysis an outside judge missed most often in the answers (2026-10-11): a reader of one answer
notes what is wrong in it, not what the work should have been.

Layout under ``<project>/.oceanx/research/reviews/``::

    <task_key>.json                 a reviewer's notes on one task's final answer
    outlines/<question_key>.json    a critic's outline for one research question
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from oceanx.research.memory import ResearchMemory
from oceanx.research.referee import Referee, check_notes, note_lines, question_key
from oceanx.research.tree_store import atomic_write_text

REVIEW_SCHEMA = "oceanx-answer-review/v1"
OUTLINE_SCHEMA = "oceanx-critic-outline/v1"
MAX_OUTLINE_CHARS = 2000  # an outline is brief: what to do and how to investigate, not an answer


def review_lines(review: dict) -> list[str]:
    """One review as the meta-agent sees it in a task record."""
    notes = review.get("notes") or []
    return [f"Reviewer's notes on the final answer ({len(notes)}, by {review.get('reviewer') or 'a reviewer'}):",
            *note_lines(notes)]


class Reviews:
    def __init__(self, memory: ResearchMemory):
        self.memory = memory
        self.root = memory.root / "reviews"

    @staticmethod
    def _kept(folder: Path, schema: str, key: str) -> dict[str, dict]:
        found = {}
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("schema") == schema:
                found[data[key]] = data
        return found

    def all(self) -> dict[str, dict]:
        """Every review the project holds, by task key."""
        return self._kept(self.root, REVIEW_SCHEMA, "task_key")

    def outlines(self) -> dict[str, dict]:
        """Every critic's outline the project holds, by question key."""
        return self._kept(self.root / "outlines", OUTLINE_SCHEMA, "question_key")

    def _finished(self, task_key: str) -> dict:
        digest = next((d for d in self.memory.load_digests()
                       if d.get("finished") and d["task_key"] == task_key), None)
        if digest is None:
            raise ValueError("No finished task has this key; run consolidate first.")
        return digest

    def record(self, task_key: str, notes, *, reviewer: str) -> dict:
        """Keep a reviewer's notes on one finished task. A later review of the same task
        replaces the earlier one, and the next lesson review reads it."""
        self._finished(task_key)
        if not reviewer.strip():
            raise ValueError("A review names its reviewer.")
        review = {"schema": REVIEW_SCHEMA, "task_key": task_key, "reviewer": reviewer.strip(),
                  "noted_at": datetime.now(UTC).isoformat(), "notes": check_notes(notes)}
        atomic_write_text(self.root / f"{task_key}.json", json.dumps(review, ensure_ascii=False, indent=1))
        return review

    def record_outline(self, task_key: str, text: str, *, critic: str) -> dict:
        """Keep a critic's outline for the research question of one finished task: what should
        be done for it and how to investigate it, in plain language. It counts for every task
        on that question, also later ones. A later outline for the question replaces the
        earlier one, and the next update compares the answers with it again."""
        # The question in full, as the readings key it: a digest keeps only its first characters.
        question = Referee(self.memory).question(self._finished(task_key))
        if not question.strip():
            raise ValueError("This task's research question is no longer on record in full; "
                             "name another finished task on the question.")
        if not critic.strip():
            raise ValueError("An outline names its critic.")
        text = "\n".join(line.strip() for line in str(text or "").strip().splitlines())
        if not text or len(text) > MAX_OUTLINE_CHARS:
            raise ValueError(f"An outline is 1-{MAX_OUTLINE_CHARS} characters of plain language; "
                             f"this one has {len(text)}.")
        outline = {"schema": OUTLINE_SCHEMA, "question_key": question_key(question), "question": question,
                   "critic": critic.strip(), "noted_at": datetime.now(UTC).isoformat(), "text": text}
        atomic_write_text(self.root / "outlines" / f"{outline['question_key']}.json",
                          json.dumps(outline, ensure_ascii=False, indent=1))
        return outline


__all__ = ["MAX_OUTLINE_CHARS", "OUTLINE_SCHEMA", "REVIEW_SCHEMA", "Reviews", "review_lines"]

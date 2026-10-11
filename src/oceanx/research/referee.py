"""An independent reading of a finished task's final answer, for the meta-agent.

A research tree records what a task did. It cannot show what the final answer left out or
overstated: the agents that wrote the answer also wrote those records, and an error nobody
caught leaves no trace in them. So after a task finishes, a model that saw none of the work
reads the research question and the final answer, in three calls:

1. from the question alone, the list of what it asks for. The list is kept per question text,
   so every run of a question is read against the same list;
2. the final answer against that list: what is missing or partial, which conclusions are
   stronger than the support the answer itself gives, and which superseded numbers it still
   uses;
3. the final answer as a reviewer of such answers would read it: notes on what a complete
   answer to a question of this kind would also hold, by aspect (``ASPECTS``), each marked
   general or particular to the question. The first two parts say what an answer got wrong
   or left out of its question; this part says what would have made it better research,
   which is what the Coordinator's lessons are learned from. Asked only whether the answer
   "does" each aspect, the same model said yes to 61 of 72 (2026-10-11), so it is asked for
   what is missing instead. A reviewer who knows the field can add notes of the same form
   (``reviews.py``).

A reading is evidence for the lesson review (``lessons.py``), never a rule or a score. In a
hand check of five answers (2026-10-09) about one finding in three was wrong, which is why a
lesson still needs support from tasks on several different questions. The reader sees no
research tree, code or data, and nothing an evaluator holds.

Layout under ``<project>/.oceanx/research/referee/``::

    asked/<question_key>.json   what one question asks for
    <task_key>.json             the reading of one task's final answer
"""
from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oceanx.research.llm import parse_json_object
from oceanx.research.memory import ResearchMemory, task_key
from oceanx.research.tree import nodes
from oceanx.research.tree_store import TreeStore, atomic_write_text

READING_SCHEMA = "oceanx-answer-reading/v1"
STATUSES = ("yes", "partly", "no")
MAX_ASKED = 30  # things one question asks for
MAX_FINDINGS = 8  # conclusions, and superseded numbers, kept per answer
MAX_ANSWER_CHARS = 60_000  # the longest of 34 trial answers had 54,000
MIN_ANSWER_CHARS = 200  # a shorter text is a failed task, not an answer
MAX_NEW_PER_UPDATE = 20  # tasks read in one update, newest first; the rest wait for the next
CALL_SECONDS = 300  # one model call; the slowest of 33 trial calls took 95 s, one never returned
# What a task record shows the meta-agent of one reading (the file keeps all of it).
SHOWN_ASKED, SHOWN_CLAIMS, SHOWN_SUPERSEDED = 6, 5, 3
MAX_NOTES = 16  # notes in one review
MAX_NOTE_CHARS = 400
OWN_NOTES = 10  # notes the system's own reviewer may give on one answer
# What a careful reader asks of a research answer. Each can be judged from the question and the
# answer alone: no data, no code and no reference result.
ASPECTS = {
    "framing": "Is the research question turned into hypotheses that the analysis could have refuted?",
    "results": "Is each headline result given under one stated definition (region, period, depth, "
               "baseline), and do the numbers in the answer agree with each other?",
    "depth": "Is each mechanism the answer names tested in the data by something that could have refuted "
             "it, not only shown to be compatible?",
    "breadth": "Are the results connected to related processes and compared with published values or methods?",
    "robustness": "Do the main conclusions hold under other defensible choices of definition, period or "
                  "region, and are their uncertainties given?",
    "rigor": "Are the data handled in a way that fits the conclusions drawn, and are the limits of those "
             "conclusions stated?",
}

ASKED_PROMPT = """\
You prepare the list an independent reader will check answers to one research question
against. You see only the question.

List what the question asks for: every quantity, breakdown and judgement, and every finding,
threshold, period or definition it names that an answer must use or test. Where the question
says "in each year", "by season", "at which depths" or "for each region", keep that breakdown
inside one item ("the strength of the upwelling, for each year"), not one item per year.
List nothing the question does not ask for, however useful it would be, and no data the
question says are not supplied.

Return JSON only: {{"asked": ["<one thing the question asks for>", ...]}}

Question:
{question}
"""

READING_PROMPT = """\
You read a research answer as someone who saw none of the work behind it. You see only the
question, the numbered list of what it asks for, and the final answer.

1. For each item of the list: does the answer give it? "yes", "partly" or "no"; for "partly"
   and "no", one sentence on what is missing.
   - A quantity is given when the answer states a number for it and how it was defined.
   - A breakdown ("for each year") is given only when the answer states the value for each of
     them. A range, a mean, a ranking of a few of them or a figure alone is "partly".
   - An item the answer shows cannot be decided with the supplied data, and says so, is "yes".
     So is a tested idea the answer reports as not supported.
2. Conclusions stronger than the support the answer itself gives, such as: evidence built from
   the same field as the thing it explains; "no effect" or an excluded cause from a test that
   is not significant, without the effect size the test could have detected; a percentage or
   a "main cause" without a closed budget. Quote the conclusion and say what is missing. Do
   not list a conclusion the answer already states as tentative, bounded or limited.
3. Numbers the answer says were corrected or superseded and still uses in its summary or
   headline results. Quote the stale number and the corrected one. Numbers that differ
   because they follow different stated definitions do not belong here.

Return JSON only:
{{"asked": [{{"item": <number>, "status": "yes" | "partly" | "no", "missing": "<one sentence or empty>"}}],
 "overclaims": [{{"claim": "<quoted>", "why": "<what the support lacks>"}}],
 "superseded": [{{"stale": "<quoted>", "corrected": "<quoted>"}}]}}

Question:
{question}

What it asks for:
{asked}

Final answer:
{answer}
"""

EXPECTED_PROMPT = """\
You review a research answer for a journal, as a specialist in the ocean phenomenon it is about.
You saw none of the work behind it. You see only the question and the final answer: no data, no
code and no reference result.

Judge it against what a complete answer to a question of this kind holds, not against what its
authors chose to do. Name what such an answer would also contain and this one lacks: an
analysis, a comparison, a table, a quantity or a test. Name the thing itself in one or two
sentences, so that someone could carry it out with data of the kind the question supplies.

Each note belongs to one of these aspects:
{aspects}

Give at most {limit} notes, the most valuable first. Give none for an aspect in which a
specialist would miss nothing. Mark a note "general": true when answers to questions of this
kind are generally expected to hold it, and false when it concerns this question only.
Do not ask for data the question says are not supplied. Do not repeat what the answer already
does, or already states as a limit.

Return JSON only:
{{"notes": [{{"aspect": "<name>", "text": "<one or two sentences>", "general": true | false}}]}}

Question:
{question}

Final answer:
{answer}
"""


def _clip(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def question_key(question: str) -> str:
    """One key for a question however it is spaced, cased or punctuated."""
    normal = re.sub(r"[^a-z0-9]+", " ", (question or "").lower()).strip()
    return hashlib.sha256(normal.encode()).hexdigest()[:16]


def _reply(llm: Callable[[str], str], prompt: str) -> str:
    """The model's reply; a ValueError when the call fails or does not come back within
    ``CALL_SECONDS``. The call runs in a thread of its own, so one that never returns is left
    behind instead of holding up the update."""
    box: queue.Queue = queue.Queue(maxsize=1)

    def call() -> None:
        try:
            box.put((True, llm(prompt)))
        except Exception as exc:  # noqa: BLE001 - whatever the model call raises is one failed call
            box.put((False, exc))

    threading.Thread(target=call, daemon=True).start()
    try:
        answered, value = box.get(timeout=CALL_SECONDS)
    except queue.Empty:
        raise ValueError(f"no reply within {CALL_SECONDS} s") from None
    if not answered:
        raise ValueError(f"{type(value).__name__}: {value}")
    return str(value)


def _ask(llm: Callable[[str], str], prompt: str) -> dict:
    """One JSON reply from the model, tried twice."""
    try:
        return parse_json_object(_reply(llm, prompt))
    except ValueError:
        return parse_json_object(_reply(llm, prompt))


def asked_items(question: str, llm: Callable[[str], str]) -> list[str]:
    """What a question asks for, from the question alone."""
    reply = _ask(llm, ASKED_PROMPT.format(question=question))
    items = [_clip(item, 200) for item in reply.get("asked") or [] if isinstance(item, str) and item.strip()]
    if not items:
        raise ValueError("The reader listed nothing the question asks for.")
    return items[:MAX_ASKED]


def read_answer(question: str, asked: list[str], answer: str, llm: Callable[[str], str]) -> dict:
    """One final answer read against what its question asks for."""
    reply = _ask(llm, READING_PROMPT.format(
        question=question, asked="\n".join(f"{i}. {item}" for i, item in enumerate(asked, 1)),
        answer=answer[:MAX_ANSWER_CHARS]))
    judged: dict[int, tuple[str, str]] = {}
    for entry in reply.get("asked") or []:
        try:
            index, status = int(entry["item"]), entry["status"]
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= index <= len(asked) and status in STATUSES:
            judged[index] = (status, "" if status == "yes" else _clip(entry.get("missing"), 200))
    if not judged:
        raise ValueError("The reader judged none of the things the question asks for.")

    def pairs(name: str, first: str, second: str, limit: int) -> list[dict]:
        found = [{first: _clip(entry.get(first), limit), second: _clip(entry.get(second), limit)}
                 for entry in reply.get(name) or [] if isinstance(entry, dict)]
        return [entry for entry in found if entry[first]][:MAX_FINDINGS]

    return {
        # An item the reader passed over is "unread": it says nothing about the answer.
        "asked": [{"item": item, "status": judged.get(i, ("unread", ""))[0],
                   "missing": judged.get(i, ("", ""))[1]} for i, item in enumerate(asked, 1)],
        "overclaims": pairs("overclaims", "claim", "why", 240),
        "superseded": pairs("superseded", "stale", "corrected", 160),
    }


def check_notes(raw) -> list[dict]:
    """A list of notes as it is kept: each with its aspect, its text and whether it is general.
    A ValueError says what is wrong."""
    if isinstance(raw, dict):
        raw = raw.get("notes")
    raw = raw if isinstance(raw, list) else []
    if not raw:
        raise ValueError("A review needs a list of notes.")
    if len(raw) > MAX_NOTES:
        raise ValueError(f"A review has at most {MAX_NOTES} notes; this one has {len(raw)}.")
    notes = []
    for number, entry in enumerate(raw, 1):
        entry = entry if isinstance(entry, dict) else {}
        text = " ".join(str(entry.get("text") or "").split())
        if entry.get("aspect") not in ASPECTS:
            raise ValueError(f"Note {number} needs an aspect: one of {', '.join(ASPECTS)}.")
        if not text or len(text) > MAX_NOTE_CHARS:
            raise ValueError(f"Note {number} needs a text of 1-{MAX_NOTE_CHARS} characters.")
        general = entry.get("general")
        if general is not True and general is not False:
            raise ValueError(f"Note {number} must say whether it is general: true or false.")
        notes.append({"aspect": entry["aspect"], "text": text, "general": general})
    return notes


def note_lines(notes: list[dict]) -> list[str]:
    """Notes as a task record shows them: what is expected of such answers, then the rest."""
    lines = []
    for general, heading in ((True, "expected of answers to such questions"),
                             (False, "particular to this question")):
        chosen = [note for note in notes if note["general"] is general]
        if chosen:
            lines.append(f"  {heading}: " + " | ".join(f"{note['aspect']}: {note['text']}" for note in chosen))
    return lines


def read_expected(question: str, answer: str, llm: Callable[[str], str]) -> list[dict]:
    """One final answer as a reviewer of such answers reads it: what a complete answer would
    also hold. A note the model wrote badly is dropped; an answer may get no note at all."""
    reply = _ask(llm, EXPECTED_PROMPT.format(
        aspects="\n".join(f"{name}: {text}" for name, text in ASPECTS.items()), limit=OWN_NOTES,
        question=question, answer=answer[:MAX_ANSWER_CHARS]))
    if "notes" not in reply:
        raise ValueError("The reviewer returned no list of notes.")
    raw = reply["notes"] if isinstance(reply["notes"], list) else []
    notes = []
    for entry in raw[:OWN_NOTES]:
        try:
            notes += check_notes([{**entry, "text": _clip(entry.get("text"), MAX_NOTE_CHARS)}])
        except (ValueError, TypeError):
            continue
    if raw and not notes:
        raise ValueError("None of the reviewer's notes names an aspect, a text and whether it is general.")
    return notes


def reading_lines(reading: dict) -> list[str]:
    """One reading as the meta-agent sees it in a task record."""
    asked = reading.get("asked") or []
    short = [entry for entry in asked if entry.get("status") in ("partly", "no")]
    claims, stale = reading.get("overclaims") or [], reading.get("superseded") or []

    def listed(entries: list, limit: int, text) -> str:
        more = f" | and {len(entries) - limit} more" if len(entries) > limit else ""
        return " | ".join(text(entry) for entry in entries[:limit]) + more

    lines = [(f"Independent reading of the final answer: of {len(asked)} things the question asks "
              f"for, {len(short)} missing or partial; conclusions stronger than their support: "
              f"{len(claims)}; superseded numbers still used: {len(stale)}.")]
    if short:
        lines.append("  not given: " + listed(short, SHOWN_ASKED, lambda e: (
            f"{_clip(e['item'], 110)} ({e['status']}: {_clip(e.get('missing'), 150)})")))
    if claims:
        lines.append("  stronger than its support: " + listed(claims, SHOWN_CLAIMS, lambda e: (
            f"\"{_clip(e['claim'], 150)}\": {_clip(e.get('why'), 150)}")))
    if stale:
        lines.append("  superseded but still used: " + listed(stale, SHOWN_SUPERSEDED, lambda e: (
            f"\"{_clip(e['stale'], 110)}\", corrected to \"{_clip(e.get('corrected'), 110)}\"")))
    notes = reading.get("expected") or []
    if notes:
        lines.append(f"  the same reader as a reviewer of such answers ({len(notes)} notes):")
        lines += ["  " + line for line in note_lines(notes)]
    return lines


class Referee:
    def __init__(self, memory: ResearchMemory):
        self.memory = memory
        self.root = memory.root / "referee"

    def readings(self) -> dict[str, dict]:
        """Every reading the project holds, by task key."""
        found = {}
        for path in sorted(self.root.glob("*.json")) if self.root.is_dir() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("schema") == READING_SCHEMA:
                found[data["task_key"]] = data
        return found

    def _asked(self, question: str, llm: Callable[[str], str]) -> list[str]:
        path = self.root / "asked" / f"{question_key(question)}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))["asked"]
        except (OSError, json.JSONDecodeError, KeyError):
            asked = asked_items(question, llm)
            atomic_write_text(path, json.dumps({"question": question, "asked": asked},
                                               ensure_ascii=False, indent=1))
            return asked

    @staticmethod
    def _task(store_path: Path) -> tuple[str, str]:
        """A task's research question and final answer: the Coordinator's report while the
        task folder holds it, otherwise the summary kept in the tree."""
        document = TreeStore(Path(store_path)).load() or {}
        root = next((node for node in nodes(document).values() if node.get("parent") is None), {})
        try:
            answer = Path(store_path).with_name("report.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            answer = (root.get("result") or {}).get("summary") or ""
        return root.get("question") or "", answer

    def _keep(self, reading: dict) -> None:
        atomic_write_text(self.root / f"{reading['task_key']}.json",
                          json.dumps(reading, ensure_ascii=False, indent=1))

    def read(self, store_path: Path, llm: Callable[[str], str], *, earlier: dict | None = None) -> dict | None:
        """Read one task's final answer and keep the reading. None when it has no answer.
        ``earlier`` is a reading made before the third part existed: only that part is added.
        The first two parts are kept as soon as they are made, so a third call that fails
        costs only itself and is made again at the next update."""
        question, answer = self._task(store_path)
        if not question.strip() or len(answer.strip()) < MIN_ANSWER_CHARS:
            if earlier is not None:  # its answer is no longer kept: there is nothing to add to
                self._keep({**earlier, "expected": []})
            return None
        reading = earlier or {
            "schema": READING_SCHEMA, "task_key": task_key(store_path), "question_key": question_key(question),
            "read_at": datetime.now(UTC).isoformat(), "answer_chars": len(answer),
            **read_answer(question, self._asked(question, llm), answer, llm)}
        self._keep(reading)
        reading = {**reading, "expected": read_expected(question, answer, llm)}
        self._keep(reading)
        return reading

    def read_new(self, store_paths: list[Path], digests: list[dict], llm: Callable[[str], str]) -> dict:
        """Read the finished tasks whose reading is missing or lacks its third part, newest first.
        A task whose reading fails is left for the next update; nothing else depends on it."""
        finished = {d["task_key"]: d for d in digests if d.get("finished")}
        have = self.readings()
        waiting = [path for path in map(Path, store_paths)
                   if path.is_file() and task_key(path) in finished
                   and "expected" not in have.get(task_key(path), {})]
        waiting.sort(key=lambda path: finished[task_key(path)].get("started_at") or "", reverse=True)
        result = {"read": 0, "completed": 0, "without_answer": 0, "failed": [],
                  "left_for_later": max(len(waiting) - MAX_NEW_PER_UPDATE, 0)}
        for path in waiting[:MAX_NEW_PER_UPDATE]:
            earlier = have.get(task_key(path))
            try:
                reading = self.read(path, llm, earlier=earlier)
            except ValueError as exc:
                result["failed"].append({"task_key": task_key(path), "reason": _clip(exc, 300)})
                continue
            result["without_answer" if reading is None else "completed" if earlier else "read"] += 1
        return result


__all__ = ["ASPECTS", "MAX_NOTES", "MAX_NOTE_CHARS", "READING_SCHEMA", "Referee", "asked_items",
           "check_notes", "note_lines", "question_key", "read_answer", "read_expected", "reading_lines"]

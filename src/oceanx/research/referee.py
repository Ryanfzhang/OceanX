"""An independent reading of a finished task's final answer, for the meta-agent.

A research tree records what a task did. It cannot show what the final answer left out or
overstated: the agents that wrote the answer also wrote those records, and an error nobody
caught leaves no trace in them. So after a task finishes, a model that saw none of the work
reads the research question and the final answer, in two calls:

1. from the question alone, the list of what it asks for. The list is kept per question text,
   so every run of a question is read against the same list;
2. the final answer against that list: what is missing or partial, which conclusions are
   stronger than the support the answer itself gives, and which superseded numbers it still
   uses.

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

    def read(self, store_path: Path, llm: Callable[[str], str]) -> dict | None:
        """Read one task's final answer and keep the reading. None when it has no answer."""
        question, answer = self._task(store_path)
        if not question.strip() or len(answer.strip()) < MIN_ANSWER_CHARS:
            return None
        reading = {"schema": READING_SCHEMA, "task_key": task_key(store_path),
                   "question_key": question_key(question),
                   "read_at": datetime.now(UTC).isoformat(), "answer_chars": len(answer),
                   **read_answer(question, self._asked(question, llm), answer, llm)}
        atomic_write_text(self.root / f"{reading['task_key']}.json",
                          json.dumps(reading, ensure_ascii=False, indent=1))
        return reading

    def read_new(self, store_paths: list[Path], digests: list[dict], llm: Callable[[str], str]) -> dict:
        """Read the finished tasks that have no reading yet, newest first. A task whose reading
        fails is left for the next update; nothing else depends on it."""
        finished = {d["task_key"]: d for d in digests if d.get("finished")}
        have = set(self.readings())
        waiting = [path for path in map(Path, store_paths)
                   if path.is_file() and task_key(path) in finished and task_key(path) not in have]
        waiting.sort(key=lambda path: finished[task_key(path)].get("started_at") or "", reverse=True)
        result = {"read": 0, "without_answer": 0, "failed": [],
                  "left_for_later": max(len(waiting) - MAX_NEW_PER_UPDATE, 0)}
        for path in waiting[:MAX_NEW_PER_UPDATE]:
            try:
                reading = self.read(path, llm)
            except ValueError as exc:
                result["failed"].append({"task_key": task_key(path), "reason": _clip(exc, 300)})
                continue
            result["read" if reading else "without_answer"] += 1
        return result


__all__ = ["READING_SCHEMA", "Referee", "asked_items", "question_key", "read_answer", "reading_lines"]

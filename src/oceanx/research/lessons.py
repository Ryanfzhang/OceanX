"""Lessons learned from past research trees, kept inside the skills a role already reads.

A skill reserves a place for lessons with a marked region (``skill_regions.py``): how many it
may hold and what they are about. The meta-agent maintains the lessons of each such skill. At
every review it reads the skill as its readers get it, and the saved records of finished
tasks, each with an independent reading of its final answer where one exists (``referee.py``);
it judges every current lesson (keep, revise or retire) and may add new ones. Only the
region is rewritten. The rest of the skill, and the packaged files, never change.

What the meta-agent decides takes effect at once. These rules are enforced by code, not by
the model:

* a new lesson needs supporting tasks from at least ``MIN_SUPPORT`` different research
  questions; repeated runs of one question count once;
* a lesson whose counterexamples come from as many questions as its support is retired;
* a skill holds at most as many lessons as its region allows; when it is full, a new lesson
  must be better supported than the weakest one, which it then replaces;
* a lesson is at most ``MAX_WORDS`` words with an explicit "applies when" condition, and
  names no task or node.

The owner can mark any lesson right (it stays, whatever later records say) or wrong (it goes
and is not proposed again). Every change is logged with its reason, and the lessons a task
could read are named in the version recorded on its research-tree events.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oceanx.research.llm import parse_json_object
from oceanx.research.memory import ResearchMemory
from oceanx.research.referee import Referee, reading_lines
from oceanx.research.tree_store import atomic_write_text
from oceanx.skill_regions import Region, fill_regions, find_regions

# Whose task records the meta-agent reads for a skill, and which agents those are.
READERS = {"coordinator": ("coordinator",),
           "expert": ("ocean_process_expert", "statistical_inference_expert")}
# Written above the lessons of a skill, so a reader can tell them from the packaged text.
LEARNED = ("Learned from past OceanX tasks (evidence, not rules; name a lesson's id in your reason "
           "or report when it changes what you do):")
MAX_WORDS = 40
MAX_CONDITION_WORDS = 25
MIN_SUPPORT = 3  # different research questions, not repeated runs of one
MAX_NEW_PER_REVIEW = 2  # per skill
MAX_PROMPT_CHARS = 200_000  # task records in one review prompt (about 50k tokens)
VERDICTS = ("right", "wrong")

REVIEW_INSTRUCTIONS = """\
You are the meta-agent of OceanX, an ocean-science research system. For one research question a
Coordinator grows a research tree: it adds sub-questions, gives each to an Expert, reads the Expert's
result and the follow-up questions the Expert proposes, and decides what to ask next, what to drop
and when to stop. Each Expert analyses the task's data with code and reports a result with its limits.

Below is one skill that {reader} reads, with the lessons it carries now, and the saved records of
finished tasks. You maintain the lessons of this skill. They sit in one marked place of the skill
and you cannot change any other part of it.

This skill takes lessons about: {about}
It holds at most {limit} lessons.

Do two things.

1. Judge every current lesson against the records ("lessons"):
- "keep": the records support it, or say nothing about it;
- "revise": it holds, but the records show its wording or its condition is wrong; give the new
  "text" and "applies_when";
- "retire": the records contradict it, the skill's own text already says it, or it repeats
  another lesson.
For each lesson, name the task keys that newly support it ("supporting") and those that contradict
it ("counter"). A task contradicts a lesson when the lesson's situation arose, the task did what
the lesson says, and that cost effort without changing the answer or led to a wrong result; or
when the task did the opposite and that went well.

2. Propose at most {max_new} new lessons ("add"). Read the skill first. A lesson must add something
the skill does not already say: propose nothing it already says, even in other words, and nothing
the records show already being done. A lesson is worth proposing only when the records show a
contrast: a choice that cost effort without changing the answer, one that went well in some
places and badly in others, or the same kind of gap left in the final answers of several tasks.
Prefer no lesson over a weak one.

{scope}

Do not propose:
- programming advice (reading files, variable names, array shapes, indexing);
- a finding about one task's region, season or process: a lesson must hold for other ocean questions;
- advice that needs data, tools or time the tasks did not have;
- what "Already in place" says, or a lesson the owner marked wrong.

A new lesson has:
- "text": at most {max_words} words: what to do and why. It must stand alone for a reader who has not
  seen these records: no task keys and no node IDs;
- "applies_when": at most {max_condition} words: the situation in which it holds;
- "supporting": keys of the tasks whose records show it. They must cover at least {min_support}
  different task questions (the "Question:" line); repeated runs of one question count once;
- "counter": keys of the tasks whose records contradict it;
- "rationale": what happened in the records, naming task keys and node IDs.

Return JSON only:
{{"lessons": [{{"id": "<id>", "verdict": "keep"|"revise"|"retire", "text": null|"...",
   "applies_when": null|"...", "supporting": ["<task_key>"], "counter": ["<task_key>"],
   "reason": "..."}}],
 "add": [{{"text": "...", "applies_when": "...", "supporting": ["<task_key>"],
   "counter": ["<task_key>"], "rationale": "..."}}]}}
"""

# Per reader: who reads the lessons, what a lesson must be about, and how to read a task record.
REVIEW_SCOPE = {
    "coordinator": ("the Coordinator", """\
These lessons are about research-tree decisions: what to establish first and which questions to run
together, which proposed follow-ups to adopt or drop, when to follow a line deeper and when to
leave it, and when the question is answered well enough to write the final answer.
Judge a decision by what it cost and gained in the records: minutes and tokens, whether the node
changed the conclusion (its label) and is cited, what was asked after a result that could not decide
the question, which follow-ups were dropped, and what the final answer still lacked of what the
question asks for.""", """\
Each task lists its questions in the order the Coordinator created them. An ID shows the parent:
B1.3.2 is under B1.3, and B1 is the task's question. Minutes count from the start of the task.
A task "run with lessons" had lessons in its skills when it ran.
"adopted from B1.3#1" means the question pursues follow-up 1 proposed by B1.3. Under "follow-ups",
"-> B1.3.2" marks a proposal that became that question and "dropped" one that was never pursued.
A label says whether the final conclusion would change without the node; a "rule" label comes from
citations only and is crude."""),
    "expert": ("an Expert", """\
These lessons are about what to watch for in an analysis. Each lesson must name an analysis choice
that changed, weakened or invalidated a result in the records: a baseline, region, period or index
whose choice changed the result; a property of the data product that limits what can be concluded;
a method assumption that did not hold; a test that caught an error, or whose absence let one
through; how a result the data cannot decide was reported; or a conclusion stated more strongly
than the analysis behind it supports.
The evidence is in each node's result and limits, in later questions that had to re-examine an
earlier result, and in the independent reading of the final answer. Each node names the Expert
that analysed it.""", """\
Each task lists the questions its Experts answered, in order. An ID shows the parent: B1.3.2 is under
B1.3. A task "run with lessons" had lessons in its skills when it ran. "found" is the Expert's
result and "limits" the limitations it reported. "why" is the Coordinator's reason for asking, which
often names the earlier result that needed another look.
A label says whether the final conclusion would change without the node; a "rule" label comes from
citations only and is crude."""),
}

# How every reader's records show a referee's reading of the final answer (referee.py).
READING_NOTE = """\
"Independent reading" comes from a model that saw only the research question and the final
answer, none of the work. It lists what the question asks for and the answer does not give,
conclusions stronger than the support the answer states, and superseded numbers the answer
still uses. About one such finding in three is wrong. Use a finding only where the task's own
results bear it out, and build a lesson on a kind of finding that recurs in tasks on different
questions, never on one finding."""


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _wording(text: str, condition: str) -> tuple[str, str]:
    """Normalise whitespace and enforce the word limits of a lesson."""
    text, condition = " ".join((text or "").split()), " ".join((condition or "").split())
    if not text or _words(text) > MAX_WORDS:
        raise ValueError(f"Lesson text must be 1-{MAX_WORDS} words.")
    if not condition or _words(condition) > MAX_CONDITION_WORDS:
        raise ValueError(f"applies_when must be 1-{MAX_CONDITION_WORDS} words.")
    if re.search(r"\bB\d+\.\d", f"{text} {condition}"):
        raise ValueError("A lesson must stand alone: node IDs belong in the rationale.")
    return text, condition


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def cited_lessons(lesson_ids: list[str], texts: list[str]) -> list[str]:
    """The lessons a task named in its reasons or reports. A citation is the agent's own word
    that a lesson changed what it did; it is counted, not trusted as proof."""
    text = "\n".join(texts)
    return [lesson_id for lesson_id in lesson_ids
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(lesson_id)}(?![A-Za-z0-9_])", text)]


class LessonBook:
    def __init__(self, memory: ResearchMemory):
        self.memory = memory
        self.root = memory.root / "lessons"

    # --- skills that take lessons --------------------------------------------------
    @staticmethod
    def regions() -> dict[str, Region]:
        """The lessons region of every packaged skill that has one, by skill name."""
        from oceanx.skills import load_ocean_skill, ocean_skill_metadata
        found = {}
        for skill in ocean_skill_metadata():
            region = find_regions(load_ocean_skill(skill.name)[0]).get("lessons")
            if region is not None:
                found[skill.name] = region
        return found

    @staticmethod
    def reader(skill: str, region: Region) -> str:
        """Whose records the meta-agent reads for this skill: the region says so, otherwise
        the roles that read the skill do."""
        from oceanx.skills import load_ocean_skill
        if region.reader in READERS:
            return region.reader
        roles = load_ocean_skill(skill)[1].roles
        return "expert" if set(roles) & set(READERS["expert"]) else "coordinator"

    # --- registry ----------------------------------------------------------------
    def _registry_path(self) -> Path:
        return self.root / "lessons.json"

    def lessons(self) -> list[dict]:
        path = self._registry_path()
        return json.loads(path.read_text(encoding="utf-8"))["lessons"] if path.is_file() else []

    def active(self, skill: str | None = None) -> list[dict]:
        return [l for l in self.lessons() if l["status"] == "active"
                and (skill is None or l.get("skill") == skill)]

    def _save(self, lessons: list[dict]) -> None:
        atomic_write_text(self._registry_path(),
                      json.dumps({"lessons": lessons}, ensure_ascii=False, indent=2))
        self.render_skills()

    def _log(self, change: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "changes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": _now(), **change}, ensure_ascii=False) + "\n")

    def changes(self, limit: int = 30) -> list[dict]:
        path = self.root / "changes.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        return [json.loads(line) for line in lines[-limit:]]

    def _state(self) -> dict:
        path = self.root / "review_state.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def review_due(self, *, interval_days: int = 1, now: datetime | None = None) -> bool:
        """Whether the meta-agent's periodic review should run: never more than once a day."""
        last = self._state().get("at")
        if not last:
            return True
        return ((now or datetime.now(UTC)) - datetime.fromisoformat(last)).days >= interval_days

    # --- what a skill shows ----------------------------------------------------------
    def _questions(self) -> dict[str, str]:
        return {d["task_key"]: _norm(d.get("question")) for d in self.memory.load_digests()}

    @staticmethod
    def _strength(lesson: dict, questions: dict[str, str]) -> int:
        """Different questions that support a lesson, minus different questions that contradict
        it. A task without a digest (a frozen snapshot has none) counts as its own question."""
        evidence = lesson.get("evidence", {})
        support = {questions.get(k) or k for k in evidence.get("supporting", [])}
        counter = {questions.get(k) or k for k in evidence.get("counter", [])}
        return len(support) - len(counter)

    def shown(self, skill: str, region: Region | None = None) -> list[dict]:
        """The lessons a reader of the skill sees, best first: the owner's choices, then the
        best supported, then the most recently confirmed. Never more than the region allows."""
        region = region or self.regions().get(skill)
        if region is None:
            return []
        questions = self._questions()
        ranked = sorted(self.active(skill), key=lambda l: l.get("updated_at") or l.get("added_at") or "",
                        reverse=True)
        ranked.sort(key=lambda l: (l.get("human") != "right", -self._strength(l, questions)))
        return ranked[:region.limit]

    def shown_ids(self) -> list[str]:
        regions = self.regions()
        return sorted(l["id"] for skill, region in regions.items() for l in self.shown(skill, region))

    def block(self, skill: str, region: Region | None = None) -> str:
        """The text of the skill's lessons region; empty when it has no lesson."""
        lessons = self.shown(skill, region)
        if not lessons:
            return ""
        return "\n".join([LEARNED, *(
            f"- {l['text']} Applies when: {l['applies_when']} ({l['id']})" for l in lessons)])

    def blocks(self) -> dict[str, str]:
        return {skill: self.block(skill, region) for skill, region in self.regions().items()}

    def skill_text(self, skill: str) -> str:
        """A skill with a lessons region as its readers get it."""
        from oceanx.skills import load_ocean_skill
        return fill_regions(load_ocean_skill(skill)[0], {"lessons": self.block(skill)})

    def version(self) -> str | None:
        """Names the lessons a task can read; None when its skills carry none."""
        shown = sorted((skill, block) for skill, block in self.blocks().items() if block)
        if not shown:
            return None
        return "lessons@" + hashlib.sha256(json.dumps(shown).encode()).hexdigest()[:12]

    @property
    def skills_root(self) -> Path:
        return self.root / "skills"

    def render_skills(self) -> None:
        """Export the skills that carry lessons for the owner to read. Tasks do not load these
        files: each task's skill library is built from the packaged skills and the lessons."""
        shutil.rmtree(self.skills_root, ignore_errors=True)
        for skill, block in self.blocks().items():
            if block:
                atomic_write_text(self.skills_root / skill / "SKILL.md", self.skill_text(skill))

    # --- review by the meta-agent ----------------------------------------------------
    def _facts(self, lesson: dict, questions: dict[str, str], digests: list[dict]) -> str:
        evidence = lesson.get("evidence", {})
        support = {questions.get(k) or k for k in evidence.get("supporting", [])}
        counter = {questions.get(k) or k for k in evidence.get("counter", [])}
        shown = sum(lesson["id"] in (d.get("lessons_shown") or []) for d in digests)
        cited = sum(lesson["id"] in (d.get("lessons_cited") or []) for d in digests)
        mark = ", marked right by the owner (it stays; only add evidence)" if lesson.get("human") == "right" else ""
        return (f"- {lesson['id']}: supported by {len(support)} questions, contradicted by "
                f"{len(counter)}; shown in {shown} tasks, cited in {cited}{mark}")

    def review_prompt(self, skill: str, digests: list[dict]) -> tuple[str, int]:
        """The meta-agent's prompt for one skill, and how many task records fit in it."""
        region = self.regions()[skill]
        reader, scope, reading = REVIEW_SCOPE[self.reader(skill, region)]
        # Newest first, but one run of every question before any repeat, because support is
        # counted in questions.
        firsts, repeats, seen = [], [], set()
        for digest in sorted(digests, key=_task_time, reverse=True):
            question = _norm(digest.get("question"))
            (repeats if question in seen else firsts).append(digest)
            seen.add(question)
        readings = Referee(self.memory).readings()
        records, size = [], 0
        for digest in firsts + repeats:
            record = _record(digest, self.reader(skill, region), readings.get(digest["task_key"]))
            if records and size + len(record) > MAX_PROMPT_CHARS:
                break
            records.append(record)
            size += len(record)
        questions = self._questions()
        current = self.active(skill)
        wrong = [l["text"] for l in self.lessons() if l.get("human") == "wrong"]
        prompt = (REVIEW_INSTRUCTIONS.format(
            reader=reader, about=region.about, limit=region.limit, max_new=MAX_NEW_PER_REVIEW,
            scope=scope, max_words=MAX_WORDS, max_condition=MAX_CONDITION_WORDS,
            min_support=MIN_SUPPORT)
            + f'\n# The skill\nIts lessons carry their id, such as (L003).\n\n<skill name="{skill}">\n'
            + _body(self.skill_text(skill)) + "\n</skill>"
            + "\n\n# Its lessons now\n" + ("\n".join(self._facts(l, questions, digests) for l in current)
                                          or "None yet.")
            + "\n\n# Lessons the owner marked wrong\n" + ("\n".join(f"- {text}" for text in wrong) or "None.")
            + "\n\n# Already in place\n" + _in_place(self.reader(skill, region), skill)
            + "\n\n# How to read a record\n" + reading + "\n" + READING_NOTE
            + "\n\n# Records\n" + "\n\n".join(records))
        return prompt, len(records)

    def _evidence(self, raw: dict, digests: dict[str, dict]) -> tuple[list[str], list[str]]:
        supporting = [k for k in dict.fromkeys(raw.get("supporting") or []) if k in digests]
        counter = [k for k in dict.fromkeys(raw.get("counter") or []) if k in digests]
        return supporting, counter

    def _new_lesson(self, raw: dict, skill: str, role: str, digests: dict[str, dict],
                    lessons: list[dict]) -> dict:
        text, condition = _wording(str(raw.get("text") or ""), str(raw.get("applies_when") or ""))
        supporting, counter = self._evidence(raw, digests)
        support_q = {_norm(digests[k].get("question")) for k in supporting}
        counter_q = {_norm(digests[k].get("question")) for k in counter}
        if len(support_q) < MIN_SUPPORT:
            raise ValueError(f"A lesson needs supporting tasks from at least {MIN_SUPPORT} different "
                             f"questions; these come from {len(support_q)}.")
        if len(counter_q) >= len(support_q):
            raise ValueError("Counterexamples must come from fewer questions than the support.")
        for lesson in lessons:
            if _norm(lesson["text"]) == _norm(text) and (
                    lesson["status"] == "active" or lesson.get("human") == "wrong"):
                raise ValueError("The owner marked this lesson wrong." if lesson.get("human") == "wrong"
                                 else "Duplicate of a lesson the skills already carry.")
        return {"id": f"L{len(lessons) + 1:03d}", "skill": skill, "role": role, "text": text,
                "applies_when": condition, "evidence": {"supporting": supporting, "counter": counter},
                "status": "active", "human": None, "added_by": "meta-agent", "added_at": _now()}

    def _retire(self, lesson: dict, *, by: str, reason: str) -> None:
        lesson.update(status="retired", retired_by=by, retired_at=_now(), retired_reason=reason[:600])
        self._log({"lesson": lesson["id"], "skill": lesson.get("skill"), "change": "retired", "by": by,
                   "reason": reason[:600], "text": lesson["text"]})

    def _apply(self, skill: str, region: Region, reply: dict, digests: dict[str, dict],
               lessons: list[dict]) -> tuple[list[dict], list[dict]]:
        """Carry out one skill's review. Returns what changed and what was refused."""
        role, changed, rejected = self.reader(skill, region), [], []
        questions = {k: _norm(d.get("question")) for k, d in digests.items()}
        current = {l["id"]: l for l in lessons if l["status"] == "active" and l.get("skill") == skill}
        for item in reply.get("lessons") or []:
            lesson = current.get(item.get("id")) if isinstance(item, dict) else None
            if lesson is None:
                continue
            supporting, counter = self._evidence(item, digests)
            evidence = lesson.setdefault("evidence", {"supporting": [], "counter": []})
            for side, keys in (("supporting", supporting), ("counter", counter)):
                evidence[side] = list(dict.fromkeys([*evidence.get(side, []), *keys]))
            if supporting or counter:
                lesson["updated_at"] = _now()
            if lesson.get("human") == "right":
                continue  # the owner's mark stands; only the evidence grows
            verdict, reason = item.get("verdict"), str(item.get("reason") or "")
            if verdict == "retire":
                self._retire(lesson, by="meta-agent", reason=reason or "retired at review")
                changed.append({"lesson": lesson["id"], "change": "retired"})
            elif verdict == "revise":
                try:
                    text, condition = _wording(str(item.get("text") or lesson["text"]),
                                               str(item.get("applies_when") or lesson["applies_when"]))
                except ValueError as exc:
                    rejected.append({"skill": skill, "text": str(item.get("text"))[:200], "reason": str(exc)})
                    continue
                if (text, condition) != (lesson["text"], lesson["applies_when"]):
                    self._log({"lesson": lesson["id"], "skill": skill, "change": "revised",
                               "by": "meta-agent", "reason": reason[:600],
                               "before": lesson["text"], "after": text})
                    lesson.update(text=text, applies_when=condition, updated_at=_now())
                    changed.append({"lesson": lesson["id"], "change": "revised"})
        for lesson in current.values():  # what the records say, whatever the model said
            evidence = lesson.get("evidence", {})
            support = {questions.get(k) or k for k in evidence.get("supporting", [])}
            counter = {questions.get(k) or k for k in evidence.get("counter", [])}
            if (lesson["status"] == "active" and lesson.get("human") != "right"
                    and counter and len(counter) >= len(support)):
                self._retire(lesson, by="rule", reason=(
                    f"contradicted: {len(counter)} questions against it, {len(support)} for it"))
                changed.append({"lesson": lesson["id"], "change": "retired"})

        def active() -> list[dict]:
            return [l for l in lessons if l["status"] == "active" and l.get("skill") == skill]

        def weakest() -> dict | None:
            free = [l for l in active() if l.get("human") != "right"]
            return min(free, key=lambda l: (self._strength(l, questions),
                                            l.get("updated_at") or l.get("added_at") or ""),
                       default=None)

        for raw in (reply.get("add") or [])[:MAX_NEW_PER_REVIEW]:
            try:
                lesson = self._new_lesson(raw, skill, role, digests, lessons)
                if len(active()) >= region.limit:
                    loser = weakest()
                    if loser is None or self._strength(lesson, questions) <= self._strength(loser, questions):
                        raise ValueError(f"{skill} already holds {region.limit} lessons and this one is "
                                         "not better supported than its weakest.")
                    self._retire(loser, by="rule", reason=f"replaced by the better supported {lesson['id']}")
                    changed.append({"lesson": loser["id"], "change": "retired"})
            except (ValueError, TypeError, AttributeError) as exc:
                text = raw.get("text", "") if isinstance(raw, dict) else raw
                rejected.append({"skill": skill, "text": str(text)[:200], "reason": str(exc)})
                continue
            lessons.append(lesson)
            self._log({"lesson": lesson["id"], "skill": skill, "change": "added", "by": "meta-agent",
                       "reason": str(raw.get("rationale") or "")[:600], "text": lesson["text"]})
            changed.append({"lesson": lesson["id"], "change": "added"})
        while len(active()) > region.limit and weakest() is not None:  # older data over the limit
            loser = weakest()
            self._retire(loser, by="rule", reason=f"{skill} holds at most {region.limit} lessons")
            changed.append({"lesson": loser["id"], "change": "retired"})
        return changed, rejected

    def review(self, llm: Callable[[str], str], *, task_keys: set[str] | None = None,
               force: bool = False) -> dict:
        """The meta-agent's periodic update: one call per skill that takes lessons."""
        digests = {d["task_key"]: d for d in self.memory.load_digests()
                   if d.get("finished") and (task_keys is None or d["task_key"] in task_keys)}
        questions = len({_norm(d.get("question")) for d in digests.values()})
        result = {"changes": [], "rejected": [], "skills_reviewed": 0, "tasks_considered": 0,
                  "questions": questions, "new_tasks": 0}
        new = set(digests) - set(self._state().get("tasks", []))
        result["new_tasks"] = len(new)
        if not new and not force:
            return result  # nothing happened since the last review
        lessons = self.lessons()
        for skill, region in self.regions().items():
            has_lessons = any(l["status"] == "active" and l.get("skill") == skill for l in lessons)
            if not has_lessons and questions < MIN_SUPPORT:
                continue  # nothing to judge, and no new lesson could pass
            prompt, fitted = self.review_prompt(skill, list(digests.values()))
            result["skills_reviewed"] += 1
            result["tasks_considered"] = max(result["tasks_considered"], fitted)
            try:
                reply = parse_json_object(llm(prompt))
            except ValueError as exc:  # an unreadable reply changes nothing; the other skills go on
                result["rejected"].append({"skill": skill, "text": "",
                                           "reason": f"The meta-agent's reply could not be read: {exc}"})
                continue
            changed, rejected = self._apply(skill, region, reply, digests, lessons)
            result["changes"] += changed
            result["rejected"] += rejected
            self._save(lessons)  # a later skill's prompt sees what this one changed
        atomic_write_text(self.root / "review_state.json",
                          json.dumps({"at": _now(), "tasks": sorted(digests)}))
        return result

    # --- the owner's view --------------------------------------------------------------
    def mark(self, lesson_id: str, verdict: str, *, reviewer: str) -> dict:
        """Right keeps a lesson whatever later records say (and restores a retired one);
        wrong removes it and stops it from being proposed again."""
        if verdict not in VERDICTS:
            raise ValueError("verdict must be right or wrong.")
        lessons = self.lessons()
        lesson = next((l for l in lessons if l["id"] == lesson_id), None)
        if lesson is None:
            raise ValueError("Unknown lesson.")
        who = reviewer.strip() or "owner"
        lesson["human"] = verdict
        if verdict == "wrong":
            if lesson["status"] == "active":
                self._retire(lesson, by=who, reason="marked wrong by the owner")
        else:
            if lesson["status"] != "active":
                if lesson.get("skill") not in self.regions():
                    raise ValueError("Its skill no longer takes lessons.")
                for key in ("retired_by", "retired_at", "retired_reason"):
                    lesson.pop(key, None)
                lesson["status"] = "active"
            lesson["updated_at"] = _now()
            self._log({"lesson": lesson_id, "skill": lesson.get("skill"), "change": "marked right",
                       "by": who, "text": lesson["text"]})
        self._save(lessons)
        return lesson

    def overview(self) -> dict:
        digests = self.memory.load_digests()
        by_key = {d["task_key"]: d for d in digests}
        regions = self.regions()

        def view(lesson: dict, shown: set[str]) -> dict:
            evidence = lesson.get("evidence", {})
            return {**lesson, "shown": lesson["id"] in shown,
                    "tasks_shown": sum(lesson["id"] in (d.get("lessons_shown") or []) for d in digests),
                    "tasks_cited": sum(lesson["id"] in (d.get("lessons_cited") or []) for d in digests),
                    "evidence_tasks": {side: [
                        {"task_key": k, "question": by_key.get(k, {}).get("question", "")}
                        for k in evidence.get(side, [])] for side in ("supporting", "counter")}}

        skills = []
        for skill, region in regions.items():
            shown = {l["id"] for l in self.shown(skill, region)}
            skills.append({"name": skill, "about": region.about, "limit": region.limit,
                           "reader": self.reader(skill, region),
                           "lessons": [view(l, shown) for l in self.active(skill)]})
        retired = [l for l in self.lessons() if l["status"] == "retired"][-20:]
        state = self._state()
        return {"skills": skills, "retired": [view(l, set()) for l in retired],
                "changes": self.changes(),
                "limits": {"max_words": MAX_WORDS, "max_condition_words": MAX_CONDITION_WORDS,
                           "min_support": MIN_SUPPORT},
                "lessons_version": self.version(), "digests": len(digests),
                "last_reviewed_at": state.get("at"),
                "last_consolidated_at": self.memory.state().get("last_consolidated_at")}


def _in_place(role: str, skill: str) -> str:
    """What the reader is told besides this skill, so the meta-agent does not repeat it."""
    from oceanx.runtime import OCEAN_CHILD_BASE_SYSTEM_PROMPT, OCEAN_EXPLORATION_POLICY
    from oceanx.skills import ocean_skill_metadata
    standing = OCEAN_EXPLORATION_POLICY if role == "coordinator" else OCEAN_CHILD_BASE_SYSTEM_PROMPT
    others = {s.name: s.description for reader in READERS[role]
              for s in ocean_skill_metadata(role=reader) if s.name != skill}
    return (standing.strip() + "\nOther skills the same readers have:\n"
            + "\n".join(f"- {name}: {text}" for name, text in sorted(others.items())))


def _body(document: str) -> str:
    """A SKILL.md without its frontmatter."""
    lines = document.splitlines()
    if lines and lines[0].strip() == "---":
        closing = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
        if closing is not None:
            lines = lines[closing + 1:]
    return "\n".join(lines).strip()


def _task_time(digest: dict) -> str:
    return digest.get("started_at") or digest.get("digested_at", "")


def _millions(tokens: int) -> str:
    return f"{tokens / 1e6:.1f}M tokens"


def _label(digest: dict, node_id: str) -> str:
    label = digest.get("labels", {}).get(node_id)
    if not label:
        return "no label"
    source = {"judge": "model judge", "human": "owner"}.get(label.get("source"), "rule")
    return f"{label['label']} ({source})"


def _attempts(node: dict) -> str:
    """How a question's delegations went, in minutes since the task started."""
    runs = node.get("attempts") or []
    if not runs:
        return "ran"  # v1 digests keep no times
    if len(runs) == 1 and runs[0]["end"] is not None:
        return f"ran min {runs[0]['start']}-{runs[0]['end']}"
    return "; ".join(
        f"attempt {i} from min {run['start']} " + ("returned no report" if run["end"] is None
                                                  else f"reported at min {run['end']}")
        for i, run in enumerate(runs, 1))


def _record(digest: dict, role: str, reading: dict | None = None) -> str:
    """One task as the meta-agent reads it: its decisions for the Coordinator skill, its
    analyses for the Expert skill, and for both the referee's reading of its final answer."""
    outline, outcomes = digest.get("outline", {}), digest.get("outcomes", {})
    questions = {n: node for n, node in outline.items() if node.get("parent") is not None}
    proposals = [p for node in outline.values() for p in node.get("proposals") or []]
    version = (digest.get("policy_versions") or ["?"])[-1]
    policy = version.split("/")[-1].split("@")[0] + (
        ", run with lessons" if "+lessons@" in version else ", run without lessons")
    answer = next((n.get("result") for n in outline.values() if n.get("parent") is None), None)
    answered = sum(bool(node.get("result")) for node in questions.values())
    adopted = sum(bool(p["adopted_as"]) for p in proposals)
    header = (f"## Task {digest['task_key']}: policy {policy}, {digest.get('wall_minutes', '?')} "
              f"min, {_millions(int(digest.get('tokens', 0)))}, {answered} questions answered, "
              f"{adopted} of {len(proposals)} proposed follow-ups adopted")
    lines = [header, f"Question: {digest.get('question')}",
             f"Final answer: {answer or 'none recorded'}", *(reading_lines(reading) if reading else [])]
    for node_id, node in questions.items():
        outcome = outcomes.get(node_id, {})
        runs = node.get("attempts") or []
        ran = bool(runs or node.get("result"))
        if role == "expert" and not ran:
            continue  # a question nobody analysed says nothing about analysis
        facts = [node_id]
        if role == "coordinator":
            origin = node.get("origin") or {}
            facts.append("adopted from " + ", ".join(origin.get("refs") or ["a proposal"])
                         if origin.get("type") == "expert-proposal" else "added by the Coordinator")
            facts.append(f"created min {node.get('created_min', '?')}")
            facts.append(_attempts(node) if ran else "never run")
        else:
            facts += [str(node.get("expert") or "expert"), f"{outcome.get('model_calls', 0)} model calls"]
            silent = sum(run["end"] is None for run in runs)
            if silent:
                facts.append(f"{silent} of {len(runs)} attempts returned no report")
        if ran and outcome.get("model_calls"):  # older runs did not attribute every call to its node
            facts.append(_millions(int(outcome.get("input_tokens", 0))
                                   + int(outcome.get("output_tokens", 0))))
        facts.append(str(node.get("status")))
        if ran:
            facts += ["cited in the final answer" if outcome.get("cited_in_final") else "not cited",
                      _label(digest, node_id)]
        lines.append("- " + " | ".join(facts))
        lines.append(f"  asked: {node.get('question')}")
        if node.get("why_it_matters"):
            lines.append(f"  why: {node['why_it_matters']}")
        if node.get("result"):
            lines.append(f"  found: {node['result']}")
        if role == "expert" and node.get("limits"):
            lines.append(f"  limits: {node['limits']}")
        if node.get("close_reason"):
            lines.append(f"  closed because: {node['close_reason']}")
        if role == "coordinator" and node.get("proposals"):
            lines.append("  follow-ups: " + " | ".join(
                f"{i} -> {p['adopted_as']}" if p["adopted_as"] else f"{i} dropped: {p['text']}"
                for i, p in enumerate(node["proposals"], 1)))
    return "\n".join(lines)


__all__ = ["LEARNED", "MAX_WORDS", "MIN_SUPPORT", "READERS", "LessonBook", "cited_lessons"]

"""Human-approved lessons distilled from past research trees, written into the skills a
role already reads.

The meta-agent reads the saved records of finished tasks and the skills it may write into,
and proposes short lessons, each for a named skill and section. Nothing it writes enters a
prompt, and nothing is written until a human approves it. An approved lesson is then written
into that skill, at the end of that section, for every later research task of the project.

* role ``coordinator``: research-tree decisions (the order of questions, which follow-ups
  to adopt, how deep to go, retries, when to stop), written into the Coordinator's planning
  skill;
* role ``expert``: what to watch for in an analysis (definitions, limits of the data, method
  assumptions, checks, reporting an undecidable result), written into the analysis skills.

The packaged skill files are never modified. Each task's skill library is built from them
and the project's approved lessons (``revised_skills``), so two runs of one OceanX version
can differ in lessons alone.

Lessons are deliberately constrained because unreviewed LLM-written guidance has not been
shown to help:

* at most ``MAX_ACTIVE`` active lessons per role, each at most ``MAX_WORDS`` words,
  with an explicit "applies when" condition and one of the role's topics;
* a lesson only adds to a skill; it cannot change or remove the packaged text;
* every lesson cites supporting tasks (and counterexamples) that must exist in the
  project's digests, from at least ``MIN_SUPPORT`` different research questions;
* the meta-agent only proposes (add or retire); a human approves or rejects in the
  desktop or CLI, optionally editing the wording;
* the active set has a content version recorded on every research-tree event, so
  paired runs can tell whether lessons help.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oceanx.research.memory import ResearchMemory
from oceanx.research.llm import parse_json_object
from oceanx.research.tree_store import atomic_write_text

ROLES = ("coordinator", "expert")
# Per role: the agents its lessons are for.
READERS = {"coordinator": ("coordinator",),
           "expert": ("ocean_process_expert", "statistical_inference_expert")}
# Per role: the packaged skills the meta-agent reads and may write approved lessons into.
WRITABLE = {
    "coordinator": ("research-trajectory-planning",),
    "expert": ("ocean-physical-consistency-review", "ocean-analysis-design",
               "ocean-dataset-diagnosis", "hypothesis-experiment-design"),
}
# Per role: topic -> the section a lesson opens in its skill when no existing section fits.
TOPICS = {
    "coordinator": {"order": "Order of questions", "adopt": "Adopting follow-ups",
                    "depth": "How deep to go", "retry": "Retries", "stop": "When to stop",
                    "assign": "Wording and assigning questions"},
    "expert": {"definition": "Definitions and baselines", "data-limit": "Limits of the data",
               "method": "Method assumptions", "check": "Checks", "report": "Reporting"},
}
# Written above the lessons of a section, so a reader can tell them from the packaged text.
LEARNED = "Learned from past OceanX tasks (approved by the project owner; evidence, not rules):"
MAX_ACTIVE = 12
MAX_WORDS = 40
MAX_CONDITION_WORDS = 25
MIN_SUPPORT = 3  # different research questions, not repeated runs of one
MAX_NEW_PER_RUN = 3  # per role
MAX_PROMPT_CHARS = 200_000  # task records in one mining prompt (about 50k tokens)
REVIEW_AFTER_DAYS = 90  # an unreviewed lesson is put back in front of the owner

MINING_INSTRUCTIONS = """\
You are the meta-agent of OceanX, an ocean-science research system. For one research question a
Coordinator grows a research tree: it adds sub-questions, gives each to an Expert, reads the Expert's
result and the follow-up questions the Expert proposes, and decides what to ask next, what to drop
and when to stop. Each Expert analyses the task's data with code and reports a result with its limits.

Below are the skills {reader} reads, and the saved records of finished tasks. Propose at most
{max_new} lessons for {reader}. An approved lesson is written into the skill and section you name,
where {reader} reads it before working.

Read the skills first. A lesson must add something its skill does not already say: propose nothing
a skill already says, even in other words, and nothing the records show already being done. A lesson
is worth proposing only when the records show a contrast: a choice that cost effort without changing
the answer, or one that went well in some places and badly in others. Prefer no lesson over a weak one.

{scope}

Do not propose:
- programming advice (reading files, variable names, array shapes, indexing);
- a finding about one task's region, season or process: a lesson must hold for other ocean questions;
- advice that needs data, tools or time the tasks did not have;
- what "Already in place" or a proposal awaiting review already says.

Each lesson has:
- "topic": one of {topics};
- "skill": the skill it is written into, one of {skills};
- "section": the "## " heading of that skill it belongs under, when the lesson is about that
  section's subject; otherwise null, which opens a section named after its topic;
- "text": at most {max_words} words: what to do and why. It must stand alone for a reader who has not
  seen these records: no task keys and no node IDs;
- "applies_when": at most {max_condition} words: the situation in which it holds;
- "supporting": keys of the tasks whose records show it. They must cover at least {min_support}
  different task questions (the "Question:" line); repeated runs of one question count once;
- "counter": keys of the tasks whose records contradict it;
- "rationale": what happened in the records, naming task keys and node IDs.
You may also propose retiring an existing lesson (kind "retire", with "lesson_id" and "counter") when
later records contradict it. Return JSON only:
{{"proposals": [{{"kind": "add"|"retire", "lesson_id": null|"<id>", "topic": "...", "skill": "...",
  "section": null|"...", "text": "...", "applies_when": "...", "supporting": ["<task_key>"],
  "counter": ["<task_key>"], "rationale": "..."}}]}}
"""

# Per role: who reads the lessons, what a lesson must be about, and how to read a task record.
MINING_SCOPE = {
    "coordinator": ("the Coordinator", """\
These lessons are about research-tree decisions. Each lesson must change one of these decisions:
- order: what to establish first and which questions to run together;
- adopt: which proposed follow-ups to adopt, merge or drop;
- depth: when to follow a line deeper and when to leave it;
- retry: what to do when an Expert returns no report or an unusable one;
- stop: when the question is answered well enough to write the final answer;
- assign: how to word a sub-question, or which Expert to give it to, so that its result is usable.
Judge a decision by what it cost and gained in the records: minutes and tokens, whether the node
changed the conclusion (its label) and is cited, what was asked after a result that could not decide
the question, and which follow-ups were dropped.""", """\
Each task lists its questions in the order the Coordinator created them. An ID shows the parent:
B1.3.2 is under B1.3, and B1 is the task's question. Minutes count from the start of the task.
"adopted from B1.3#1" means the question pursues follow-up 1 proposed by B1.3. Under "follow-ups",
"-> B1.3.2" marks a proposal that became that question and "dropped" one that was never pursued.
A label says whether the final conclusion would change without the node; a "rule" label comes from
citations only and is crude."""),
    "expert": ("an Expert", """\
These lessons are about what to watch for in an analysis. Each lesson must name an analysis choice
that changed, weakened or invalidated a result in the records:
- definition: a baseline, region, period or index that nodes defined differently, or whose choice
  changed the result;
- data-limit: a property of the data product that limits what can be concluded from it;
- method: a method assumption that did not hold;
- check: a test that caught an error, or whose absence let one through;
- report: how to report a result that the data cannot decide.
The evidence is in each node's result and limits, and in later questions that had to re-examine an
earlier result. Each node names the Expert that analysed it; write a lesson into a skill that
Expert reads.""", """\
Each task lists the questions its Experts answered, in order. An ID shows the parent: B1.3.2 is under
B1.3. "found" is the Expert's result and "limits" the limitations it reported. "why" is the
Coordinator's reason for asking, which often names the earlier result that needed another look.
A label says whether the final conclusion would change without the node; a "rule" label comes from
citations only and is crude."""),
}


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _wording(text: str, condition: str) -> tuple[str, str]:
    """Normalise whitespace and enforce the word limits shared by proposals and approvals."""
    text, condition = " ".join((text or "").split()), " ".join((condition or "").split())
    if not text or _words(text) > MAX_WORDS:
        raise ValueError(f"Lesson text must be 1-{MAX_WORDS} words.")
    if not condition or _words(condition) > MAX_CONDITION_WORDS:
        raise ValueError(f"applies_when must be 1-{MAX_CONDITION_WORDS} words.")
    return text, condition


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


class LessonBook:
    def __init__(self, memory: ResearchMemory):
        self.memory = memory
        self.root = memory.root / "lessons"
        self.proposals = memory.root / "proposals" / "lessons"

    # --- registry ----------------------------------------------------------------
    def _registry_path(self) -> Path:
        return self.root / "lessons.json"

    def lessons(self) -> list[dict]:
        path = self._registry_path()
        return json.loads(path.read_text(encoding="utf-8"))["lessons"] if path.is_file() else []

    def active(self, role: str | None = None) -> list[dict]:
        return [l for l in self.lessons() if l["status"] == "active"
                and (role is None or l["role"] == role)]

    def _save(self, lessons: list[dict]) -> None:
        atomic_write_text(self._registry_path(),
                      json.dumps({"lessons": lessons}, ensure_ascii=False, indent=2))
        self.render_skills()

    def version(self) -> str | None:
        active = sorted((l["id"], l["role"], l.get("skill"), l.get("section"), l["text"],
                         l["applies_when"]) for l in self.active())
        if not active:
            return None
        return "lessons@" + hashlib.sha256(json.dumps(active).encode()).hexdigest()[:12]

    @property
    def skills_root(self) -> Path:
        return self.root / "skills"

    def revised_skills(self) -> dict[str, str]:
        """Each skill that has approved lessons, as its readers get it: the packaged SKILL.md
        with those lessons written in."""
        from oceanx.skills import load_ocean_skill
        active, revised = self.active(), {}
        for name in (name for names in WRITABLE.values() for name in names):
            lessons = [l for l in active if l.get("skill") == name]
            if lessons:
                revised[name] = write_lessons(load_ocean_skill(name)[0], lessons)
        return revised

    def render_skills(self) -> None:
        """Export the revised skills for the owner to read. Tasks do not load these files:
        each task's skill library is built from the packaged skills and the approved lessons."""
        from oceanx.skills import validate_ocean_skill_document
        shutil.rmtree(self.skills_root, ignore_errors=True)
        for name, content in self.revised_skills().items():
            validate_ocean_skill_document(content, expected_name=name)
            atomic_write_text(self.skills_root / name / "SKILL.md", content)

    def _skill_text(self, name: str) -> str:
        """A writable skill as its readers currently get it."""
        from oceanx.skills import load_ocean_skill
        return self.revised_skills().get(name) or load_ocean_skill(name)[0]

    # --- proposals ---------------------------------------------------------------
    def pending(self) -> list[dict]:
        return [p for p in self._all_proposals() if p["status"] == "pending"]

    def _all_proposals(self) -> list[dict]:
        if not self.proposals.is_dir():
            return []
        items = [json.loads(p.read_text(encoding="utf-8")) for p in self.proposals.glob("*.json")]
        return sorted(items, key=lambda p: p["created_at"])

    def _proposal_path(self, proposal_id: str) -> Path:
        if not re.fullmatch(r"lp_[a-f0-9]{12}", proposal_id):
            raise ValueError("Unknown lesson proposal.")
        return self.proposals / f"{proposal_id}.json"

    def protected_task_keys(self) -> set[str]:
        keys: set[str] = set()
        for proposal in self.pending():
            keys.update(proposal["evidence"]["supporting"])
            keys.update(proposal["evidence"]["counter"])
        return keys

    def validate_candidate(self, raw: dict, digests: dict[str, dict]) -> dict:
        kind = raw.get("kind", "add")
        if kind not in {"add", "retire"}:
            raise ValueError("kind must be add or retire.")
        supporting = [k for k in dict.fromkeys(raw.get("supporting") or []) if k in digests]
        counter = [k for k in dict.fromkeys(raw.get("counter") or []) if k in digests]
        if kind == "retire":
            lesson = next((l for l in self.active() if l["id"] == raw.get("lesson_id")), None)
            if lesson is None:
                raise ValueError("Retire proposal must name an active lesson.")
            if not counter:
                raise ValueError("Retire proposal needs counterexample tasks from the digests.")
            return {"kind": "retire", "role": lesson["role"], "lesson_id": lesson["id"],
                    "text": lesson["text"], "applies_when": lesson["applies_when"],
                    "evidence": {"supporting": supporting, "counter": counter},
                    "rationale": str(raw.get("rationale") or "")[:600]}
        role = raw.get("role")
        if role not in ROLES:
            raise ValueError("role must be coordinator or expert.")
        if raw.get("topic") not in TOPICS[role]:
            raise ValueError(f"topic must be one of {', '.join(TOPICS[role])}.")
        skill = raw.get("skill")
        if skill not in WRITABLE[role]:
            raise ValueError(f"skill must be one of {', '.join(WRITABLE[role])}.")
        # A lesson goes under a section the skill has, or opens one named after its topic.
        section = TOPICS[role][raw["topic"]]
        wanted = str(raw.get("section") or "").strip()
        if wanted:
            headings = [*_headings(self._skill_text(skill)), section]
            section = next((h for h in headings if _norm(h) == _norm(wanted)), None)
            if section is None:
                raise ValueError(f'"{wanted}" is not a section of {skill}.')
        text, condition = _wording(str(raw.get("text") or ""), str(raw.get("applies_when") or ""))
        if re.search(r"\bB\d+\.\d", f"{text} {condition}"):
            raise ValueError("A lesson must stand alone: node IDs belong in the rationale.")
        questions = {_norm(digests[k].get("question")) for k in supporting}
        if len(questions) < MIN_SUPPORT:
            raise ValueError(f"A lesson needs supporting tasks from at least {MIN_SUPPORT} different "
                             f"questions; these come from {len(questions)}.")
        if len(counter) >= len(supporting):
            raise ValueError("Counterexamples must be fewer than supporting tasks.")
        existing = {_norm(l["text"]) for l in self.active()} | {_norm(p["text"]) for p in self.pending()}
        if _norm(text) in existing:
            raise ValueError("Duplicate of an existing or pending lesson.")
        return {"kind": "add", "role": role, "topic": raw["topic"], "skill": skill,
                "section": section, "lesson_id": None, "text": text, "applies_when": condition,
                "evidence": {"supporting": supporting, "counter": counter},
                "rationale": str(raw.get("rationale") or "")[:600]}

    def add_proposal(self, candidate: dict, *, source: str) -> dict:
        proposal = {**candidate, "id": f"lp_{uuid.uuid4().hex[:12]}", "status": "pending",
                    "source": source, "created_at": datetime.now(UTC).isoformat()}
        atomic_write_text(self._proposal_path(proposal["id"]),
                      json.dumps(proposal, ensure_ascii=False, indent=2))
        return proposal

    def mining_prompt(self, role: str, digests: list[dict]) -> tuple[str, int]:
        """The meta-agent's prompt for one role, and how many task records fit in it."""
        from oceanx.skills import load_ocean_skill
        reader, scope, reading = MINING_SCOPE[role]
        skills = "\n\n".join(
            '<skill name="{}" read_by="{}">\n{}\n</skill>'.format(
                name, ", ".join(r for r in load_ocean_skill(name)[1].roles if r in READERS[role]),
                _body(self._skill_text(name))) for name in WRITABLE[role])
        # Newest first, but one run of every question before any repeat, because support is
        # counted in questions.
        firsts, repeats, seen = [], [], set()
        for digest in sorted(digests, key=_task_time, reverse=True):
            question = _norm(digest.get("question"))
            (repeats if question in seen else firsts).append(digest)
            seen.add(question)
        records, size = [], 0
        for digest in firsts + repeats:
            record = _record(digest, role)
            if records and size + len(record) > MAX_PROMPT_CHARS:
                break
            records.append(record)
            size += len(record)

        waiting = [{key: p.get(key) for key in ("skill", "section", "text", "applies_when")}
                   for p in self.pending() if p["role"] == role and p["kind"] == "add"]
        prompt = (MINING_INSTRUCTIONS.format(
            max_new=MAX_NEW_PER_RUN, reader=reader, scope=scope, topics=" | ".join(TOPICS[role]),
            skills=" | ".join(WRITABLE[role]), max_words=MAX_WORDS,
            max_condition=MAX_CONDITION_WORDS, min_support=MIN_SUPPORT)
            + "\n# Skills you write into\nLessons already written carry their id, such as (L003; ...).\n\n"
            + skills
            + "\n\n# Already in place\n" + _in_place(role)
            + "\n\n# Proposals awaiting review\n" + json.dumps(waiting, ensure_ascii=False)
            + "\n\n# How to read a record\n" + reading
            + "\n\n# Records\n" + "\n\n".join(records))
        return prompt, len(records)

    def mine(self, llm: Callable[[str], str], *, task_keys: set[str] | None = None) -> dict:
        """Ask the meta-agent for lessons for each role's skill; validate every proposal."""
        digests = {d["task_key"]: d for d in self.memory.load_digests()
                   if d.get("finished") and (task_keys is None or d["task_key"] in task_keys)}
        questions = len({_norm(d.get("question")) for d in digests.values()})
        created, rejected, considered = [], [], 0
        # With fewer questions no lesson could pass validation, so the model is not called.
        for role in ROLES if questions >= MIN_SUPPORT else ():
            prompt, fitted = self.mining_prompt(role, list(digests.values()))
            considered = max(considered, fitted)
            raw_items = parse_json_object(llm(prompt)).get("proposals") or []
            for raw in raw_items[:MAX_NEW_PER_RUN]:
                try:
                    candidate = self.validate_candidate({**raw, "role": role}, digests)
                except (ValueError, TypeError) as exc:
                    text = raw.get("text", "") if isinstance(raw, dict) else raw
                    rejected.append({"role": role, "text": str(text)[:200], "reason": str(exc)})
                    continue
                created.append(self.add_proposal(candidate, source="meta-agent"))
        return {"created": created, "rejected": rejected, "tasks_considered": considered,
                "questions": questions}

    # --- human decisions ---------------------------------------------------------
    def decide(self, proposal_id: str, *, approve: bool, reviewer: str,
               text: str | None = None, applies_when: str | None = None,
               reason: str | None = None) -> dict:
        path = self._proposal_path(proposal_id)
        if not path.is_file():
            raise ValueError("Unknown lesson proposal.")
        proposal = json.loads(path.read_text(encoding="utf-8"))
        if proposal["status"] != "pending":
            raise ValueError("This proposal was already decided.")
        if not reviewer.strip():
            raise ValueError("A decision needs a reviewer.")
        decided = {"reviewer": reviewer.strip(), "decided_at": datetime.now(UTC).isoformat(),
                   "decision_reason": (reason or "").strip()[:600]}
        lessons = self.lessons()
        if approve and proposal["kind"] == "add":
            final_text, condition = _wording(
                proposal["text"] if text is None else text,
                proposal["applies_when"] if applies_when is None else applies_when)
            if len(self.active(proposal["role"])) >= MAX_ACTIVE:
                raise ValueError(f"{proposal['role']} already has {MAX_ACTIVE} active lessons; "
                                 "retire one first.")
            lessons.append({"id": f"L{len(lessons) + 1:03d}", "role": proposal["role"],
                            "topic": proposal.get("topic"), "skill": proposal.get("skill"),
                            "section": proposal.get("section"),
                            "text": final_text, "applies_when": condition,
                            "evidence": proposal["evidence"], "status": "active",
                            "approved_by": decided["reviewer"], "approved_at": decided["decided_at"],
                            "source_proposal": proposal_id,
                            "edited": final_text != proposal["text"]
                            or condition != proposal["applies_when"]})
            self._save(lessons)
        elif approve and proposal["kind"] == "retire":
            self._retire(lessons, proposal["lesson_id"], decided, reason or proposal["rationale"])
        elif proposal["kind"] == "retire":  # keeping a lesson restarts its review clock
            for lesson in lessons:
                if lesson["id"] == proposal["lesson_id"]:
                    lesson["reviewed_at"] = decided["decided_at"]
            self._save(lessons)
        proposal.update(status="approved" if approve else "rejected", **decided)
        atomic_write_text(path, json.dumps(proposal, ensure_ascii=False, indent=2))
        return proposal

    def review_stale(self, *, now: datetime | None = None) -> list[dict]:
        """Put lessons not reviewed for ``REVIEW_AFTER_DAYS`` back to the owner as retire proposals."""
        now = now or datetime.now(UTC)
        waiting = {p["lesson_id"] for p in self.pending() if p["kind"] == "retire"}
        created = []
        for lesson in self.active():
            last = datetime.fromisoformat(lesson.get("reviewed_at") or lesson["approved_at"])
            if lesson["id"] not in waiting and (now - last).days >= REVIEW_AFTER_DAYS:
                created.append(self.add_proposal({
                    "kind": "retire", "role": lesson["role"], "lesson_id": lesson["id"],
                    "text": lesson["text"], "applies_when": lesson["applies_when"],
                    "evidence": lesson.get("evidence", {"supporting": [], "counter": []}),
                    "rationale": f"Periodic review: not confirmed for {REVIEW_AFTER_DAYS} days. "
                                 "Reject to keep it, approve to retire it."}, source="review"))
        return created

    def retire(self, lesson_id: str, *, reviewer: str, reason: str) -> None:
        """Direct human retirement from the desktop (no proposal needed)."""
        if not reviewer.strip() or not reason.strip():
            raise ValueError("Retiring a lesson needs a reviewer and a reason.")
        self._retire(self.lessons(), lesson_id,
                     {"reviewer": reviewer.strip(), "decided_at": datetime.now(UTC).isoformat()},
                     reason)

    def _retire(self, lessons: list[dict], lesson_id: str, decided: dict, reason: str) -> None:
        for lesson in lessons:
            if lesson["id"] == lesson_id and lesson["status"] == "active":
                lesson.update(status="retired", retired_by=decided["reviewer"],
                              retired_at=decided["decided_at"], retired_reason=reason[:600])
                self._save(lessons)
                return
        raise ValueError("Unknown or already retired lesson.")

    # --- desktop view ------------------------------------------------------------
    def overview(self) -> dict:
        digests = {d["task_key"]: d for d in self.memory.load_digests()}

        def with_tasks(item: dict) -> dict:
            evidence = item.get("evidence", {})
            return {**item, "evidence_tasks": {
                side: [{"task_key": k, "question": digests.get(k, {}).get("question", "")}
                       for k in evidence.get(side, [])] for side in ("supporting", "counter")}}

        state = self.memory.state()
        return {
            "pending": [with_tasks(p) for p in self.pending()],
            "active": [with_tasks(l) for l in self.active()],
            "retired": [l for l in self.lessons() if l["status"] == "retired"][-20:],
            "limits": {"max_active_per_role": MAX_ACTIVE, "max_words": MAX_WORDS,
                       "max_condition_words": MAX_CONDITION_WORDS, "min_support": MIN_SUPPORT},
            "lessons_version": self.version(),
            "digests": len(digests),
            "last_consolidated_at": state.get("last_consolidated_at"),
        }


def _in_place(role: str) -> str:
    """What the role is told besides the skills above, so the meta-agent does not repeat it."""
    from oceanx.runtime import OCEAN_CHILD_BASE_SYSTEM_PROMPT, OCEAN_EXPLORATION_POLICY
    from oceanx.skills import ocean_skill_metadata
    standing = OCEAN_EXPLORATION_POLICY if role == "coordinator" else OCEAN_CHILD_BASE_SYSTEM_PROMPT
    others = {s.name: s.description for reader in READERS[role]
              for s in ocean_skill_metadata(role=reader) if s.name not in WRITABLE[role]}
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


def _headings(document: str) -> list[str]:
    return [line[3:].strip() for line in document.splitlines() if line.startswith("## ")]


def write_lessons(document: str, lessons: list[dict]) -> str:
    """The skill with each lesson written at the end of its section.

    A section the skill does not have is added at the end. The packaged text is unchanged.
    """
    entries: dict[str, list[str]] = {}
    for lesson in lessons:
        evidence = lesson.get("evidence", {})
        entries.setdefault(lesson.get("section") or "Lessons from past tasks", []).append(
            f"- {lesson['text']} Applies when: {lesson['applies_when']} "
            f"({lesson['id']}; seen in {len(evidence.get('supporting', []))} tasks, "
            f"{len(evidence.get('counter', []))} counterexamples.)")
    out: list[str] = []

    def close(section: str | None) -> None:
        """Write the lessons of the section that just ended, after its packaged text."""
        if section in entries:
            while out and not out[-1].strip():
                out.pop()
            out.extend(["", LEARNED, "", *entries.pop(section), ""])

    section = None
    for line in document.rstrip().splitlines():
        if line.startswith("## "):
            close(section)
            section = line[3:].strip()
        out.append(line)
    close(section)
    for heading, items in entries.items():  # sections the skill does not have yet
        while out and not out[-1].strip():
            out.pop()
        out.extend(["", f"## {heading}", "", LEARNED, "", *items])
    return "\n".join(out).rstrip() + "\n"


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


def _record(digest: dict, role: str) -> str:
    """One task as the meta-agent reads it: its decisions for the Coordinator skill, its
    analyses for the Expert skill."""
    outline, outcomes = digest.get("outline", {}), digest.get("outcomes", {})
    questions = {n: node for n, node in outline.items() if node.get("parent") is not None}
    proposals = [p for node in outline.values() for p in node.get("proposals") or []]
    policy = (digest.get("policy_versions") or ["?"])[-1].split("/")[-1].split("@")[0]
    answer = next((n.get("result") for n in outline.values() if n.get("parent") is None), None)
    answered = sum(bool(node.get("result")) for node in questions.values())
    adopted = sum(bool(p["adopted_as"]) for p in proposals)
    header = (f"## Task {digest['task_key']}: policy {policy}, {digest.get('wall_minutes', '?')} "
              f"min, {_millions(int(digest.get('tokens', 0)))}, {answered} questions answered, "
              f"{adopted} of {len(proposals)} proposed follow-ups adopted")
    lines = [header, f"Question: {digest.get('question')}",
             f"Final answer: {answer or 'none recorded'}"]
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


__all__ = ["LessonBook", "MAX_ACTIVE", "MAX_WORDS", "MIN_SUPPORT", "READERS", "ROLES", "TOPICS",
           "WRITABLE", "write_lessons"]

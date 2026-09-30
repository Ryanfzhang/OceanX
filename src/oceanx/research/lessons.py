"""Human-approved lessons distilled from past research trees.

Lessons are a small amount of plain language. Coordinator lessons are added to the
Coordinator's guidance (next to the policy's guidance text); Expert lessons are a
role-scoped Skill read on demand. They are deliberately constrained because
unreviewed LLM-written guidance has not been shown to help:

* at most ``MAX_ACTIVE`` active lessons per role, each at most ``MAX_WORDS`` words,
  with an explicit "applies when" condition;
* every lesson cites supporting tasks (and counterexamples) that must exist in the
  project's digests; at least ``MIN_SUPPORT`` supporting tasks are required;
* the meta-agent only proposes (add or retire); a human approves or rejects in the
  desktop or CLI, optionally editing the wording;
* the active set has a content version recorded on every research-tree event, so
  paired runs can tell whether lessons help.

Two roles: ``coordinator`` (which branches to explore, deepen or stop) and
``expert`` (method lessons: recurring analysis pitfalls).
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
EXPERT_SKILL = ("method-lessons", ("ocean_process_expert", "statistical_inference_expert"),
                "Short human-approved lessons about recurring analysis pitfalls seen in past "
                "OceanX tasks. Read before choosing an analysis method.")
_PREAMBLE = ("Each lesson is evidence from earlier tasks, not a rule. Ignore a lesson when its "
             "condition does not hold for the current question.")
MAX_ACTIVE = 12
MAX_WORDS = 40
MAX_CONDITION_WORDS = 25
MIN_SUPPORT = 3
MAX_NEW_PER_RUN = 5
MAX_TASKS_IN_PROMPT = 40
REVIEW_AFTER_DAYS = 90  # an unreviewed lesson is put back in front of the owner

MINING_INSTRUCTIONS = """\
You review digests of finished ocean-science research tasks and propose at most {max_new} short
lessons that recur across tasks. Two kinds: role "coordinator" (which research branches to explore,
deepen or stop) and role "expert" (recurring analysis pitfalls; node "code_failures" list repeated
execution errors worth an expert lesson). Each lesson must:
- be at most {max_words} words of plain language, stated as advice with its reason;
- give "applies_when" (at most {max_condition} words) describing when it holds;
- cite at least {min_support} supporting task keys and any counterexample task keys from the digests;
- not duplicate an existing lesson.
You may also propose retiring an existing lesson (kind "retire") when later tasks contradict it.
Prefer no lesson over a weak one. Return JSON only:
{{"proposals": [{{"kind": "add"|"retire", "role": "coordinator"|"expert", "lesson_id": null|"<id>",
  "text": "...", "applies_when": "...", "supporting": ["<task_key>"], "counter": ["<task_key>"],
  "rationale": "..."}}]}}
"""


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
        active = sorted((l["id"], l["role"], l["text"], l["applies_when"]) for l in self.active())
        if not active:
            return None
        return "lessons@" + hashlib.sha256(json.dumps(active).encode()).hexdigest()[:12]

    @property
    def skills_root(self) -> Path:
        return self.root / "skills"

    @staticmethod
    def _numbered(lessons: list[dict]) -> list[str]:
        return [f"{i}. {l['text']} Applies when: {l['applies_when']} "
                f"(seen in {len(l.get('evidence', {}).get('supporting', []))} tasks, "
                f"{len(l.get('evidence', {}).get('counter', []))} counterexamples.)"
                for i, l in enumerate(lessons, 1)]

    def coordinator_guidance(self) -> str:
        """Approved Coordinator lessons, appended to the policy guidance in the prompt."""
        active = self.active("coordinator")
        return "\n".join(["# Lessons from past research (human-approved)", _PREAMBLE,
                          *self._numbered(active)]) if active else ""

    def render_skills(self) -> None:
        """Write the Expert method-lessons SKILL.md (removed when none are active)."""
        from oceanx.skills import validate_ocean_skill_document
        name, agent_roles, description = EXPERT_SKILL
        directory, active = self.skills_root / name, self.active("expert")
        if not active:
            shutil.rmtree(directory, ignore_errors=True)
            return
        lines = ["---", f"name: {name}", f"description: {description}", "metadata:",
                 "  origin: human-approved-lessons", f"  version: {self.version()}", "  roles:",
                 *[f"    - {r}" for r in agent_roles], "---", "",
                 "# Lessons from past OceanX research (human-approved)", "", _PREAMBLE, "",
                 *self._numbered(active)]
        content = "\n".join(lines) + "\n"
        validate_ocean_skill_document(content, expected_name=name)
        atomic_write_text(directory / "SKILL.md", content)

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
        text, condition = _wording(str(raw.get("text") or ""), str(raw.get("applies_when") or ""))
        if len(supporting) < MIN_SUPPORT:
            raise ValueError(f"A lesson needs at least {MIN_SUPPORT} supporting tasks.")
        if len(counter) >= len(supporting):
            raise ValueError("Counterexamples must be fewer than supporting tasks.")
        existing = {_norm(l["text"]) for l in self.active()} | {_norm(p["text"]) for p in self.pending()}
        if _norm(text) in existing:
            raise ValueError("Duplicate of an existing or pending lesson.")
        return {"kind": "add", "role": role, "lesson_id": None, "text": text,
                "applies_when": condition,
                "evidence": {"supporting": supporting, "counter": counter},
                "rationale": str(raw.get("rationale") or "")[:600]}

    def add_proposal(self, candidate: dict, *, source: str) -> dict:
        proposal = {**candidate, "id": f"lp_{uuid.uuid4().hex[:12]}", "status": "pending",
                    "source": source, "created_at": datetime.now(UTC).isoformat()}
        atomic_write_text(self._proposal_path(proposal["id"]),
                      json.dumps(proposal, ensure_ascii=False, indent=2))
        return proposal

    def mine(self, llm: Callable[[str], str], *, task_keys: set[str] | None = None) -> dict:
        """Ask the meta-agent for lesson proposals from digests; validate every one."""
        digests = {d["task_key"]: d for d in self.memory.load_digests()
                   if d.get("finished") and (task_keys is None or d["task_key"] in task_keys)}
        recent = sorted(digests.values(), key=lambda d: d.get("digested_at", ""))[-MAX_TASKS_IN_PROMPT:]
        prompt = (MINING_INSTRUCTIONS.format(max_new=MAX_NEW_PER_RUN, max_words=MAX_WORDS,
                                             max_condition=MAX_CONDITION_WORDS,
                                             min_support=MIN_SUPPORT)
                  + "\nExisting lessons:\n" + json.dumps(
                      [{k: l[k] for k in ("id", "role", "text", "applies_when")} for l in self.active()],
                      ensure_ascii=False)
                  + "\n\nTask digests:\n" + json.dumps([_prompt_digest(d) for d in recent],
                                                        ensure_ascii=False))
        raw_items = parse_json_object(llm(prompt)).get("proposals") or []
        created, rejected = [], []
        for raw in raw_items[:MAX_NEW_PER_RUN]:
            try:
                candidate = self.validate_candidate(raw, digests)
            except (ValueError, TypeError) as exc:
                rejected.append({"text": str(raw.get("text", ""))[:200], "reason": str(exc)})
                continue
            created.append(self.add_proposal(candidate, source="meta-agent"))
        return {"created": created, "rejected": rejected, "tasks_considered": len(recent)}

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


def _prompt_digest(digest: dict) -> dict:
    nodes = []
    for node_id, node in digest.get("outline", {}).items():
        outcome = digest.get("outcomes", {}).get(node_id, {})
        nodes.append({
            "id": node_id, "kind": node.get("kind"), "status": node.get("status"),
            "question": node.get("question"), "result": node.get("result"),
            "verdict": node.get("verdict"), "close_reason": node.get("close_reason"),
            "tokens": int(outcome.get("input_tokens", 0)) + int(outcome.get("output_tokens", 0)),
            "cited": outcome.get("cited_in_final"), "reopened": outcome.get("reopened"),
            "label": (digest.get("labels", {}).get(node_id) or {}).get("label"),
            "code_failures": outcome.get("code_failures") or [],
        })
    return {"task_key": digest["task_key"], "question": digest.get("question"), "nodes": nodes}


__all__ = ["LessonBook", "MAX_ACTIVE", "MAX_WORDS", "MIN_SUPPORT", "ROLES"]

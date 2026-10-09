"""Project research memory: bounded digests, retention and consolidation state.

Layout under ``<project>/.oceanx/research/``::

    digests/<task_key>.json    one small digest per task (what lesson mining reads)
    archive/<task_key>.sqlite3.gz  raw stores past retention (never read by agents)
    lessons/                   lessons, their change log and the rendered skills (lessons.py)
    tools/                     learned helper functions and call counts (toolbook.py)
    referee/                   independent readings of final answers (referee.py)
    state.json                 last consolidation time and counters

Raw per-task stores keep full events and attempts for as long as they are useful;
lesson mining reads only digests, so its input stays bounded. A digest keeps the
outline, the decision history (who proposed each question, when it was created, run
and answered, and what became of the follow-ups it proposed), outcomes and labels,
so archiving a raw store loses no evidence mining needs.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oceanx.research.tree import kind, nodes, summary_field
from oceanx.research.tree_store import TreeStore, atomic_write_text

DIGEST_SCHEMA = "oceanx-research-digest/v2"
# v1 digests lack the decision history. They stay readable and are rebuilt while their raw
# store exists.
READABLE_DIGESTS = {"oceanx-research-digest/v1", DIGEST_SCHEMA}
DEFAULT_RETENTION_DAYS = 30
DEFAULT_INTERVAL_DAYS = 7
MAX_TEXT = 240


def _clip(text: str | None, limit: int = MAX_TEXT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _limits(summary: str) -> str:
    """The limitations an Expert reported, starting where the field first names a limit."""
    text = " ".join(summary_field(summary, "Evidence and limitations").split())
    match = re.search(r"\b[Ll]imit", text)
    return _clip(text[match.start():] if match else text, 500)


def task_key(store_path: Path) -> str:
    return hashlib.sha256(str(Path(store_path).resolve()).encode()).hexdigest()[:16]


def build_digest(store_path: Path) -> dict | None:
    """Summarise one task store into a bounded, agent-free digest."""
    store = TreeStore(Path(store_path))
    document = store.load()
    if document is None:
        return None
    found = nodes(document)
    outcomes = store.outcomes()
    labels, human_labels = store.labels(), store.labels(sources=("human",))
    events, attempts = store.events(), store.attempts()
    began = datetime.fromisoformat(events[0]["ts"]) if events else None

    def minute(ts: str | None) -> float | None:
        """Minutes since the task's first tree event."""
        if not ts or began is None:
            return None
        return round((datetime.fromisoformat(ts) - began).total_seconds() / 60, 1)

    # Per node, every delegation in order: when it started and when it reported. A delegation
    # that returned no report leaves no attempt record, so its "end" stays None.
    created, runs, experts = {}, {}, {}
    for event in events:
        if event["type"] == "created":
            created.setdefault(event["node_id"], event["ts"])
        elif event["type"] == "delegated":
            runs.setdefault(event["node_id"], {})[event["payload"].get("attempt_id")] = {
                "start": minute(event["ts"]), "end": None}
    for attempt in attempts:  # oldest first
        run = runs.setdefault(attempt["node_id"], {}).setdefault(
            attempt["attempt_id"], {"start": minute(attempt["started_at"]), "end": None})
        run["end"] = minute(attempt["ended_at"])
        experts[attempt["node_id"]] = attempt["expert_role"]
    adopted_as = {ref: node_id for node_id, node in found.items()
                  for ref in node["origin"]["refs"] if "#" in ref}
    outline = {}
    for node_id, node in found.items():  # in the order the Coordinator created them
        result = node.get("result") or {}
        summary = result.get("summary", "")
        outline[node_id] = {
            "parent": node.get("parent"), "kind": kind(node), "status": node["status"],
            "relation": node.get("relation"), "question": _clip(node.get("question")),
            "why_it_matters": _clip(node.get("why_it_matters"), 160),
            "origin": node["origin"],
            "expert": experts.get(node_id) or node.get("expert_role"),
            "result": _clip(summary_field(summary, "Result") or summary, 300),
            "limits": _limits(summary),
            # Follow-ups this node proposed; adopted_as is the question that pursued one, else null.
            "proposals": [{"text": _clip(text, 140), "adopted_as": adopted_as.get(f"{node_id}#{i}")}
                          for i, text in enumerate(result.get("proposals") or [], 1)],
            "created_min": minute(created.get(node_id)),
            "attempts": list(runs.get(node_id, {}).values()),
            "verdict": node.get("verdict"),
            "close_reason": _clip(node.get("close_reason"), 160) or None,
        }
    root = next((n for n in outline.values() if n["parent"] is None), {})
    root_id = next((n for n, node in outline.items() if node["parent"] is None), None)
    # What the task ran with and used. None for a task recorded before this was logged, so
    # such a task is not read as "the lessons and tools went unused".
    library = outcomes.get(root_id, {}).get("library") or {}
    return {
        "schema": DIGEST_SCHEMA,
        "task_key": task_key(store_path),
        "source": str(Path(store_path).resolve()),
        "digested_at": datetime.now(UTC).isoformat(),
        "question": root.get("question", ""),
        "policy_versions": sorted({e["policy_version"] for e in events}),
        "started_at": events[0]["ts"] if events else None,
        "wall_minutes": minute(events[-1]["ts"]) if events else None,
        "finished": bool(outcomes),
        "outline": outline,
        "outcomes": outcomes,
        "labels": labels,
        "human_labels": human_labels,
        "event_counts": {t: sum(e["type"] == t for e in events)
                         for t in sorted({e["type"] for e in events})},
        "tokens": sum(int(o.get("input_tokens", 0)) + int(o.get("output_tokens", 0))
                      for o in outcomes.values()),
        "lessons_shown": library.get("lessons_shown"),
        "lessons_cited": library.get("lessons_cited"),
        "tools_mounted": library.get("tools_mounted"),
        "tool_calls": library.get("tool_calls"),
    }


def run_measures(digest: dict) -> dict:
    """Process measures of one finished research tree (improvement data; never shown to a model).

    A question counts as decisive when its effective label is decision-changing. Labels from
    the log rules alone are crude, so judge or human labels should exist before these are read.
    """
    outline, outcomes, labels = digest["outline"], digest.get("outcomes", {}), digest.get("labels", {})
    root = next((n for n, node in outline.items() if node.get("parent") is None), None)
    ran = [n for n, node in outline.items() if n != root and node.get("attempts")]

    def tokens(node_id: str) -> int:
        outcome = outcomes.get(node_id, {})
        return int(outcome.get("input_tokens", 0)) + int(outcome.get("output_tokens", 0))

    labelled = [n for n in ran if n in labels]
    decisive = [n for n in labelled if labels[n]["label"] == "decision-changing"]
    spent = sum(tokens(n) for n in labelled)
    ends = [run["end"] for n in decisive for run in outline[n]["attempts"] if run["end"] is not None]
    proposals = [p for node in outline.values() for p in node.get("proposals", [])]
    attempts = [run for n in ran for run in outline[n]["attempts"]]
    wall = digest.get("wall_minutes")
    expert_skills = [outcomes.get(n, {}).get("skills_read") for n in ran]
    return {
        "questions_run": len(ran),
        "max_depth": max((n.count(".") for n in ran), default=0),
        "tokens": int(digest.get("tokens", 0)),
        "wall_minutes": wall,
        # Share of the labelled questions' tokens spent on questions that did not change the answer.
        "nondecisive_token_share": 1 - sum(tokens(n) for n in decisive) / spent if spent else None,
        "last_decisive_minute": max(ends, default=None),
        "last_decisive_fraction": max(ends) / wall if ends and wall else None,
        "followups_proposed": len(proposals),
        "followups_adopted": sum(bool(p["adopted_as"]) for p in proposals),
        "attempts": len(attempts),
        "attempts_without_report": sum(run["end"] is None for run in attempts),
        "label_sources": {source: sum(labels[n]["source"] == source for n in labelled)
                          for source in sorted({labels[n]["source"] for n in labelled})},
        # None for runs recorded before skill reads were logged.
        "coordinator_skills_read": outcomes.get(root, {}).get("skills_read"),
        "questions_whose_expert_read_a_skill": (
            sum(bool(names) for names in expert_skills) if all(n is not None for n in expert_skills)
            else None),
        "expert_skills_read": sorted({name for names in expert_skills for name in names or []}),
    }


def find_stores(roots) -> list[Path]:
    """Task stores under run or project directories."""
    found: list[Path] = []
    for root in (Path(r).expanduser() for r in roots):
        if root.is_file() and root.name.endswith(".sqlite3"):
            found.append(root)
        elif root.is_dir():
            found.extend(sorted(root.rglob("research_tree.sqlite3")))
    return list(dict.fromkeys(found))


class ResearchMemory:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def digests(self) -> Path:
        return self.root / "digests"

    @property
    def archive(self) -> Path:
        return self.root / "archive"

    # --- state -------------------------------------------------------------------
    def state(self) -> dict:
        path = self.root / "state.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def _write_state(self, state: dict) -> None:
        atomic_write_text(self.root / "state.json", json.dumps(state, indent=2))

    def due(self, *, interval_days: int = DEFAULT_INTERVAL_DAYS, now: datetime | None = None) -> bool:
        last = self.state().get("last_consolidated_at")
        if not last:
            return True
        now = now or datetime.now(UTC)
        return now - datetime.fromisoformat(last) >= timedelta(days=interval_days)

    # --- digests -----------------------------------------------------------------
    def digest(self, store_path: Path) -> dict | None:
        digest = build_digest(store_path)
        if digest is not None:
            atomic_write_text(self.digests / f"{digest['task_key']}.json",
                          json.dumps(digest, ensure_ascii=False, indent=1))
        return digest

    def load_digests(self) -> list[dict]:
        if not self.digests.is_dir():
            return []
        out = []
        for path in sorted(self.digests.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("schema") in READABLE_DIGESTS:
                out.append(data)
        return out

    # --- consolidation -------------------------------------------------------------
    def consolidate(self, store_paths: list[Path], *, retention_days: int = DEFAULT_RETENTION_DAYS,
                    protected_keys: set[str] = frozenset(), now: datetime | None = None) -> dict:
        """Digest new/changed finished stores and archive raw stores past retention.

        Unfinished tasks (no outcomes yet) are digested but never archived. A raw
        store is archived only after a current digest exists, and never when its task
        key is protected (e.g. cited by an open proposal).
        """
        now = now or datetime.now(UTC)
        digested = archived = skipped = 0
        cutoff = now - timedelta(days=retention_days)
        for store_path in store_paths:
            store_path = Path(store_path)
            if not store_path.is_file():
                continue
            key = task_key(store_path)
            digest_path = self.digests / f"{key}.json"
            try:
                digest = json.loads(digest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                digest = None
            if (digest is None or digest.get("schema") != DIGEST_SCHEMA
                    or digest_path.stat().st_mtime < store_path.stat().st_mtime):
                digest = self.digest(store_path)
                digested += digest is not None
            if digest is None or not digest.get("finished") or key in protected_keys:
                skipped += 1
                continue
            modified = datetime.fromtimestamp(store_path.stat().st_mtime, UTC)
            if modified < cutoff:
                self.archive.mkdir(parents=True, exist_ok=True)
                target = self.archive / f"{key}.sqlite3.gz"
                with store_path.open("rb") as source, gzip.open(target, "wb") as sink:
                    shutil.copyfileobj(source, sink)
                store_path.unlink()
                archived += 1
        state = {**self.state(), "last_consolidated_at": now.isoformat(),
                 "digests": len(list(self.digests.glob("*.json"))) if self.digests.is_dir() else 0,
                 "archived_total": self.state().get("archived_total", 0) + archived}
        self._write_state(state)
        return {"digested": digested, "archived": archived, "skipped": skipped,
                "digests": state["digests"], "consolidated_at": state["last_consolidated_at"]}


__all__ = ["DIGEST_SCHEMA", "ResearchMemory", "build_digest", "find_stores", "run_measures",
           "task_key"]

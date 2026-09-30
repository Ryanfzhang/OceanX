"""Project research memory: bounded digests, retention and consolidation state.

Layout under ``<project>/.oceanx/research/``::

    digests/<task_key>.json    one small digest per task (what lesson mining reads)
    archive/<task_key>.sqlite3.gz  raw stores past retention (never read by agents)
    lessons/                   approved lessons + rendered skills (see lessons.py)
    proposals/lessons/         lesson proposals awaiting a human decision
    active_policy              the policy chosen for new tasks in the desktop (optional)
    state.json                 last consolidation time and counters

Raw per-task stores keep full events and attempts for as long as they are useful;
lesson mining reads only digests, so its input stays bounded. A digest keeps the
outline, outcomes and labels, so archiving a raw store loses no evidence it needs.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oceanx.research.tree import kind, nodes
from oceanx.research.tree_store import TreeStore, atomic_write_text

DIGEST_SCHEMA = "oceanx-research-digest/v1"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_INTERVAL_DAYS = 7
MAX_TEXT = 240


def _clip(text: str | None, limit: int = MAX_TEXT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
    events = store.events()
    outline = {}
    for node_id, node in found.items():
        summary = (node.get("result") or {}).get("summary", "")
        outline[node_id] = {
            "parent": node.get("parent"), "kind": kind(node), "status": node["status"],
            "relation": node.get("relation"), "question": _clip(node.get("question")),
            "why_it_matters": _clip(node.get("why_it_matters"), 160),
            "result": _clip(summary), "verdict": node.get("verdict"),
            "close_reason": _clip(node.get("close_reason"), 160) or None,
        }
    root = next((n for n in outline.values() if n["parent"] is None), {})
    return {
        "schema": DIGEST_SCHEMA,
        "task_key": task_key(store_path),
        "source": str(Path(store_path).resolve()),
        "digested_at": datetime.now(UTC).isoformat(),
        "question": root.get("question", ""),
        "policy_versions": sorted({e["policy_version"] for e in events}),
        "finished": bool(outcomes),
        "outline": outline,
        "outcomes": outcomes,
        "labels": labels,
        "human_labels": human_labels,
        "event_counts": {t: sum(e["type"] == t for e in events)
                         for t in sorted({e["type"] for e in events})},
        "tokens": sum(int(o.get("input_tokens", 0)) + int(o.get("output_tokens", 0))
                      for o in outcomes.values()),
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
            if data.get("schema") == DIGEST_SCHEMA:
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
            if not digest_path.is_file() or digest_path.stat().st_mtime < store_path.stat().st_mtime:
                digest = self.digest(store_path)
                digested += digest is not None
            else:
                digest = json.loads(digest_path.read_text(encoding="utf-8"))
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


__all__ = ["DIGEST_SCHEMA", "ResearchMemory", "build_digest", "find_stores", "task_key"]

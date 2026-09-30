"""Canonical SQLite store for one task's research tree and its improvement log.

The tree document, its decision events and delegation attempts are committed in one
SQLite transaction, so they cannot diverge after a crash. ``research_tree.json`` is
only a derived export. Nothing in this module is shown to a model: events and
attempts exist for later analysis of the research policy, not for the Coordinator.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

STORE_SCHEMA = "oceanx-research-tree-store/v1"
POLICY_V0 = "policy/v0-coordinator-bfs"

_DDL = """
CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tree_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL,
    document TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tree_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    revision INTEGER NOT NULL,
    node_id TEXT,
    type TEXT NOT NULL,
    reason TEXT,
    policy_version TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS tree_events_node ON tree_events(node_id);
CREATE TABLE IF NOT EXISTS node_attempts (
    attempt_id TEXT PRIMARY KEY,
    delegation_id TEXT,
    node_id TEXT NOT NULL,
    expert_role TEXT,
    agent_key TEXT NOT NULL,
    summary TEXT NOT NULL,
    report_path TEXT NOT NULL,
    output_refs TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT NOT NULL,
    revision INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS node_attempts_node ON node_attempts(node_id);
CREATE TABLE IF NOT EXISTS node_outcomes (
    node_id TEXT PRIMARY KEY,
    computed_at TEXT NOT NULL,
    outcome TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_labels (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    label TEXT NOT NULL CHECK (label IN (
        'decision-changing', 'informative-but-not-decisive', 'misleading-or-wasteful')),
    note TEXT,
    labeler TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'judge', 'auto')),
    ts TEXT NOT NULL
);
"""

LABELS = ("decision-changing", "informative-but-not-decisive", "misleading-or-wasteful")
# A human label always wins; a model judge beats rules derived from the log.
LABEL_SOURCES = ("human", "judge", "auto")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class TreeEvent:
    type: str
    node_id: str | None
    reason: str | None = None
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NodeAttempt:
    node_id: str
    agent_key: str
    summary: str
    report_path: str
    attempt_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    delegation_id: str | None = None
    expert_role: str | None = None
    output_refs: tuple[str, ...] = ()
    status: str = "returned"
    started_at: str | None = None


class TreeStore:
    """One SQLite file per task, next to the exported JSON tree."""

    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_DDL)
        row = connection.execute(
            "SELECT value FROM store_meta WHERE key = 'schema'").fetchone()
        if row is None:
            connection.execute("INSERT OR IGNORE INTO store_meta VALUES ('schema', ?)",
                               (STORE_SCHEMA,))
        elif row[0] != STORE_SCHEMA:
            raise ValueError(f"Unsupported research tree store schema: {row[0]}.")
        return connection

    @contextmanager
    def _transaction(self):
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def _query(self, sql: str, args: tuple = ()) -> list[tuple]:
        if not self.path.exists():
            return []
        with closing(self._connect()) as connection:
            return connection.execute(sql, args).fetchall()

    @staticmethod
    def _insert_events(connection, events, *, revision: int, policy_version: str, now: str) -> None:
        connection.executemany(
            "INSERT INTO tree_events (ts, revision, node_id, type, reason, policy_version, payload) "
            "VALUES (?,?,?,?,?,?,?)",
            [(now, revision, e.node_id, e.type, e.reason, policy_version,
              json.dumps(e.payload, ensure_ascii=False)) for e in events])

    def load(self) -> dict | None:
        rows = self._query("SELECT document FROM tree_state WHERE id = 1")
        return json.loads(rows[0][0]) if rows else None

    def commit(self, document: dict, *, events=(), attempts=(),
               policy_version: str = POLICY_V0) -> None:
        """Atomically replace the tree and append its events and attempts."""
        revision, now = int(document.get("revision", 0)), _now()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO tree_state (id, revision, document, updated_at) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET revision = excluded.revision, "
                "document = excluded.document, updated_at = excluded.updated_at",
                (revision, json.dumps(document, ensure_ascii=False), now))
            connection.executemany(
                "INSERT INTO node_attempts (attempt_id, delegation_id, node_id, expert_role, "
                "agent_key, summary, report_path, output_refs, status, started_at, ended_at, "
                "revision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(a.attempt_id, a.delegation_id, a.node_id, a.expert_role, a.agent_key, a.summary,
                  a.report_path, json.dumps(list(a.output_refs)), a.status, a.started_at, now,
                  revision) for a in attempts])
            self._insert_events(connection, events, revision=revision,
                                policy_version=policy_version, now=now)

    def append_events(self, events, *, revision: int, policy_version: str = POLICY_V0) -> None:
        """Append events that do not change the tree document (e.g. delegations)."""
        with self._transaction() as connection:
            self._insert_events(connection, events, revision=revision,
                                policy_version=policy_version, now=_now())

    def write_outcomes(self, outcomes: dict[str, dict]) -> None:
        now = _now()
        with self._transaction() as connection:
            connection.executemany(
                "INSERT INTO node_outcomes VALUES (?,?,?) ON CONFLICT(node_id) DO UPDATE "
                "SET computed_at = excluded.computed_at, outcome = excluded.outcome",
                [(n, now, json.dumps(o, ensure_ascii=False)) for n, o in outcomes.items()])

    def outcomes(self) -> dict[str, dict]:
        return {n: json.loads(v) for n, v in
                self._query("SELECT node_id, outcome FROM node_outcomes")}

    def add_label(self, node_id: str, label: str, *, labeler: str, note: str | None = None,
                  source: str = "human") -> None:
        if label not in LABELS:
            raise ValueError(f"Label must be one of {', '.join(LABELS)}.")
        if source not in LABEL_SOURCES or not labeler.strip():
            raise ValueError("A label needs a labeler and a known source.")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO node_labels (node_id, label, note, labeler, ts, source) "
                "VALUES (?,?,?,?,?,?)", (node_id, label, note, labeler.strip(), _now(), source))

    def labels(self, *, sources: tuple[str, ...] = LABEL_SOURCES) -> dict[str, dict]:
        """Effective label per node: latest of the most trusted source present."""
        rows = self._query("SELECT node_id, label, note, labeler, ts, source FROM node_labels "
                           "ORDER BY seq")
        best: dict[str, dict] = {}
        for node_id, label, note, labeler, ts, source in rows:
            if source not in sources:
                continue
            current = best.get(node_id)
            if current is None or LABEL_SOURCES.index(source) <= LABEL_SOURCES.index(current["source"]):
                best[node_id] = {"label": label, "note": note, "labeler": labeler, "ts": ts,
                                 "source": source}
        return best

    def _records(self, table: str, keys: tuple[str, ...], json_key: str, order: str,
                 node_id: str | None) -> list[dict]:
        where = " WHERE node_id = ?" if node_id is not None else ""
        rows = self._query(f"SELECT {', '.join(keys)} FROM {table}{where} ORDER BY {order}",
                           (node_id,) if node_id is not None else ())
        records = [dict(zip(keys, row)) for row in rows]
        for record in records:
            record[json_key] = json.loads(record[json_key])
        return records

    def events(self, node_id: str | None = None) -> list[dict]:
        return self._records("tree_events", ("seq", "ts", "revision", "node_id", "type", "reason",
                                             "policy_version", "payload"), "payload", "seq", node_id)

    def attempts(self, node_id: str | None = None) -> list[dict]:
        return self._records("node_attempts", (
            "attempt_id", "delegation_id", "node_id", "expert_role", "agent_key", "summary",
            "report_path", "output_refs", "status", "started_at", "ended_at", "revision"),
            "output_refs", "ended_at, rowid", node_id)


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a synced temporary file and rename, so readers never see partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False,
                                         prefix=f".{path.name}.") as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


_STATUS_EVENTS = {
    "candidate": "deselected", "selected": "selected",
    "completed": "completed", "failed": "failed",
}


def events_for_changes(changes: list[dict], created: list[str]) -> list[TreeEvent]:
    """Translate one Coordinator decision batch into log events (no model-visible effect)."""
    pending = list(created)
    events: list[TreeEvent] = []
    for change in changes:
        action = change["action"]
        reason = (str(change.get("reason")).strip() or None) if change.get("reason") else None
        if action == "add":
            node_id = pending.pop(0) if pending else None
            events.append(TreeEvent("created", node_id, reason, {
                "parent": None if change["target"] == "ROOT" else change["target"],
                "status": change.get("status"), "relation": change.get("relation"),
                "kind": change.get("kind") or "question",
                "origin_type": "expert-proposal" if change.get("from_proposal")
                else change.get("origin_type") or "coordinator",
                "from_proposal": change.get("from_proposal"),
            }))
            if change.get("status") == "selected" and change.get("kind", "question") == "question":
                # Selecting at creation is still a selection decision.
                events.append(TreeEvent("selected", node_id, reason,
                                        {"status": "selected", "at_creation": True}))
        elif action == "set_status":
            events.append(TreeEvent(_STATUS_EVENTS.get(str(change.get("status")), "status"),
                                    change["target"], reason, {"status": change.get("status")}))
        elif action == "link":
            events.append(TreeEvent("linked", change["target"], reason, {
                "other": change.get("other"), "link_type": change.get("link_type") or "related",
            }))
        elif action == "set_verdict":
            events.append(TreeEvent("verdict", change["target"], reason,
                                    {"verdict": change.get("verdict")}))
        elif action == "decline":
            events.append(TreeEvent("declined", change["target"], reason))
        elif action in {"close", "reopen", "revise", "prune"}:
            events.append(TreeEvent({"close": "closed", "reopen": "reopened",
                                     "revise": "revised", "prune": "pruned"}[action],
                                    change["target"], reason))
    return events


__all__ = ["LABELS", "LABEL_SOURCES", "POLICY_V0", "NodeAttempt", "TreeEvent", "TreeStore", "atomic_write_text",
           "events_for_changes"]

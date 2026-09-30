"""Native OceanX workspace journal, with no historical database migration path."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal
from uuid import uuid4

from oceanx.artifacts.impact import (
    ImpactEdge,
    ImpactNode,
    rebuild_impact,
    would_create_propagating_cycle,
)
from oceanx.artifacts.models import (
    ArtifactFile,
    ArtifactLinkDraft,
    ArtifactManifest,
    ArtifactProjection,
    ArtifactRef,
    ArtifactVersion,
    ClaimContent,
    DecisionContent,
    ExperimentContent,
    HypothesisContent,
    ImpactHop,
    InteractiveViewContent,
    ObservationContent,
    ReportContent,
)
from oceanx.delivery import build_delivery_manifests
from oceanx.protocol.v2.models import (
    EventEnvelope,
    RequestEnvelope,
    canonical_request_fields,
    new_event_id,
    parse_event,
)
from oceanx.storage import ensure_private_directory, ensure_private_file
from oceanx.task_results import TaskResultRef
from oceanx.team.models import CoordinatorResult, WorkFailureCode


class RequestStoreError(RuntimeError):
    """Base error for durable request journal failures."""


class RequestIdConflict(RequestStoreError):
    """A reused request ID has a different semantic request hash."""


class RequestNotFound(RequestStoreError):
    """The requested durable record does not exist."""


class WorkspaceRevisionConflict(RequestStoreError):
    """A mutation was based on an obsolete workspace revision."""

    def __init__(self, current_revision: int) -> None:
        super().__init__(f"Expected workspace revision does not match {current_revision}")
        self.current_revision = current_revision


class ArtifactVersionConflict(RequestStoreError):
    """An immutable artifact ID/version already has different manifest content."""


class ArtifactCommitNotFound(RequestStoreError):
    """A filesystem staging operation has no durable metadata intent."""


class TaskNotFound(RequestStoreError):
    """The requested durable ResearchTask does not exist."""


class TaskRevisionConflict(RequestStoreError):
    """A task-local mutation was based on an obsolete task revision."""

    def __init__(self, current_revision: int) -> None:
        super().__init__(f"Expected task revision does not match {current_revision}")
        self.current_revision = current_revision


TERMINAL_EVENT_TYPES = frozenset({"request.completed", "request.failed", "request.cancelled"})
TERMINAL_REQUEST_STATES = frozenset({"completed", "failed", "cancelled", "interrupted"})
ACTIVE_REQUEST_STATES = frozenset({"accepted", "in_progress"})


@dataclass(frozen=True)
class RequestRecord:
    request_id: str
    request_type: str
    canonical_hash: str
    canonical_request: dict[str, Any]
    principal: str
    session_id: str | None
    workspace_id: str | None
    task_id: str | None
    state: str
    terminal_event: EventEnvelope | None
    created_at: str
    updated_at: str

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_REQUEST_STATES


@dataclass(frozen=True)
class RequestReservation:
    record: RequestRecord
    created: bool


ResearchTaskState = Literal["active", "completed", "archived"]
TaskWorkflowState = Literal[
    "planning",
    "working",
    "completed",
    "incomplete",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class ResearchTaskRecord:
    task_id: str
    workspace_id: str
    title: str
    status: ResearchTaskState
    task_revision: int
    active_request_id: str | None
    created_at: str
    updated_at: str

    def as_summary(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "status": self.status,
            "task_revision": self.task_revision,
            "active_request_id": self.active_request_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class TaskArtifactRecord:
    """One immutable artifact attached to a user-visible research task."""

    artifact: ArtifactVersion
    relations: tuple[str, ...]
    origin_request_ids: tuple[str, ...]
    linked_at: str


@dataclass(frozen=True)
class TaskWorkflowRecord:
    """Durable state for one Coordinator-owned task request."""

    request_id: str
    task_id: str
    workspace_id: str
    state: TaskWorkflowState
    activity: str
    heartbeat_at: str
    failure_fingerprint: str | None
    repeated_failures: int
    created_at: str
    updated_at: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "state": self.state,
            "activity": self.activity,
            "heartbeat_at": self.heartbeat_at,
            "failure_fingerprint": self.failure_fingerprint,
            "repeated_failures": self.repeated_failures,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class TaskTranscriptItem:
    item_id: str
    task_id: str
    sequence: int
    role: Literal["user", "assistant", "tool", "system"]
    text: str
    request_id: str | None
    turn_id: str | None
    tool_call_id: str | None
    interrupted: bool
    created_at: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "sequence": self.sequence,
            "role": self.role,
            "text": self.text,
            "request_id": self.request_id,
            "turn_id": self.turn_id,
            "tool_call_id": self.tool_call_id,
            "interrupted": self.interrupted,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PendingInteractionRecord:
    interaction_id: str
    request_id: str
    task_id: str | None
    workspace_id: str
    session_id: str
    principal: str
    kind: Literal["question", "permission", "paper_selection"]
    question: str
    options: tuple[dict[str, Any], ...]
    state: Literal["pending", "answered", "interrupted"]
    created_at: str
    resolved_at: str | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "kind": self.kind,
            "question": self.question,
            "options": list(self.options),
            "state": self.state,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchTaskSnapshot:
    task: ResearchTaskRecord
    transcript: tuple[TaskTranscriptItem, ...]
    next_transcript_cursor: int | None
    sources: tuple[dict[str, Any], ...]
    outputs: tuple[dict[str, Any], ...]
    delivery_manifests: tuple[dict[str, Any], ...]
    interactions: tuple[PendingInteractionRecord, ...]
    workflow: TaskWorkflowRecord | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "task": self.task.as_summary(),
            "transcript": [item.as_payload() for item in self.transcript],
            "next_transcript_cursor": self.next_transcript_cursor,
            "sources": list(self.sources),
            "outputs": list(self.outputs),
            "delivery_manifests": list(self.delivery_manifests),
            "interactions": [item.as_payload() for item in self.interactions],
            "workflow": self.workflow.as_payload() if self.workflow is not None else None,
        }


@dataclass(frozen=True)
class WorkspaceSnapshot:
    workspace_id: str
    path: str | None
    revision: int
    artifacts: list[dict[str, Any]]
    active_refs: dict[str, ArtifactRef] = field(default_factory=dict)
    disclosure_policy: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "path": self.path,
            "revision": self.revision,
            "artifacts": self.artifacts,
            "active_refs": {
                slot: ref.model_dump(mode="json") for slot, ref in sorted(self.active_refs.items())
            },
            "disclosure_policy": self.disclosure_policy,
        }


@dataclass(frozen=True)
class WorkspaceOpenCommit:
    snapshot: WorkspaceSnapshot
    previous_revision: int
    change: str | None
    changed_event: EventEnvelope | None
    terminal_event: EventEnvelope


@dataclass(frozen=True)
class ActiveRefCommit:
    """One active-pointer mutation with its durable domain and terminal events."""

    snapshot: WorkspaceSnapshot
    previous_revision: int
    domain_event: EventEnvelope
    terminal_event: EventEnvelope


@dataclass(frozen=True)
class CodeExecutionRecord:
    """One immutable audit record for code run by an Expert session."""

    execution_id: str
    workspace_id: str
    task_id: str
    agent_thread_id: str
    server_run_id: str
    state: str
    request: dict[str, Any]
    result: dict[str, Any] | None
    started_at: str
    ended_at: str | None


@dataclass(frozen=True)
class DisclosurePolicyCommit:
    policy: dict[str, Any]
    previous_revision: int
    workspace_revision: int
    domain_event: EventEnvelope
    terminal_event: EventEnvelope


@dataclass(frozen=True)
class CancellationCommit:
    target: RequestRecord
    target_terminal_event: EventEnvelope | None
    terminal_event: EventEnvelope


@dataclass(frozen=True)
class ArtifactCommitIntent:
    operation_id: str
    request_id: str | None
    # ``request_id`` owns a standalone request terminal. ``origin_request_id``
    # only correlates a domain mutation performed inside a long-lived agent request.
    origin_request_id: str | None
    task_id: str | None
    task_relation: str | None
    workspace_id: str
    artifact_id: str
    version: int
    expected_workspace_revision: int | None
    staging_uri: str
    target_uri: str
    manifest: ArtifactManifest
    status: str
    quarantine_uri: str | None
    committed_event_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ArtifactCommit:
    artifact: ArtifactVersion
    projection: ArtifactProjection
    previous_revision: int
    workspace_revision: int
    domain_event: EventEnvelope
    terminal_event: EventEnvelope | None


@dataclass(frozen=True)
class ToolCallRecord:
    """Durable model-tool correlation and final replay result, if available."""

    operation_id: str
    request_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    state: str
    result: dict[str, Any] | None
    created_at: str
    completed_at: str | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _state_for_terminal_event(event: EventEnvelope) -> str:
    if event.type == "request.completed":
        return "completed"
    if event.type == "request.cancelled":
        return "cancelled"
    if event.type == "request.failed":
        error = event.payload.error
        return "interrupted" if error.code == "request_interrupted" else "failed"
    raise RequestStoreError(f"Event is not request-terminal: {event.type}")


class RequestStore:
    """SQLite-backed idempotency journal with atomic event persistence."""

    def __init__(self, database_path: Path) -> None:
        self.path = database_path
        ensure_private_directory(self.path.parent)
        ensure_private_file(self.path)
        self._connection = sqlite3.connect(
            str(database_path),
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        try:
            self._initialize()
        except BaseException:
            self._connection.close()
            raise

    def _initialize(self) -> None:
        """Create native storage, or open exactly this storage contract. Never migrate."""
        tables = {row[0] for row in self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        if tables:
            versions = ([row[0] for row in self._connection.execute("SELECT version FROM storage_contract")]
                        if "storage_contract" in tables else [])
            if versions != ["oceanx-agent-server/v3"]:
                raise RequestStoreError("Unsupported legacy database. Use a new OceanX state directory; old tasks are not imported.")
        else:
            self._connection.executescript("BEGIN IMMEDIATE;\n" + Path(__file__).with_name("schema.sql").read_text(encoding="utf-8") + "\nCOMMIT;")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._enforce_sqlite_private_files()


    def record_model_call(self, record: dict[str, Any]) -> None:
        """Meter calls, including summaries; never persist prompts or credentials."""
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO model_call_observations VALUES (?, ?, ?, ?) "
                "ON CONFLICT(call_id) DO UPDATE SET record_json=excluded.record_json",
                (record["call_id"], record.get("request_id"), record["thread_id"], _canonical_json(record)),
            )

    def list_model_calls(self, request_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT record_json FROM model_call_observations WHERE request_id=? ORDER BY rowid",
                (request_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


    def close(self) -> None:
        with self._lock:
            self._enforce_sqlite_private_files()
            self._connection.close()



    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")
                self._enforce_sqlite_private_files()

    def _enforce_sqlite_private_files(self) -> None:
        """Keep SQLite's WAL sidecars under the same local-only policy as the DB."""

        ensure_private_file(self.path)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.path}{suffix}")
            if sidecar.exists():
                ensure_private_file(sidecar)

    @staticmethod
    def canonical_hash(request: RequestEnvelope) -> tuple[str, dict[str, Any]]:
        canonical = canonical_request_fields(request)
        digest = hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()
        return digest, canonical

    def reserve(self, request: RequestEnvelope, *, principal: str) -> RequestReservation:
        """Persist a request identity before emitting ``request.accepted``."""

        canonical_hash, canonical = self.canonical_hash(request)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM request_records WHERE request_id = ?", (request.request_id,)
            ).fetchone()
            if existing is not None:
                record = self._request_from_row(existing)
                if record.canonical_hash != canonical_hash:
                    raise RequestIdConflict(
                        f"Request ID already has a different payload: {request.request_id}"
                    )
                return RequestReservation(record=record, created=False)
            now = _utc_now()
            context = request.context
            connection.execute(
                """
                INSERT INTO request_records (
                    request_id, request_type, canonical_hash, canonical_request_json,
                    principal, session_id, workspace_id, task_id, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'accepted', ?, ?)
                """,
                (
                    request.request_id,
                    request.type,
                    canonical_hash,
                    _canonical_json(canonical),
                    principal,
                    context.session_id if context else None,
                    context.workspace_id if context else None,
                    context.task_id if context else None,
                    now,
                    now,
                ),
            )
            record = self._request_from_row(
                connection.execute(
                    "SELECT * FROM request_records WHERE request_id = ?", (request.request_id,)
                ).fetchone()
            )
            return RequestReservation(record=record, created=True)

    def mark_in_progress(self, request_id: str) -> RequestRecord:
        """Move a freshly accepted request into the durable active state."""

        with self._transaction() as connection:
            row = self._require_request_row(connection, request_id)
            record = self._request_from_row(row)
            if record.terminal:
                return record
            connection.execute(
                "UPDATE request_records SET state = 'in_progress', updated_at = ? WHERE request_id = ?",
                (_utc_now(), request_id),
            )
            return self._request_from_row(self._require_request_row(connection, request_id))

    def get_request(self, request_id: str) -> RequestRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM request_records WHERE request_id = ?", (request_id,)
            ).fetchone()
            return self._request_from_row(row) if row is not None else None

    def get_event(self, event_id: str) -> EventEnvelope | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT event_json FROM event_records WHERE event_id = ?", (event_id,)
            ).fetchone()
            return parse_event(json.loads(row["event_json"])) if row is not None else None

    def record_domain_event(self, event: EventEnvelope) -> None:
        """Persist an already-committed domain state notification exactly once before broadcast."""

        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT 1 FROM event_records WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if existing is None:
                self._persist_event(connection, event)

    def commit_terminal(self, request_id: str, event: EventEnvelope) -> RequestRecord:
        """Persist a terminal result and its event before any broadcast occurs."""

        if event.type not in TERMINAL_EVENT_TYPES:
            raise RequestStoreError(f"Cannot commit non-terminal event {event.type}")
        if event.request_id != request_id:
            raise RequestStoreError("Terminal event request ID does not match the durable request")
        with self._transaction() as connection:
            record = self._request_from_row(self._require_request_row(connection, request_id))
            if record.terminal:
                if record.terminal_event is not None:
                    return record
                raise RequestStoreError(f"Terminal request has no terminal event: {request_id}")
            self._close_active_tool_calls_in_transaction(
                connection,
                request_id=request_id,
                terminal_event_type=event.type,
            )
            self._persist_event(connection, event)
            connection.execute(
                """
                UPDATE request_records
                SET state = ?, terminal_event_json = ?, terminal_event_id = ?, updated_at = ?
                WHERE request_id = ?
                """,
                (
                    _state_for_terminal_event(event),
                    event.model_dump_json(),
                    event.event_id,
                    _utc_now(),
                    request_id,
                ),
            )
            return self._request_from_row(self._require_request_row(connection, request_id))

    def commit_session_open(
        self,
        *,
        request_id: str,
        session_id: str,
        principal: str,
        workspace_id: str | None,
        terminal_event: EventEnvelope,
    ) -> RequestRecord:
        """Open/refresh a session and commit its request terminal in one transaction."""

        with self._transaction() as connection:
            self._ensure_nonterminal_request(connection, request_id)
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO session_records (session_id, principal, workspace_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    principal = excluded.principal,
                    workspace_id = excluded.workspace_id,
                    updated_at = excluded.updated_at
                """,
                (session_id, principal, workspace_id, now, now),
            )
            self._commit_terminal_in_transaction(connection, request_id, terminal_event)
            return self._request_from_row(self._require_request_row(connection, request_id))

    def commit_workspace_open(
        self,
        *,
        request_id: str,
        workspace_id: str,
        path: str,
        expected_revision: int | None,
        event_factory: Callable[
            [WorkspaceSnapshot, int, str | None], tuple[EventEnvelope | None, EventEnvelope]
        ],
    ) -> WorkspaceOpenCommit:
        """Atomically mutate workspace state, domain event, and request terminal."""

        with self._transaction() as connection:
            self._ensure_nonterminal_request(connection, request_id)
            existing = connection.execute(
                "SELECT * FROM workspace_records WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            previous_revision = int(existing["revision"]) if existing is not None else 0
            if expected_revision is not None and expected_revision != previous_revision:
                raise WorkspaceRevisionConflict(previous_revision)
            change: str | None
            if existing is None:
                revision = 1
                change = "opened"
                connection.execute(
                    """
                    INSERT INTO workspace_records (workspace_id, path, revision, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (workspace_id, path, revision, _utc_now()),
                )
            elif existing["path"] != path:
                revision = previous_revision + 1
                change = "updated"
                connection.execute(
                    """
                    UPDATE workspace_records SET path = ?, revision = ?, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (path, revision, _utc_now(), workspace_id),
                )
            else:
                revision = previous_revision
                change = None
            snapshot = WorkspaceSnapshot(
                workspace_id=workspace_id,
                path=path,
                revision=revision,
                artifacts=self.list_artifact_summaries(workspace_id),
                active_refs=self.list_active_refs(workspace_id),
                disclosure_policy=self._disclosure_policy_summary_in_connection(
                    connection, workspace_id
                ),
            )
            changed_event, terminal_event = event_factory(snapshot, previous_revision, change)
            if changed_event is not None:
                self._persist_event(connection, changed_event)
            self._commit_terminal_in_transaction(connection, request_id, terminal_event)
            return WorkspaceOpenCommit(
                snapshot=snapshot,
                previous_revision=previous_revision,
                change=change,
                changed_event=changed_event,
                terminal_event=terminal_event,
            )

    def workspace_snapshot(self, workspace_id: str) -> WorkspaceSnapshot:
        """Read a complete replaceable workspace snapshot from authoritative projections."""

        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM workspace_records WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if row is None:
                return WorkspaceSnapshot(
                    workspace_id=workspace_id,
                    path=None,
                    revision=0,
                    artifacts=[],
                )
            return WorkspaceSnapshot(
                workspace_id=workspace_id,
                path=row["path"],
                revision=int(row["revision"]),
                artifacts=self.list_artifact_summaries(workspace_id),
                active_refs=self.list_active_refs(workspace_id),
                disclosure_policy=self._disclosure_policy_summary_in_connection(
                    self._connection, workspace_id
                ),
            )

    def create_research_task(
        self,
        *,
        workspace_id: str,
        title: str,
        task_id: str | None = None,
    ) -> ResearchTaskRecord:
        """Create one durable research thread without copying workspace artifacts."""

        normalized_title = title.strip()
        if not normalized_title:
            raise RequestStoreError("ResearchTask title must contain non-whitespace text")
        if len(normalized_title) > 512:
            raise RequestStoreError("ResearchTask title exceeds the 512-character limit")
        identifier = task_id or f"task_{uuid4().hex}"
        now = _utc_now()
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO research_tasks (
                        task_id, workspace_id, title, status, task_revision, active_request_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', 0, NULL, ?, ?)
                    """,
                    (identifier, workspace_id, normalized_title, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise RequestStoreError(f"ResearchTask already exists: {identifier}") from exc
            return self._research_task_from_row(
                self._require_research_task_row(connection, identifier)
            )

    def list_research_tasks(
        self,
        *,
        workspace_id: str,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[ResearchTaskRecord]:
        """List task summaries without loading transcript or checkpoint payloads."""

        if not 1 <= limit <= 500:
            raise ValueError("ResearchTask list limit must be between 1 and 500")
        query = "SELECT * FROM research_tasks WHERE workspace_id = ?"
        values: list[Any] = [workspace_id]
        if not include_archived:
            query += " AND status != 'archived'"
        query += " ORDER BY updated_at DESC, task_id DESC LIMIT ?"
        values.append(limit)
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
            return [self._research_task_from_row(row) for row in rows]

    def list_cache_cleanup_candidates(
        self, *, active_before: str, archived_before: str,
    ) -> tuple[ResearchTaskRecord, ...]:
        """Tasks idle past retention, including archived tasks, across workspaces."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM research_tasks
                WHERE active_request_id IS NULL AND (
                    (status = 'archived' AND updated_at <= ?)
                    OR (status != 'archived' AND updated_at <= ?)
                )
                ORDER BY updated_at, task_id
                """,
                (archived_before, active_before),
            ).fetchall()
            return tuple(self._research_task_from_row(row) for row in rows)

    def get_research_task(
        self,
        task_id: str,
        *,
        workspace_id: str | None = None,
    ) -> ResearchTaskRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM research_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return None
            task = self._research_task_from_row(row)
            if workspace_id is not None and task.workspace_id != workspace_id:
                return None
            return task

    def rename_research_task(
        self,
        *,
        task_id: str,
        title: str,
        expected_task_revision: int | None,
    ) -> ResearchTaskRecord:
        normalized_title = title.strip()
        if not normalized_title:
            raise RequestStoreError("ResearchTask title must contain non-whitespace text")
        with self._transaction() as connection:
            task = self._require_research_task(connection, task_id)
            self._require_task_revision(task, expected_task_revision)
            connection.execute(
                """
                UPDATE research_tasks
                SET title = ?, task_revision = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (normalized_title, task.task_revision + 1, _utc_now(), task_id),
            )
            return self._research_task_from_row(
                self._require_research_task_row(connection, task_id)
            )

    def set_research_task_status(
        self,
        *,
        task_id: str,
        status: ResearchTaskState,
        expected_task_revision: int | None,
    ) -> ResearchTaskRecord:
        with self._transaction() as connection:
            task = self._require_research_task(connection, task_id)
            self._require_task_revision(task, expected_task_revision)
            if task.active_request_id is not None:
                raise RequestStoreError("Cannot archive or reopen a task with an active request")
            connection.execute(
                """
                UPDATE research_tasks
                SET status = ?, task_revision = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (status, task.task_revision + 1, _utc_now(), task_id),
            )
            return self._research_task_from_row(
                self._require_research_task_row(connection, task_id)
            )

    def delete_research_task(
        self,
        *,
        task_id: str,
        expected_task_revision: int | None,
        in_flight_request_id: str | None = None,
    ) -> None:
        """Remove one task and its task-scoped rows; workspace evidence stays."""

        with self._transaction() as connection:
            task = self._require_research_task(connection, task_id)
            self._require_task_revision(task, expected_task_revision)
            if task.active_request_id is not None:
                raise RequestStoreError("Cannot delete a task with an active request")
            # Code executions are owned directly by the task and Agent Server thread.
            connection.execute("DELETE FROM code_executions WHERE task_id = ?", (task_id,))
            connection.execute(
                "DELETE FROM model_call_observations WHERE json_extract(record_json, '$.task_id') = ?",
                (task_id,),
            )
            request_ids = [
                row["request_id"]
                for row in connection.execute(
                    "SELECT request_id FROM request_records WHERE task_id = ?", (task_id,)
                ).fetchall()
                if row["request_id"] != in_flight_request_id
            ]
            if request_ids:
                request_marks = ", ".join("?" for _ in request_ids)
                for table in (
                    "operation_checkpoints",
                    "tool_call_records",
                    "event_records",
                    "task_interactions",
                ):
                    connection.execute(
                        f"DELETE FROM {table} WHERE request_id IN ({request_marks})",
                        request_ids,
                    )
            connection.execute("DELETE FROM task_interactions WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM task_workflows WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM task_transcript_items WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM task_artifact_links WHERE task_id = ?", (task_id,))
            # Coordinator receipts are the durable child of foreground requests.
            # Clear them before their request rows; SQLite correctly rejects the
            # opposite order while foreign-key enforcement is enabled.
            connection.execute(
                "DELETE FROM coordinator_result_receipts WHERE request_id IN "
                "(SELECT request_id FROM request_records WHERE task_id = ? "
                "AND request_id IS NOT ?)",
                (task_id, in_flight_request_id),
            )
            connection.execute(
                "DELETE FROM request_records WHERE task_id = ? AND request_id IS NOT ?",
                (task_id, in_flight_request_id),
            )
            connection.execute("DELETE FROM research_tasks WHERE task_id = ?", (task_id,))

    def begin_task_request(
        self,
        *,
        task_id: str,
        request_id: str,
        expected_task_revision: int | None,
    ) -> ResearchTaskRecord:
        """Claim the one foreground request slot before the model runtime starts."""

        with self._transaction() as connection:
            task = self._require_research_task(connection, task_id)
            self._require_task_revision(task, expected_task_revision)
            if task.status != "active":
                raise RequestStoreError("Only active ResearchTasks may receive an agent request")
            if task.active_request_id is not None:
                raise RequestStoreError("ResearchTask already has an active foreground request")
            connection.execute(
                """
                UPDATE research_tasks
                SET active_request_id = ?, task_revision = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (request_id, task.task_revision + 1, _utc_now(), task_id),
            )
            return self._research_task_from_row(
                self._require_research_task_row(connection, task_id)
            )

    def start_task_workflow(
        self,
        *,
        request_id: str,
        task_id: str,
        workspace_id: str,
    ) -> TaskWorkflowRecord:
        """Create the durable orchestration identity for one foreground task request."""

        with self._transaction() as connection:
            task = self._require_research_task(connection, task_id)
            if task.workspace_id != workspace_id or task.active_request_id != request_id:
                raise RequestStoreError("Task workflow must belong to the active task request")
            now = _utc_now()
            connection.execute(
                """
                INSERT OR IGNORE INTO task_workflows (
                    request_id, task_id, workspace_id, state, activity,
                    heartbeat_at, failure_fingerprint, repeated_failures, created_at, updated_at
                ) VALUES (?, ?, ?, 'planning', 'Planning the task', ?, NULL, 0, ?, ?)
                """,
                (request_id, task_id, workspace_id, now, now, now),
            )
            row = connection.execute(
                "SELECT * FROM task_workflows WHERE request_id = ?", (request_id,)
            ).fetchone()
            assert row is not None
            return self._task_workflow_from_row(row)

    def transition_task_workflow(
        self,
        *,
        request_id: str,
        state: TaskWorkflowState,
        activity: str,
        failure_fingerprint: str | None = None,
    ) -> TaskWorkflowRecord | None:
        """Persist workflow status and heartbeat without changing task revision."""

        if not activity.strip() or len(activity) > 512:
            raise RequestStoreError("Workflow activity must be a bounded non-empty string")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM task_workflows WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None:
                return None
            prior = self._task_workflow_from_row(row)
            repeat_count = prior.repeated_failures
            if failure_fingerprint is not None:
                repeat_count = (
                    prior.repeated_failures + 1
                    if prior.failure_fingerprint == failure_fingerprint
                    else 1
                )
            now = _utc_now()
            connection.execute(
                """
                UPDATE task_workflows
                SET state = ?, activity = ?, heartbeat_at = ?,
                    failure_fingerprint = ?, repeated_failures = ?, updated_at = ?
                WHERE request_id = ?
                """,
                (
                    state,
                    activity.strip(),
                    now,
                    failure_fingerprint,
                    repeat_count,
                    now,
                    request_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM task_workflows WHERE request_id = ?", (request_id,)
            ).fetchone()
            assert updated is not None
            return self._task_workflow_from_row(updated)

    def update_task_workflow_progress(
        self,
        *,
        request_id: str,
        activity: str,
    ) -> TaskWorkflowRecord | None:
        """Persist non-terminal progress without inventing a lifecycle transition.

        This is the single state-preserving progress API for foreground task
        workflows.  Callers that intentionally change lifecycle state must use
        :meth:`transition_task_workflow` instead.
        """

        current = self.get_task_workflow(request_id)
        if current is None:
            return None
        return self.transition_task_workflow(
            request_id=request_id,
            state=current.state,
            activity=activity,
        )

    def get_task_workflow(self, request_id: str) -> TaskWorkflowRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM task_workflows WHERE request_id = ?", (request_id,)
            ).fetchone()
            return self._task_workflow_from_row(row) if row is not None else None

    def list_task_workflows(self, task_id: str) -> tuple[TaskWorkflowRecord, ...]:
        """Return every durable request lifecycle for one task in display order."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM task_workflows WHERE task_id = ? ORDER BY created_at, request_id",
                (task_id,),
            ).fetchall()
            return tuple(self._task_workflow_from_row(row) for row in rows)

    def append_task_transcript_item(
        self,
        *,
        task_id: str,
        item_id: str,
        role: Literal["user", "assistant", "tool", "system"],
        text: str,
        request_id: str | None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        interrupted: bool = False,
    ) -> TaskTranscriptItem:
        """Persist one bounded display record; streaming deltas stay transport-local."""

        if len(text) > 64_000:
            raise RequestStoreError("Task transcript item exceeds the 64 KiB display limit")
        with self._transaction() as connection:
            self._require_research_task(connection, task_id)
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                    "FROM task_transcript_items WHERE task_id = ?",
                    (task_id,),
                ).fetchone()["next_sequence"]
            )
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO task_transcript_items (
                    item_id, task_id, sequence, role, text, request_id, turn_id, tool_call_id,
                    interrupted, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    task_id,
                    sequence,
                    role,
                    text,
                    request_id,
                    turn_id,
                    tool_call_id,
                    int(interrupted),
                    now,
                ),
            )
            connection.execute(
                "UPDATE research_tasks SET updated_at = ? WHERE task_id = ?", (now, task_id)
            )
            return TaskTranscriptItem(
                item_id=item_id,
                task_id=task_id,
                sequence=sequence,
                role=role,
                text=text,
                request_id=request_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                interrupted=interrupted,
                created_at=now,
            )

    def task_snapshot(
        self,
        *,
        task_id: str,
        transcript_limit: int = 100,
        before_sequence: int | None = None,
    ) -> ResearchTaskSnapshot:
        """Read renderer-safe task state."""

        if not 1 <= transcript_limit <= 500:
            raise ValueError("Task transcript limit must be between 1 and 500")
        with self._transaction() as connection:
            task = self._research_task_from_row(
                self._require_research_task_row(connection, task_id)
            )
            query = "SELECT * FROM task_transcript_items WHERE task_id = ?"
            values: list[Any] = [task_id]
            if before_sequence is not None:
                query += " AND sequence < ?"
                values.append(before_sequence)
            query += " ORDER BY sequence DESC LIMIT ?"
            values.append(transcript_limit)
            rows = connection.execute(query, values).fetchall()
            transcript = tuple(reversed(tuple(self._task_transcript_from_row(row) for row in rows)))
            next_cursor: int | None = None
            if transcript:
                older = connection.execute(
                    "SELECT 1 FROM task_transcript_items WHERE task_id = ? AND sequence < ? LIMIT 1",
                    (task_id, transcript[0].sequence),
                ).fetchone()
                if older is not None:
                    next_cursor = transcript[0].sequence
            sources = tuple(self._task_source_summaries_in_connection(connection, task_id))
            outputs = tuple(self._task_output_summaries_in_connection(connection, task_id))
            interactions = tuple(self._pending_interactions_in_connection(connection, task_id))
            workflow_row = connection.execute(
                "SELECT * FROM task_workflows WHERE task_id = ? ORDER BY updated_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            return ResearchTaskSnapshot(
                task=task,
                transcript=transcript,
                next_transcript_cursor=next_cursor,
                sources=sources,
                outputs=outputs,
                delivery_manifests=tuple(
                    manifest.model_dump(mode="json")
                    for manifest in build_delivery_manifests(outputs)
                ),
                interactions=interactions,
                workflow=(
                    self._task_workflow_from_row(workflow_row) if workflow_row is not None else None
                ),
            )

    def research_notes(self, *, workspace_id: str, task_id: str) -> dict[str, Any]:
        """Recover original questions and recent model-authored notes, without a tree.

        The existing append-only transcript is the version history. This is a
        bounded read projection, not a summarizer, scientific schema or new log.
        """
        with self._lock:
            row = self._require_research_task_row(self._connection, task_id)
            if row["workspace_id"] != workspace_id:
                raise RequestStoreError("Task is outside this workspace")
            rows = self._connection.execute(
                "SELECT role, text, request_id, sequence FROM task_transcript_items "
                "WHERE task_id = ? AND role IN ('user', 'assistant') "
                "ORDER BY sequence DESC LIMIT 8", (task_id,),
            ).fetchall()
            first = self._connection.execute(
                "SELECT text FROM task_transcript_items WHERE task_id = ? AND role = 'user' "
                "ORDER BY sequence LIMIT 1", (task_id,),
            ).fetchone()
            return {
                "original_user_question": first["text"] if first else None,
                "recent_notes": [
                    {"role": r["role"], "text": r["text"][:6000],
                     "request_id": r["request_id"], "sequence": r["sequence"],
                     "truncated": len(r["text"]) > 6000}
                    for r in reversed(rows)
                ],
                "history": "Full original messages and earlier versions remain in the task transcript.",
            }

    def list_task_transcript_for_request(
        self,
        *,
        task_id: str,
        request_id: str,
    ) -> tuple[TaskTranscriptItem, ...]:
        """Return the complete visible Coordinator transcript for one request."""

        with self._lock:
            self._require_research_task_row(self._connection, task_id)
            rows = self._connection.execute(
                """
                SELECT * FROM task_transcript_items
                WHERE task_id = ? AND request_id = ?
                ORDER BY sequence
                """,
                (task_id, request_id),
            ).fetchall()
            return tuple(self._task_transcript_from_row(row) for row in rows)

    def create_interaction(
        self,
        *,
        interaction_id: str,
        request_id: str,
        task_id: str | None,
        workspace_id: str,
        session_id: str,
        principal: str,
        question: str,
        kind: Literal["question", "permission", "paper_selection"],
        options: tuple[dict[str, Any], ...] = (),
    ) -> PendingInteractionRecord:
        if not question.strip() or len(question) > 4_000:
            raise RequestStoreError("Interaction must contain at most 4,000 characters")
        if kind == "paper_selection" and not options:
            raise RequestStoreError("Paper selection must contain at least one option")
        if kind != "paper_selection" and options:
            raise RequestStoreError("Only paper selection may contain options")
        if len(options) > 30:
            raise RequestStoreError("Paper selection may contain at most 30 options")
        serialized_options = _canonical_json(list(options))
        if len(serialized_options) > 64_000:
            raise RequestStoreError("Interaction options exceed the 64,000 character limit")
        with self._transaction() as connection:
            self._ensure_nonterminal_request(connection, request_id)
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO task_interactions (
                    interaction_id, request_id, task_id, workspace_id, session_id, principal,
                    kind, question, options_json, state, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL)
                """,
                (
                    interaction_id,
                    request_id,
                    task_id,
                    workspace_id,
                    session_id,
                    principal,
                    kind,
                    question.strip(),
                    serialized_options,
                    now,
                ),
            )
            return self._interaction_from_row(
                self._require_interaction_row(connection, interaction_id)
            )

    def commit_interaction_response(
        self,
        *,
        interaction_id: str,
        session_id: str,
        principal: str,
        terminal_event: EventEnvelope,
    ) -> PendingInteractionRecord:
        with self._transaction() as connection:
            request_id = terminal_event.request_id
            if request_id is None:
                raise RequestStoreError("Interaction response terminal requires a request ID")
            self._ensure_nonterminal_request(connection, request_id)
            interaction = self._interaction_from_row(
                self._require_interaction_row(connection, interaction_id)
            )
            if interaction.session_id != session_id or interaction.principal != principal:
                raise RequestStoreError("Interaction belongs to a different session")
            if interaction.state != "pending":
                raise RequestStoreError("Interaction is no longer pending")
            connection.execute(
                "UPDATE task_interactions SET state = 'answered', resolved_at = ? WHERE interaction_id = ?",
                (_utc_now(), interaction_id),
            )
            self._commit_terminal_in_transaction(connection, request_id, terminal_event)
            return self._interaction_from_row(
                self._require_interaction_row(connection, interaction_id)
            )

    def commit_task_terminal(
        self,
        *,
        request_id: str,
        terminal_event: EventEnvelope,
    ) -> RequestRecord:
        """Commit one task terminal; LangGraph owns model conversation persistence."""

        with self._transaction() as connection:
            request = self._request_from_row(self._require_request_row(connection, request_id))
            self._commit_terminal_in_transaction(connection, request_id, terminal_event)
            if request.task_id is not None:
                task = self._require_research_task(connection, request.task_id)
                if task.active_request_id != request_id:
                    raise RequestStoreError("Terminal request is not the active task request")
                now = _utc_now()
                if terminal_event.type == "request.completed":
                    connection.execute(
                        """
                        UPDATE task_workflows
                        SET state = 'completed', activity = 'Task completed', heartbeat_at = ?,
                            failure_fingerprint = NULL, repeated_failures = 0, updated_at = ?
                        WHERE request_id = ?
                        """,
                        (now, now, request_id),
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO task_artifact_links (
                            task_id, artifact_id, version, relation, origin_request_id, created_at
                        )
                        SELECT ?, artifact_id, version, 'supporting', ?, ?
                        FROM artifact_commit_intents
                        WHERE workspace_id = ? AND origin_request_id = ? AND status = 'committed'
                        """,
                        (
                            request.task_id,
                            request_id,
                            now,
                            request.workspace_id,
                            request_id,
                        ),
                    )
                    self._clear_task_active_request_in_connection(
                        connection, task_id=request.task_id, request_id=request_id
                    )
                    return self._request_from_row(
                        self._require_request_row(connection, request_id)
                    )

                mark_interrupted = terminal_event.type == "request.cancelled"
                workflow_state: TaskWorkflowState = "cancelled"
                workflow_activity = "Cancelled by user"
                failure_fingerprint: str | None = None
                if terminal_event.type == "request.failed":
                    error = terminal_event.payload.error
                    mark_interrupted = error.code == "request_interrupted"
                    workflow_state = "incomplete" if error.recoverable else "failed"
                    workflow_activity = (
                        "Recoverable incomplete — continue from the LangGraph thread"
                        if error.recoverable
                        else "Task failed"
                    )
                    failure_fingerprint = hashlib.sha256(
                        f"{error.code}\0{error.message}".encode("utf-8")
                    ).hexdigest()
                if mark_interrupted:
                    self._mark_task_transcript_interrupted_in_connection(
                        connection, task_id=request.task_id, request_id=request_id
                    )
                row = connection.execute(
                    "SELECT failure_fingerprint, repeated_failures FROM task_workflows "
                    "WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                repeated = 0
                if failure_fingerprint is not None:
                    repeated = (
                        int(row["repeated_failures"]) + 1
                        if row is not None and row["failure_fingerprint"] == failure_fingerprint
                        else 1
                    )
                connection.execute(
                    """
                    UPDATE task_workflows
                    SET state = ?, activity = ?, heartbeat_at = ?, failure_fingerprint = ?,
                        repeated_failures = ?, updated_at = ?
                    WHERE request_id = ?
                    """,
                    (
                        workflow_state,
                        workflow_activity,
                        now,
                        failure_fingerprint,
                        repeated,
                        now,
                        request_id,
                    ),
                )
                self._clear_task_active_request_in_connection(
                    connection, task_id=request.task_id, request_id=request_id
                )
            return self._request_from_row(self._require_request_row(connection, request_id))

    def commit_disclosure_policy(
        self,
        *,
        request_id: str,
        workspace_id: str,
        provider_id: str,
        policy: dict[str, Any],
        expected_workspace_revision: int | None,
        event_factory: Callable[
            [dict[str, Any], int, int, str], tuple[EventEnvelope, EventEnvelope]
        ],
    ) -> DisclosurePolicyCommit:
        """Atomically version a confirmed disclosure policy with its request terminal."""

        with self._transaction() as connection:
            self._ensure_nonterminal_request(connection, request_id)
            current_revision = self._workspace_revision(connection, workspace_id)
            if (
                expected_workspace_revision is not None
                and expected_workspace_revision != current_revision
            ):
                raise WorkspaceRevisionConflict(current_revision)
            existing = self._disclosure_policy_in_connection(connection, workspace_id)
            policy_version = 1 if existing is None else int(existing["policy_version"]) + 1
            updated_at = _utc_now()
            connection.execute(
                """
                INSERT INTO workspace_disclosure_policies (
                    workspace_id, provider_id, policy_version, policy_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    provider_id = excluded.provider_id,
                    policy_version = excluded.policy_version,
                    policy_json = excluded.policy_json,
                    updated_at = excluded.updated_at
                """,
                (workspace_id, provider_id, policy_version, _canonical_json(policy), updated_at),
            )
            connection.execute(
                """
                INSERT INTO workspace_disclosure_policy_versions (
                    workspace_id, policy_version, provider_id, policy_json, confirmed_request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    policy_version,
                    provider_id,
                    _canonical_json(policy),
                    request_id,
                    updated_at,
                ),
            )
            summary = self._disclosure_policy_summary_from_record(
                {
                    "provider_id": provider_id,
                    "policy_version": policy_version,
                    "policy": policy,
                    "confirmed_request_id": request_id,
                    "updated_at": updated_at,
                }
            )
            previous_revision, workspace_revision = self._bump_workspace_revision(
                connection, workspace_id
            )
            event_id = new_event_id()
            domain_event, terminal_event = event_factory(
                summary,
                previous_revision,
                workspace_revision,
                event_id,
            )
            if domain_event.event_id != event_id:
                raise RequestStoreError(
                    "Disclosure policy event factory must preserve the supplied durable event ID"
                )
            self._persist_event(connection, domain_event)
            self._commit_terminal_in_transaction(connection, request_id, terminal_event)
            return DisclosurePolicyCommit(
                policy=summary,
                previous_revision=previous_revision,
                workspace_revision=workspace_revision,
                domain_event=domain_event,
                terminal_event=terminal_event,
            )

    def next_artifact_version(self, *, workspace_id: str, artifact_id: str) -> int:
        """Return a version beyond both committed and durable in-flight intents."""

        with self._lock:
            row = self._connection.execute(
                """
                SELECT COALESCE(MAX(version), 0) AS latest FROM (
                    SELECT version FROM artifact_versions
                    WHERE workspace_id = ? AND artifact_id = ?
                    UNION ALL
                    SELECT version FROM artifact_commit_intents
                    WHERE workspace_id = ? AND artifact_id = ?
                )
                """,
                (workspace_id, artifact_id, workspace_id, artifact_id),
            ).fetchone()
            return int(row["latest"]) + 1

    def prepare_artifact_intent(
        self,
        *,
        operation_id: str,
        request_id: str | None,
        origin_request_id: str | None,
        task_id: str | None,
        task_relation: str | None,
        expected_workspace_revision: int | None,
        manifest: ArtifactManifest,
        staging_uri: str,
        target_uri: str,
    ) -> ArtifactCommitIntent:
        """Durably record a staged filesystem operation before its atomic rename."""

        if (task_id is None) != (task_relation is None):
            raise RequestStoreError("Artifact Task ownership requires both task_id and relation")
        if task_relation is not None and (not task_relation or len(task_relation) > 128):
            raise RequestStoreError("Artifact Task relation must be bounded and non-empty")
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM artifact_commit_intents WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                intent = self._intent_from_row(existing)
                if intent.manifest.manifest_sha256 != manifest.manifest_sha256:
                    raise ArtifactVersionConflict(
                        f"Operation ID already belongs to a different manifest: {operation_id}"
                    )
                if intent.origin_request_id != origin_request_id:
                    raise ArtifactVersionConflict(
                        f"Operation ID already belongs to a different originating request: {operation_id}"
                    )
                if intent.task_id != task_id or intent.task_relation != task_relation:
                    raise ArtifactVersionConflict(
                        "Operation ID already belongs to different Task ownership"
                    )
                return intent
            now = _utc_now()
            try:
                connection.execute(
                    """
                    INSERT INTO artifact_commit_intents (
                        operation_id, request_id, origin_request_id, task_id, task_relation,
                        workspace_id, artifact_id, version,
                        expected_workspace_revision, staging_uri, target_uri, manifest_json, manifest_sha256, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)
                    """,
                    (
                        operation_id,
                        request_id,
                        origin_request_id,
                        task_id,
                        task_relation,
                        manifest.workspace_id,
                        manifest.artifact_id,
                        manifest.version,
                        expected_workspace_revision,
                        staging_uri,
                        target_uri,
                        manifest.model_dump_json(),
                        manifest.manifest_sha256,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ArtifactVersionConflict(
                    f"Artifact version is already reserved: {manifest.artifact_id}@v{manifest.version:04d}"
                ) from exc
            return self._intent_from_row(
                connection.execute(
                    "SELECT * FROM artifact_commit_intents WHERE operation_id = ?", (operation_id,)
                ).fetchone()
            )

    def get_artifact_intent(self, operation_id: str) -> ArtifactCommitIntent | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM artifact_commit_intents WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            return self._intent_from_row(row) if row is not None else None

    def pending_artifact_intents(self) -> list[ArtifactCommitIntent]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM artifact_commit_intents WHERE status = 'prepared' ORDER BY created_at"
            ).fetchall()
            return [self._intent_from_row(row) for row in rows]

    def quarantine_artifact_intent(
        self,
        *,
        operation_id: str,
        quarantine_uri: str | None,
    ) -> ArtifactCommitIntent:
        """Mark an unrecoverable filesystem operation as audit-only, never publishable."""

        with self._transaction() as connection:
            intent = self._intent_from_row(self._require_intent_row(connection, operation_id))
            if intent.status == "committed":
                raise RequestStoreError("A committed artifact intent cannot be quarantined")
            connection.execute(
                """
                UPDATE artifact_commit_intents
                SET status = 'quarantined', quarantine_uri = ?, updated_at = ?
                WHERE operation_id = ?
                """,
                (quarantine_uri, _utc_now(), operation_id),
            )
            row = self._require_intent_row(connection, operation_id)
            return self._intent_from_row(row)

    def commit_artifact_intent(
        self,
        *,
        operation_id: str,
        expected_workspace_revision: int | None,
        event_factory: Callable[
            [ArtifactVersion, ArtifactProjection, int, int, str],
            tuple[EventEnvelope, EventEnvelope | None],
        ],
    ) -> ArtifactCommit:
        """Finalize immutable metadata, domain event, and request terminal atomically."""

        with self._transaction() as connection:
            intent = self._intent_from_row(self._require_intent_row(connection, operation_id))
            if intent.status == "committed":
                artifact = self._require_artifact(
                    connection, intent.workspace_id, intent.artifact_id, intent.version
                )
                projection = self._require_projection(
                    connection,
                    intent.workspace_id,
                    intent.artifact_id,
                    intent.version,
                )
                if intent.committed_event_id is None:
                    raise RequestStoreError("Committed artifact has no durable source event")
                event_row = connection.execute(
                    "SELECT event_json FROM event_records WHERE event_id = ?",
                    (intent.committed_event_id,),
                ).fetchone()
                if event_row is None:
                    raise RequestStoreError(
                        "Committed artifact event is missing from the durable journal"
                    )
                event = parse_event(json.loads(event_row["event_json"]))
                request_row = (
                    self._require_request_row(connection, intent.request_id)
                    if intent.request_id is not None
                    else None
                )
                terminal = (
                    self._request_from_row(request_row).terminal_event
                    if request_row is not None
                    else None
                )
                return ArtifactCommit(
                    artifact=artifact,
                    projection=projection,
                    previous_revision=self._workspace_revision(connection, intent.workspace_id),
                    workspace_revision=self._workspace_revision(connection, intent.workspace_id),
                    domain_event=event,
                    terminal_event=terminal,
                )
            if intent.status != "prepared":
                raise RequestStoreError(f"Artifact intent is not finalizable: {intent.status}")
            workspace = connection.execute(
                "SELECT * FROM workspace_records WHERE workspace_id = ?", (intent.workspace_id,)
            ).fetchone()
            if workspace is None:
                raise RequestStoreError(f"Workspace is not open: {intent.workspace_id}")
            previous_revision = int(workspace["revision"])
            expected = intent.expected_workspace_revision
            if expected_workspace_revision is not None and expected_workspace_revision != expected:
                raise RequestStoreError("Artifact intent expected revision changed after staging")
            if expected is not None and expected != previous_revision:
                raise WorkspaceRevisionConflict(previous_revision)
            existing = connection.execute(
                """
                SELECT manifest_sha256 FROM artifact_versions
                WHERE workspace_id = ? AND artifact_id = ? AND version = ?
                """,
                (intent.workspace_id, intent.artifact_id, intent.version),
            ).fetchone()
            if existing is not None:
                if existing["manifest_sha256"] != intent.manifest.manifest_sha256:
                    raise ArtifactVersionConflict(
                        f"Artifact version already has different content: {intent.artifact_id}@{intent.version}"
                    )
                raise RequestStoreError(
                    "Prepared intent unexpectedly already has an artifact version"
                )

            manifest = intent.manifest
            artifact = self._artifact_from_manifest(manifest, intent.target_uri)
            self._validate_artifact_links(connection, artifact)
            self._validate_domain_content_refs(connection, artifact)
            domain_event_id = new_event_id()
            projection = ArtifactProjection(
                ref=artifact.ref,
                lifecycle_state="available",
                impact_state="current",
                impact_reasons=(),
                updated_at=datetime.now(timezone.utc),
                source_event_id=domain_event_id,
            )
            workspace_revision = previous_revision + 1
            self._insert_artifact_version(connection, artifact)
            self._insert_artifact_links(connection, artifact, source_event_id=domain_event_id)
            self._upsert_projection(connection, projection, workspace_id=intent.workspace_id)
            if artifact.supersedes_version is not None:
                self._mark_superseded(
                    connection,
                    workspace_id=intent.workspace_id,
                    artifact_id=artifact.ref.artifact_id,
                    version=artifact.supersedes_version,
                    source_event_id=domain_event_id,
                )
            rebuilt = self._rebuild_impact_in_transaction(
                connection, workspace_id=intent.workspace_id
            )
            projection = rebuilt[artifact.ref]
            domain_event, terminal_event = event_factory(
                artifact,
                projection,
                previous_revision,
                workspace_revision,
                domain_event_id,
            )
            if domain_event.event_id != domain_event_id:
                raise RequestStoreError(
                    "Artifact event factory must preserve the supplied durable event ID"
                )
            connection.execute(
                "UPDATE workspace_records SET revision = ?, updated_at = ? WHERE workspace_id = ?",
                (workspace_revision, _utc_now(), intent.workspace_id),
            )
            self._persist_event(connection, domain_event)
            if intent.task_id is not None and intent.task_relation is not None:
                task = self._require_research_task(connection, intent.task_id)
                if task.workspace_id != intent.workspace_id:
                    raise RequestStoreError("Artifact Task ownership crosses workspaces")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO task_artifact_links (
                        task_id, artifact_id, version, relation, origin_request_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent.task_id,
                        artifact.ref.artifact_id,
                        artifact.ref.version,
                        intent.task_relation,
                        intent.origin_request_id or intent.request_id or "",
                        _utc_now(),
                    ),
                )
            if terminal_event is not None:
                if intent.request_id is None:
                    raise RequestStoreError(
                        "Artifact terminal event requires a request-backed commit intent"
                    )
                self._commit_terminal_in_transaction(connection, intent.request_id, terminal_event)
            connection.execute(
                """
                UPDATE artifact_commit_intents
                SET status = 'committed', committed_event_id = ?, updated_at = ? WHERE operation_id = ?
                """,
                (domain_event.event_id, _utc_now(), operation_id),
            )
            return ArtifactCommit(
                artifact=artifact,
                projection=projection,
                previous_revision=previous_revision,
                workspace_revision=workspace_revision,
                domain_event=domain_event,
                terminal_event=terminal_event,
            )

    def list_artifact_summaries(
        self,
        workspace_id: str,
        *,
        artifact_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return compact, projection-bearing summaries without loading large artifact files."""

        query = """
            SELECT v.*, p.lifecycle_state,
                   p.impact_state, p.impact_reasons_json, p.updated_at, p.source_event_id
            FROM artifact_versions AS v
            JOIN artifact_projections AS p
              ON p.workspace_id = v.workspace_id
             AND p.artifact_id = v.artifact_id
             AND p.version = v.version
            WHERE v.workspace_id = ?
        """
        values: list[Any] = [workspace_id]
        if artifact_type is not None:
            query += " AND v.artifact_type = ?"
            values.append(artifact_type)
        query += " ORDER BY v.created_at DESC LIMIT ?"
        values.append(limit)
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
            return [self._artifact_summary_from_row(row) for row in rows]

    def find_local_dataset_reference(
        self,
        *,
        workspace_id: str,
        source_scope: str,
        source_locator: str,
        registered_fingerprint: dict[str, int],
    ) -> ArtifactVersion | None:
        """Return an existing immutable reference to the same unchanged local source.

        This is metadata identity, not content inspection.  It prevents repeated UI
        attachment of one path from creating another artifact or copying bytes while
        still creating a new version when the source fingerprint changes.
        """

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM artifact_versions
                WHERE workspace_id = ? AND artifact_type = 'dataset'
                ORDER BY created_at DESC, artifact_id, version DESC
                """,
                (workspace_id,),
            ).fetchall()
            for row in rows:
                artifact = self._artifact_from_row(row, connection=self._connection)
                content = artifact.content
                if (
                    content.get("materialization_level") != "local_reference"
                    or content.get("source_scope") != source_scope
                    or content.get("registered_fingerprint") != registered_fingerprint
                ):
                    continue
                locator = content.get(
                    "source_relative_path" if source_scope == "workspace" else "source_path"
                )
                if locator == source_locator:
                    return artifact
            return None

    def list_task_output_summaries(self, *, task_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return exact artifact versions recorded as outputs of one research task."""

        if not 1 <= limit <= 500:
            raise ValueError("Task output limit must be between 1 and 500")
        with self._lock:
            self._require_research_task_row(self._connection, task_id)
            return self._task_output_summaries_in_connection(self._connection, task_id, limit=limit)

    def list_task_artifacts(self, *, task_id: str) -> list[TaskArtifactRecord]:
        """Return complete immutable artifacts owned or referenced by one task.

        This is an internal filesystem-projection API. Renderer payloads continue to use
        ``list_task_output_summaries`` so local URIs and file inventories never leak into
        Protocol v2 snapshots.
        """

        with self._lock:
            self._require_research_task_row(self._connection, task_id)
            rows = self._connection.execute(
                """
                SELECT l.relation, l.origin_request_id, l.created_at AS task_linked_at, v.*
                FROM task_artifact_links AS l
                JOIN research_tasks AS t ON t.task_id = l.task_id
                JOIN artifact_versions AS v
                  ON v.workspace_id = t.workspace_id
                 AND v.artifact_id = l.artifact_id
                 AND v.version = l.version
                WHERE l.task_id = ?
                ORDER BY l.created_at, v.artifact_id, v.version
                """,
                (task_id,),
            ).fetchall()
            grouped: dict[tuple[str, int], dict[str, Any]] = {}
            for row in rows:
                key = (str(row["artifact_id"]), int(row["version"]))
                item = grouped.setdefault(
                    key,
                    {
                        "row": row,
                        "relations": [],
                        "origin_request_ids": [],
                        "linked_at": str(row["task_linked_at"]),
                    },
                )
                relation = str(row["relation"])
                if relation not in item["relations"]:
                    item["relations"].append(relation)
                raw_origin = row["origin_request_id"]
                if raw_origin:
                    origin = str(raw_origin)
                    if origin not in item["origin_request_ids"]:
                        item["origin_request_ids"].append(origin)
                item["linked_at"] = max(item["linked_at"], str(row["task_linked_at"]))
            return [
                TaskArtifactRecord(
                    artifact=self._artifact_from_row(item["row"], connection=self._connection),
                    relations=tuple(item["relations"]),
                    origin_request_ids=tuple(item["origin_request_ids"]),
                    linked_at=item["linked_at"],
                )
                for item in grouped.values()
            ]

    def link_task_artifact(
        self,
        *,
        task_id: str,
        ref: ArtifactRef,
        relation: str,
        origin_request_id: str | None,
    ) -> None:
        """Associate one immutable artifact version with its owning task."""

        if not relation or len(relation) > 128:
            raise RequestStoreError("Task artifact relation must be a bounded non-empty string")
        with self._transaction() as connection:
            task = self._require_research_task(connection, task_id)
            artifact = connection.execute(
                """
                SELECT 1 FROM artifact_versions
                WHERE workspace_id = ? AND artifact_id = ? AND version = ?
                """,
                (task.workspace_id, ref.artifact_id, ref.version),
            ).fetchone()
            if artifact is None:
                raise RequestStoreError("Task artifact must exist in the task workspace")
            connection.execute(
                """
                INSERT OR IGNORE INTO task_artifact_links (
                    task_id, artifact_id, version, relation, origin_request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    ref.artifact_id,
                    ref.version,
                    relation,
                    origin_request_id or "",
                    _utc_now(),
                ),
            )

    def replace_task_request_deliveries(
        self,
        *,
        task_id: str,
        origin_request_id: str,
        primary_refs: tuple[ArtifactRef, ...],
        supporting_refs: tuple[ArtifactRef, ...] = (),
    ) -> None:
        """Atomically replace one response's presentation set without deleting evidence."""

        if not origin_request_id:
            raise RequestStoreError("Task delivery replacement requires a request ID")
        if not primary_refs:
            raise RequestStoreError("A task response requires at least one primary delivery")
        if len(set(primary_refs)) != len(primary_refs):
            raise RequestStoreError("Primary task deliveries must be unique")
        if len(set(supporting_refs)) != len(supporting_refs):
            raise RequestStoreError("Supporting task deliveries must be unique")
        if set(primary_refs).intersection(supporting_refs):
            raise RequestStoreError("Primary and supporting task deliveries must be disjoint")

        deliveries = tuple((ref, "primary") for ref in primary_refs) + tuple(
            (ref, "supporting") for ref in supporting_refs
        )
        with self._transaction() as connection:
            task = self._require_research_task(connection, task_id)
            for ref, _relation in deliveries:
                artifact = connection.execute(
                    """
                    SELECT 1 FROM artifact_versions
                    WHERE workspace_id = ? AND artifact_id = ? AND version = ?
                    """,
                    (task.workspace_id, ref.artifact_id, ref.version),
                ).fetchone()
                if artifact is None:
                    raise RequestStoreError("Task artifact must exist in the task workspace")

            # Direct publication and earlier result-submission paths may already have projected
            # several representations as outputs. The final presentation contract is
            # authoritative for this request only; supporting/evidence links remain durable.
            connection.execute(
                """
                DELETE FROM task_artifact_links
                WHERE task_id = ? AND origin_request_id = ?
                  AND relation IN ('primary', 'output')
                """,
                (task_id, origin_request_id),
            )
            now = _utc_now()
            for ref, relation in deliveries:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO task_artifact_links (
                        task_id, artifact_id, version, relation, origin_request_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        ref.artifact_id,
                        ref.version,
                        relation,
                        origin_request_id,
                        now,
                    ),
                )

    def _task_output_summaries_in_connection(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT l.relation, l.origin_request_id, l.created_at AS task_linked_at,
                   v.*, p.lifecycle_state,
                   p.impact_state, p.impact_reasons_json, p.updated_at, p.source_event_id
            FROM task_artifact_links AS l
            JOIN research_tasks AS t ON t.task_id = l.task_id
            JOIN artifact_versions AS v
              ON v.workspace_id = t.workspace_id
             AND v.artifact_id = l.artifact_id
             AND v.version = l.version
            JOIN artifact_projections AS p
              ON p.workspace_id = v.workspace_id
             AND p.artifact_id = v.artifact_id
             AND p.version = v.version
            WHERE l.task_id = ? AND l.relation != 'source'
            ORDER BY l.created_at DESC
            """,
            (task_id,),
        ).fetchall()
        grouped: dict[tuple[str, int], dict[str, Any]] = {}
        relation_priority = {"primary": 3, "output": 3, "supporting": 2, "internal": 1}
        for row in rows:
            key = (str(row["artifact_id"]), int(row["version"]))
            origin = str(row["origin_request_id"]) or None
            priority = relation_priority.get(str(row["relation"]), 0)
            summary = grouped.get(key)
            if summary is None:
                presentation = self._task_output_presentation_metadata_in_connection(
                    connection,
                    row,
                )
                summary = {
                    "artifact": self._artifact_summary_from_row(row),
                    "relation": row["relation"],
                    "origin_request_id": origin,
                    "origin_request_ids": [],
                    "linked_at": row["task_linked_at"],
                    **presentation,
                    "_relation_priority": priority,
                }
                grouped[key] = summary
            elif priority > int(summary["_relation_priority"]):
                summary["relation"] = row["relation"]
                summary["origin_request_id"] = origin
                summary["origin_request_ids"] = []
                summary["linked_at"] = row["task_linked_at"]
                summary["_relation_priority"] = priority
            elif priority < int(summary["_relation_priority"]):
                continue
            if origin is not None and origin not in summary["origin_request_ids"]:
                summary["origin_request_ids"].append(origin)
        for summary in grouped.values():
            summary.pop("_relation_priority", None)
        return list(grouped.values())[:limit]

    def _task_source_summaries_in_connection(
        self,
        connection: sqlite3.Connection,
        task_id: str,
    ) -> list[dict[str, Any]]:
        """Return task-owned inputs separately from user-facing result outputs."""

        rows = connection.execute(
            """
            SELECT l.origin_request_id, l.created_at AS task_linked_at,
                   v.*, p.lifecycle_state,
                   p.impact_state, p.impact_reasons_json, p.updated_at, p.source_event_id
            FROM task_artifact_links AS l
            JOIN research_tasks AS t ON t.task_id = l.task_id
            JOIN artifact_versions AS v
              ON v.workspace_id = t.workspace_id
             AND v.artifact_id = l.artifact_id
             AND v.version = l.version
            JOIN artifact_projections AS p
              ON p.workspace_id = v.workspace_id
             AND p.artifact_id = v.artifact_id
             AND p.version = v.version
            WHERE l.task_id = ? AND l.relation = 'source'
            ORDER BY l.created_at, v.artifact_id, v.version
            """,
            (task_id,),
        ).fetchall()
        grouped: dict[tuple[str, int], dict[str, Any]] = {}
        for row in rows:
            key = (str(row["artifact_id"]), int(row["version"]))
            origin = str(row["origin_request_id"]) or None
            summary = grouped.get(key)
            if summary is None:
                summary = {
                    "artifact": self._artifact_summary_from_row(row),
                    "relation": "source",
                    "origin_request_id": origin,
                    "origin_request_ids": [],
                    "linked_at": row["task_linked_at"],
                }
                grouped[key] = summary
            if origin is not None and origin not in summary["origin_request_ids"]:
                summary["origin_request_ids"].append(origin)
        return list(grouped.values())

    @staticmethod
    def _task_output_presentation_metadata_in_connection(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        """Project the artifact's direct user-facing result capability."""

        artifact_type = str(row["artifact_type"])
        artifact_key = f"{row['artifact_id']}@v{int(row['version'])}"
        return {
            "result_entry_kind": (
                artifact_type if artifact_type in {"interactive_view", "report"} else None
            ),
            "result_ref": artifact_key,
        }

    def list_artifact_versions(
        self, *, workspace_id: str, artifact_id: str
    ) -> list[dict[str, Any]]:
        """Return every immutable version of one artifact in newest-first order."""

        query = """
            SELECT v.*, p.lifecycle_state,
                   p.impact_state, p.impact_reasons_json, p.updated_at, p.source_event_id
            FROM artifact_versions AS v
            JOIN artifact_projections AS p
              ON p.workspace_id = v.workspace_id
             AND p.artifact_id = v.artifact_id
             AND p.version = v.version
            WHERE v.workspace_id = ? AND v.artifact_id = ?
            ORDER BY v.version DESC
        """
        with self._lock:
            rows = self._connection.execute(query, (workspace_id, artifact_id)).fetchall()
        return [self._artifact_summary_from_row(row) for row in rows]

    def get_artifact_file(self, *, workspace_id: str, uri: str) -> ArtifactFile | None:
        """Resolve a URI only when it belongs to an immutable artifact in this workspace."""

        with self._lock:
            row = self._connection.execute(
                """
                SELECT uri, mime_type, size_bytes, sha256 FROM artifact_files
                WHERE workspace_id = ? AND uri = ?
                """,
                (workspace_id, uri),
            ).fetchone()
        if row is None:
            return None
        return ArtifactFile(
            uri=row["uri"],
            mime_type=row["mime_type"],
            size_bytes=int(row["size_bytes"]),
            sha256=row["sha256"],
        )

    def list_artifact_links(
        self,
        *,
        workspace_id: str,
        ref: ArtifactRef,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Return typed graph edges in either direction without loading artifact payloads."""

        if direction not in {"incoming", "outgoing", "both"}:
            raise ValueError(f"Unsupported artifact-link direction: {direction}")
        clauses: list[str] = []
        values: list[Any] = [workspace_id]
        if direction in {"outgoing", "both"}:
            clauses.append("(source_artifact_id = ? AND source_version = ?)")
            values.extend((ref.artifact_id, ref.version))
        if direction in {"incoming", "both"}:
            clauses.append("(target_artifact_id = ? AND target_version = ?)")
            values.extend((ref.artifact_id, ref.version))
        query = (
            """
            SELECT * FROM artifact_links
            WHERE workspace_id = ? AND ("""
            + " OR ".join(clauses)
            + ") ORDER BY link_id"
        )
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
        return [
            {
                "source": {
                    "artifact_id": row["source_artifact_id"],
                    "version": int(row["source_version"]),
                },
                "target": {
                    "artifact_id": row["target_artifact_id"],
                    "version": int(row["target_version"]),
                },
                "relation": row["relation"],
                "intrinsic": bool(row["intrinsic"]),
                "created_at": row["created_at"],
                "source_event_id": row["source_event_id"],
            }
            for row in rows
        ]

    def list_active_refs(self, workspace_id: str) -> dict[str, ArtifactRef]:
        """Read named workspace pointers that always pin an exact artifact version."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT slot, artifact_id, version FROM workspace_active_refs
                WHERE workspace_id = ? ORDER BY slot
                """,
                (workspace_id,),
            ).fetchall()
        return {
            row["slot"]: ArtifactRef(artifact_id=row["artifact_id"], version=int(row["version"]))
            for row in rows
        }

    def set_disclosure_policy(
        self,
        *,
        workspace_id: str,
        provider_id: str,
        policy_version: int,
        policy: dict[str, Any],
    ) -> None:
        """Persist a provider-bound disclosure policy without storing disclosed content."""

        with self._transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM workspace_records WHERE workspace_id = ?", (workspace_id,)
                ).fetchone()
                is None
            ):
                raise RequestStoreError(f"Workspace is not open: {workspace_id}")
            updated_at = _utc_now()
            serialized_policy = _canonical_json(policy)
            connection.execute(
                """
                INSERT INTO workspace_disclosure_policies (
                    workspace_id, provider_id, policy_version, policy_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    provider_id = excluded.provider_id,
                    policy_version = excluded.policy_version,
                    policy_json = excluded.policy_json,
                    updated_at = excluded.updated_at
                """,
                (workspace_id, provider_id, policy_version, serialized_policy, updated_at),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO workspace_disclosure_policy_versions (
                    workspace_id, policy_version, provider_id, policy_json, confirmed_request_id, created_at
                ) VALUES (?, ?, ?, ?, NULL, ?)
                """,
                (workspace_id, policy_version, provider_id, serialized_policy, updated_at),
            )

    def get_disclosure_policy(self, workspace_id: str) -> dict[str, Any] | None:
        """Read the active provider-bound policy as structured data."""

        with self._lock:
            return self._disclosure_policy_in_connection(self._connection, workspace_id)

    @staticmethod
    def _disclosure_policy_in_connection(
        connection: sqlite3.Connection,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM workspace_disclosure_policies WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "provider_id": row["provider_id"],
            "policy_version": int(row["policy_version"]),
            "policy": json.loads(row["policy_json"]),
            "updated_at": row["updated_at"],
        }

    @classmethod
    def _disclosure_policy_summary_in_connection(
        cls,
        connection: sqlite3.Connection,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        policy = cls._disclosure_policy_in_connection(connection, workspace_id)
        if policy is None:
            return None
        version = connection.execute(
            """
            SELECT confirmed_request_id FROM workspace_disclosure_policy_versions
            WHERE workspace_id = ? AND policy_version = ?
            """,
            (workspace_id, policy["policy_version"]),
        ).fetchone()
        return cls._disclosure_policy_summary_from_record(
            {
                **policy,
                "confirmed_request_id": version["confirmed_request_id"]
                if version is not None
                else None,
            }
        )

    @staticmethod
    def _disclosure_policy_summary_from_record(record: dict[str, Any]) -> dict[str, Any]:
        policy = record["policy"]
        return {
            "provider_id": record["provider_id"],
            "policy_version": int(record["policy_version"]),
            "metadata": policy["metadata"],
            "aggregate_statistics": policy["aggregate_statistics"],
            "raw_bounded_sample": policy["raw_bounded_sample"],
            "document_text": policy["document_text"],
            "diagnostic_excerpt": policy["diagnostic_excerpt"],
            "confirmed": bool(record.get("confirmed_request_id")),
            "updated_at": datetime.fromisoformat(record["updated_at"])
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }

    def list_disclosure_policy_versions(
        self,
        *,
        workspace_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return immutable policy snapshots newest first without returning disclosed data."""

        if limit < 1 or limit > 500:
            raise ValueError("Disclosure policy version limit must be between 1 and 500")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM workspace_disclosure_policy_versions
                WHERE workspace_id = ?
                ORDER BY policy_version DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        return [
            {
                **self._disclosure_policy_summary_from_record(
                    {
                        "provider_id": row["provider_id"],
                        "policy_version": int(row["policy_version"]),
                        "policy": json.loads(row["policy_json"]),
                        "confirmed_request_id": row["confirmed_request_id"],
                        "updated_at": row["created_at"],
                    }
                ),
                "confirmed_request_id": row["confirmed_request_id"],
            }
            for row in rows
        ]

    def get_disclosure_policy_summary(self, workspace_id: str) -> dict[str, Any] | None:
        """Return the active policy with its request-bound confirmation state."""

        with self._lock:
            return self._disclosure_policy_summary_in_connection(self._connection, workspace_id)

    def record_disclosure_audit(
        self,
        *,
        audit_id: str,
        workspace_id: str,
        provider_id: str,
        policy_version: int,
        content_type: str,
        disposition: str,
        byte_count: int,
        item_count: int,
        source_ref: ArtifactRef | None = None,
    ) -> None:
        """Record only disclosure metadata, never the potentially sensitive disclosed value."""

        if byte_count < 0 or item_count < 0:
            raise ValueError("Disclosure audit sizes must be non-negative")
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO disclosure_audit_records (
                    audit_id, workspace_id, provider_id, policy_version, content_type,
                    disposition, byte_count, item_count, source_ref_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    workspace_id,
                    provider_id,
                    policy_version,
                    content_type,
                    disposition,
                    byte_count,
                    item_count,
                    _canonical_json(source_ref.model_dump(mode="json")) if source_ref else None,
                    _utc_now(),
                ),
            )

    def list_disclosure_audits(
        self, *, workspace_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return audit metadata suitable for an inspector without returning disclosed payloads."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM disclosure_audit_records
                WHERE workspace_id = ? ORDER BY created_at DESC, audit_id DESC LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        return [
            {
                "audit_id": row["audit_id"],
                "provider_id": row["provider_id"],
                "policy_version": int(row["policy_version"]),
                "content_type": row["content_type"],
                "disposition": row["disposition"],
                "byte_count": int(row["byte_count"]),
                "item_count": int(row["item_count"]),
                "source_ref": json.loads(row["source_ref_json"])
                if row["source_ref_json"]
                else None,
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def record_resource_usage(
        self,
        *,
        usage_id: str,
        workspace_id: str,
        resource_kind: str,
        resource_name: str,
        resource_version: str,
        agent_run_id: str | None = None,
        request_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        """Audit a loaded skill/reference by identity and version, never by copied content."""

        with self._transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM workspace_records WHERE workspace_id = ?", (workspace_id,)
                ).fetchone()
                is None
            ):
                raise RequestStoreError(f"Workspace is not open: {workspace_id}")
            connection.execute(
                """
                INSERT INTO resource_usage_records (
                    usage_id, workspace_id, agent_run_id, resource_kind, resource_name,
                    resource_version, created_at, request_id, agent_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_id,
                    workspace_id,
                    agent_run_id,
                    resource_kind,
                    resource_name,
                    resource_version,
                    _utc_now(),
                    request_id,
                    agent_id,
                ),
            )

    def list_resource_usage(
        self,
        *,
        workspace_id: str,
        agent_run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read resource identity records for an inspector or reproducibility appendix."""

        with self._lock:
            if agent_run_id is None:
                rows = self._connection.execute(
                    """
                    SELECT * FROM resource_usage_records
                    WHERE workspace_id = ? ORDER BY created_at DESC, usage_id DESC LIMIT ?
                    """,
                    (workspace_id, limit),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """
                    SELECT * FROM resource_usage_records
                    WHERE workspace_id = ? AND agent_run_id = ?
                    ORDER BY created_at DESC, usage_id DESC LIMIT ?
                    """,
                    (workspace_id, agent_run_id, limit),
                ).fetchall()
        return [
            {
                "usage_id": row["usage_id"],
                "agent_run_id": row["agent_run_id"],
                "resource_kind": row["resource_kind"],
                "resource_name": row["resource_name"],
                "resource_version": row["resource_version"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def set_active_ref(
        self,
        *,
        workspace_id: str,
        slot: str,
        ref: ArtifactRef,
        expected_workspace_revision: int | None,
    ) -> WorkspaceSnapshot:
        """Move one named active pointer while preserving exact immutable refs."""

        with self._transaction() as connection:
            workspace = connection.execute(
                "SELECT * FROM workspace_records WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if workspace is None:
                raise RequestStoreError(f"Workspace is not open: {workspace_id}")
            previous_revision = int(workspace["revision"])
            if (
                expected_workspace_revision is not None
                and expected_workspace_revision != previous_revision
            ):
                raise WorkspaceRevisionConflict(previous_revision)
            self._require_artifact(connection, workspace_id, ref.artifact_id, ref.version)
            connection.execute(
                """
                INSERT INTO workspace_active_refs (workspace_id, slot, artifact_id, version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, slot) DO UPDATE SET
                    artifact_id = excluded.artifact_id,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (workspace_id, slot, ref.artifact_id, ref.version, _utc_now()),
            )
            revision = previous_revision + 1
            connection.execute(
                "UPDATE workspace_records SET revision = ?, updated_at = ? WHERE workspace_id = ?",
                (revision, _utc_now(), workspace_id),
            )
            return WorkspaceSnapshot(
                workspace_id=workspace_id,
                path=workspace["path"],
                revision=revision,
                artifacts=self.list_artifact_summaries(workspace_id),
                active_refs=self.list_active_refs(workspace_id),
            )

    def commit_active_ref(
        self,
        *,
        request_id: str,
        workspace_id: str,
        slot: str,
        ref: ArtifactRef,
        expected_workspace_revision: int | None,
        event_factory: Callable[[WorkspaceSnapshot, int, int], tuple[EventEnvelope, EventEnvelope]],
    ) -> ActiveRefCommit:
        """Atomically update one active pointer with its request terminal and domain event."""

        with self._transaction() as connection:
            self._ensure_nonterminal_request(connection, request_id)
            workspace = connection.execute(
                "SELECT * FROM workspace_records WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if workspace is None:
                raise RequestStoreError(f"Workspace is not open: {workspace_id}")
            previous_revision = int(workspace["revision"])
            if (
                expected_workspace_revision is not None
                and expected_workspace_revision != previous_revision
            ):
                raise WorkspaceRevisionConflict(previous_revision)
            self._require_artifact(connection, workspace_id, ref.artifact_id, ref.version)
            connection.execute(
                """
                INSERT INTO workspace_active_refs (workspace_id, slot, artifact_id, version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, slot) DO UPDATE SET
                    artifact_id = excluded.artifact_id,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (workspace_id, slot, ref.artifact_id, ref.version, _utc_now()),
            )
            workspace_revision = previous_revision + 1
            connection.execute(
                "UPDATE workspace_records SET revision = ?, updated_at = ? WHERE workspace_id = ?",
                (workspace_revision, _utc_now(), workspace_id),
            )
            snapshot = WorkspaceSnapshot(
                workspace_id=workspace_id,
                path=workspace["path"],
                revision=workspace_revision,
                artifacts=self.list_artifact_summaries(workspace_id),
                active_refs=self.list_active_refs(workspace_id),
                disclosure_policy=self._disclosure_policy_summary_in_connection(
                    connection, workspace_id
                ),
            )
            domain_event, terminal_event = event_factory(
                snapshot,
                previous_revision,
                workspace_revision,
            )
            self._persist_event(connection, domain_event)
            self._commit_terminal_in_transaction(connection, request_id, terminal_event)
            return ActiveRefCommit(
                snapshot=snapshot,
                previous_revision=previous_revision,
                domain_event=domain_event,
                terminal_event=terminal_event,
            )

    def start_code_execution(
        self,
        *,
        execution_id: str,
        workspace_id: str,
        task_id: str,
        agent_thread_id: str,
        server_run_id: str,
        request: dict[str, Any],
        started_at: str,
    ) -> CodeExecutionRecord:
        """Start one code activity owned by an Agent Server child run."""

        with self._transaction() as connection:
            task = connection.execute(
                "SELECT workspace_id FROM research_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None or task["workspace_id"] != workspace_id:
                raise RequestStoreError("Code execution task is unavailable")
            connection.execute(
                """
                INSERT INTO code_executions (
                    execution_id, workspace_id, task_id, agent_thread_id, server_run_id,
                    state, request_json, result_json, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, NULL, ?, NULL)
                """,
                (
                    execution_id,
                    workspace_id,
                    task_id,
                    agent_thread_id,
                    server_run_id,
                    _canonical_json(request),
                    started_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM code_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            assert row is not None
            return self._code_execution_from_row(row)

    def finish_code_execution(
        self,
        *,
        execution_id: str,
        state: str,
        result: dict[str, Any],
        ended_at: str,
    ) -> CodeExecutionRecord:
        """Finish one Expert code activity without changing workstream semantics."""

        if state not in {
            "succeeded",
            "failed",
            "timed_out",
            "resource_limited",
            "cancelled",
        }:
            raise ValueError(f"Unsupported code execution terminal state: {state}")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM code_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise RequestStoreError(f"Code execution is unavailable: {execution_id}")
            if row["state"] != "running":
                if row["state"] == state and row["result_json"] == _canonical_json(result):
                    return self._code_execution_from_row(row)
                raise RequestStoreError("Code execution already has a terminal result")
            connection.execute(
                """
                UPDATE code_executions
                SET state = ?, result_json = ?, ended_at = ?
                WHERE execution_id = ?
                """,
                (state, _canonical_json(result), ended_at, execution_id),
            )
            updated = connection.execute(
                "SELECT * FROM code_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            assert updated is not None
            return self._code_execution_from_row(updated)

    def list_agent_code_executions(
        self, *, workspace_id: str, task_id: str, agent_thread_id: str
    ) -> tuple[CodeExecutionRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM code_executions
                WHERE workspace_id = ? AND task_id = ? AND agent_thread_id = ?
                ORDER BY started_at, execution_id
                """,
                (workspace_id, task_id, agent_thread_id),
            ).fetchall()
            return tuple(self._code_execution_from_row(row) for row in rows)

    def list_task_code_executions(
        self, *, workspace_id: str, task_id: str
    ) -> tuple[CodeExecutionRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM code_executions
                   WHERE workspace_id = ? AND task_id = ?
                   ORDER BY started_at, execution_id""",
                (workspace_id, task_id),
            ).fetchall()
            return tuple(self._code_execution_from_row(row) for row in rows)

    def get_code_execution(self, execution_id: str) -> CodeExecutionRecord | None:
        """Read one Expert-owned code audit record by its immutable identity."""

        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM code_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            return self._code_execution_from_row(row) if row is not None else None

    def list_running_code_executions(self) -> tuple[CodeExecutionRecord, ...]:
        """Return executions that require startup settlement or interruption."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM code_executions WHERE state = 'running' "
                "ORDER BY started_at, execution_id"
            ).fetchall()
            return tuple(self._code_execution_from_row(row) for row in rows)

    def fail_running_code_executions(self) -> int:
        """Mark only executions left unprovable after manifest reconciliation."""

        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT execution_id FROM code_executions WHERE state = 'running'"
            ).fetchall()
            if not rows:
                return 0
            now = _utc_now()
            connection.execute(
                """
                UPDATE code_executions
                SET state = 'failed', result_json = ?, ended_at = ?
                WHERE state = 'running'
                """,
                (
                    _canonical_json(
                        {
                            "error": "Code execution was interrupted before a complete "
                            "result manifest could be verified.",
                            "failure_code": WorkFailureCode.BACKEND_INTERRUPTED.value,
                        }
                    ),
                    now,
                ),
            )
            return len(rows)

    def get_artifact(self, *, workspace_id: str, ref: ArtifactRef) -> ArtifactVersion | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM artifact_versions
                WHERE workspace_id = ? AND artifact_id = ? AND version = ?
                """,
                (workspace_id, ref.artifact_id, ref.version),
            ).fetchone()
            return self._artifact_from_row(row) if row is not None else None

    def get_projection(self, *, workspace_id: str, ref: ArtifactRef) -> ArtifactProjection | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM artifact_projections
                WHERE workspace_id = ? AND artifact_id = ? AND version = ?
                """,
                (workspace_id, ref.artifact_id, ref.version),
            ).fetchone()
            return self._projection_from_row(row) if row is not None else None

    def rebuild_impact_projections(
        self, *, workspace_id: str
    ) -> dict[ArtifactRef, ArtifactProjection]:
        """Deterministically rebuild impact projections from authoritative DB records."""

        with self._transaction() as connection:
            return self._rebuild_impact_in_transaction(connection, workspace_id=workspace_id)

    def set_artifact_lifecycle(
        self,
        *,
        workspace_id: str,
        ref: ArtifactRef,
        lifecycle_state: str,
        source_event_id: str | None = None,
    ) -> ArtifactProjection:
        """Change a lifecycle projection without mutating the immutable artifact manifest."""

        with self._transaction() as connection:
            projection = self._require_projection(
                connection,
                workspace_id,
                ref.artifact_id,
                ref.version,
            ).model_copy(
                update={
                    "lifecycle_state": lifecycle_state,
                    "updated_at": datetime.now(timezone.utc),
                    "source_event_id": source_event_id,
                }
            )
            self._upsert_projection(connection, projection, workspace_id=workspace_id)
            rebuilt = self._rebuild_impact_in_transaction(connection, workspace_id=workspace_id)
            return rebuilt[ref]

    def set_artifact_impact_input(
        self,
        *,
        state_event_id: str,
        workspace_id: str,
        ref: ArtifactRef,
        kind: str,
        active: bool,
        source_event_id: str | None = None,
    ) -> ArtifactProjection:
        """Record source availability/decision facts and rebuild dependent projections."""

        if kind not in {"source_unavailable", "decision_invalidated"}:
            raise RequestStoreError(f"Unsupported artifact impact input: {kind}")
        with self._transaction() as connection:
            self._require_artifact(connection, workspace_id, ref.artifact_id, ref.version)
            connection.execute(
                """
                INSERT INTO artifact_state_events (
                    state_event_id, workspace_id, artifact_id, version, kind, active,
                    source_event_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(state_event_id) DO UPDATE SET
                    active = excluded.active,
                    source_event_id = excluded.source_event_id
                """,
                (
                    state_event_id,
                    workspace_id,
                    ref.artifact_id,
                    ref.version,
                    kind,
                    int(active),
                    source_event_id,
                    _utc_now(),
                ),
            )
            rebuilt = self._rebuild_impact_in_transaction(connection, workspace_id=workspace_id)
            return rebuilt[ref]

    def commit_cancellation(
        self,
        *,
        cancel_request_id: str,
        target_request_id: str,
        target_event: EventEnvelope | None,
        terminal_event: EventEnvelope,
    ) -> CancellationCommit:
        """Persist target cancellation and the control-request terminal together."""

        with self._transaction() as connection:
            self._ensure_nonterminal_request(connection, cancel_request_id)
            target = self._request_from_row(
                self._require_request_row(connection, target_request_id)
            )
            if target.terminal:
                target_event = None
            elif target_event is None:
                raise RequestStoreError("Active cancellation requires a target terminal event")
            elif target_event.request_id != target_request_id:
                raise RequestStoreError("Cancellation target event has the wrong request ID")
            if target_event is not None:
                self._commit_terminal_in_transaction(connection, target_request_id, target_event)
                self._interrupt_interactions_for_request_in_connection(
                    connection, target_request_id
                )
                if target.task_id is not None:
                    self._mark_task_transcript_interrupted_in_connection(
                        connection, task_id=target.task_id, request_id=target_request_id
                    )
                    self._clear_task_active_request_in_connection(
                        connection,
                        task_id=target.task_id,
                        request_id=target_request_id,
                    )
            self._commit_terminal_in_transaction(connection, cancel_request_id, terminal_event)
            return CancellationCommit(
                target=self._request_from_row(
                    self._require_request_row(connection, target_request_id)
                ),
                target_terminal_event=target_event,
                terminal_event=terminal_event,
            )

    def record_coordinator_result(
        self,
        *,
        request_id: str,
        result: CoordinatorResult,
    ) -> CoordinatorResult:
        """Persist the Coordinator boundary before acknowledging its tool call."""

        serialized = _canonical_json(result.model_dump(mode="json"))
        with self._transaction() as connection:
            request = self._request_from_row(self._require_request_row(connection, request_id))
            if request.request_type != "session.submit":
                raise RequestStoreError(
                    "Coordinator result parent is not a foreground Ocean request"
                )
            existing = connection.execute(
                "SELECT result_json FROM coordinator_result_receipts WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                if existing["result_json"] != serialized:
                    raise RequestStoreError(
                        "Coordinator result request already has a different durable receipt"
                    )
                return CoordinatorResult.model_validate_json(existing["result_json"])
            if request.terminal:
                raise RequestStoreError("Cannot attach a Coordinator result to a terminal request")
            connection.execute(
                """
                INSERT INTO coordinator_result_receipts (
                    request_id, result_json, created_at
                ) VALUES (?, ?, ?)
                """,
                (request_id, serialized, _utc_now()),
            )
            return result

    def get_coordinator_result(self, request_id: str) -> CoordinatorResult | None:
        """Read the durable Coordinator boundary for one foreground request."""

        with self._lock:
            row = self._connection.execute(
                "SELECT result_json FROM coordinator_result_receipts WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            return CoordinatorResult.model_validate_json(row["result_json"])

    def recover_incomplete(
        self,
        event_factory: Callable[[RequestRecord], EventEnvelope],
        completed_event_factory: Callable[[RequestRecord, CoordinatorResult], EventEnvelope]
        | None = None,
    ) -> list[EventEnvelope]:
        """Settle active requests from durable receipts or mark them interrupted."""

        recovered: list[EventEnvelope] = []
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM request_records WHERE state IN ('accepted', 'in_progress')"
            ).fetchall()
            for row in rows:
                record = self._request_from_row(row)
                receipt_row = connection.execute(
                    "SELECT result_json FROM coordinator_result_receipts WHERE request_id = ?",
                    (record.request_id,),
                ).fetchone()
                coordinator_result = (
                    CoordinatorResult.model_validate_json(receipt_row["result_json"])
                    if receipt_row is not None
                    else None
                )
                recovered_completion = (
                    coordinator_result is not None
                    and completed_event_factory is not None
                    and record.request_type == "session.submit"
                )
                event = (
                    completed_event_factory(record, coordinator_result)
                    if recovered_completion and coordinator_result is not None
                    else event_factory(record)
                )
                self._commit_terminal_in_transaction(connection, record.request_id, event)
                self._interrupt_interactions_for_request_in_connection(
                    connection, record.request_id
                )
                if record.task_id is not None:
                    workflow = connection.execute(
                        "SELECT 1 FROM task_workflows WHERE request_id = ?",
                        (record.request_id,),
                    ).fetchone()
                    if recovered_completion:
                        now = _utc_now()
                        item_id = f"recovered-coordinator-{record.request_id}"
                        existing_item = connection.execute(
                            "SELECT 1 FROM task_transcript_items WHERE item_id = ?",
                            (item_id,),
                        ).fetchone()
                        if existing_item is None and coordinator_result is not None:
                            sequence = int(
                                connection.execute(
                                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                                    "FROM task_transcript_items WHERE task_id = ?",
                                    (record.task_id,),
                                ).fetchone()["next_sequence"]
                            )
                            connection.execute(
                                """
                                INSERT INTO task_transcript_items (
                                    item_id, task_id, sequence, role, text, request_id,
                                    turn_id, tool_call_id, interrupted, created_at
                                ) VALUES (?, ?, ?, 'assistant', ?, ?, NULL, NULL, 0, ?)
                                """,
                                (
                                    item_id,
                                    record.task_id,
                                    sequence,
                                    coordinator_result.answer_markdown,
                                    record.request_id,
                                    now,
                                ),
                            )
                        connection.execute(
                            """
                            UPDATE task_workflows
                            SET state = 'completed', activity = 'Task completed',
                                heartbeat_at = ?, updated_at = ?
                            WHERE request_id = ?
                            """,
                            (now, now, record.request_id),
                        )
                    elif workflow is None:
                        # A crash can occur between request reservation and
                        # workflow creation. Record the interrupted transcript.
                        self._mark_task_transcript_interrupted_in_connection(
                            connection,
                            task_id=record.task_id,
                            request_id=record.request_id,
                        )
                    else:
                        now = _utc_now()
                        connection.execute(
                            """
                            UPDATE task_workflows
                            SET state = 'incomplete',
                                activity = 'Backend restarted — ready to resume from checkpoint',
                                heartbeat_at = ?, updated_at = ?
                            WHERE request_id = ?
                            """,
                            (now, now, record.request_id),
                        )
                    self._clear_task_active_request_in_connection(
                        connection,
                        task_id=record.task_id,
                        request_id=record.request_id,
                    )
                recovered.append(event)
        return recovered

    def operation_result(self, operation_id: str) -> dict[str, Any] | None:
        """Return an existing model-tool operation result without re-executing it."""

        with self._lock:
            row = self._connection.execute(
                "SELECT result_json FROM operation_checkpoints WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            return json.loads(row["result_json"]) if row is not None else None

    def begin_tool_call(
        self,
        *,
        operation_id: str,
        request_id: str,
        turn_id: str,
        tool_call_id: str,
        tool_name: str,
    ) -> ToolCallRecord:
        """Record a model mutation before its domain action begins.

        The operation ID is backend-generated, so disagreement on any correlated
        field signals a programming/integration error rather than a retry.
        """

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tool_call_records WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is not None:
                record = self._tool_call_record_from_row(row)
                identity = (
                    record.request_id,
                    record.turn_id,
                    record.tool_call_id,
                    record.tool_name,
                )
                proposed = (request_id, turn_id, tool_call_id, tool_name)
                if identity != proposed:
                    raise RequestStoreError(
                        f"Operation ID already belongs to a different tool call: {operation_id}"
                    )
                return record
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO tool_call_records (
                    operation_id, request_id, turn_id, tool_call_id, tool_name, state, created_at
                ) VALUES (?, ?, ?, ?, ?, 'in_progress', ?)
                """,
                (operation_id, request_id, turn_id, tool_call_id, tool_name, now),
            )
            return self._tool_call_record_from_row(
                connection.execute(
                    "SELECT * FROM tool_call_records WHERE operation_id = ?", (operation_id,)
                ).fetchone()
            )

    def get_tool_call_record(self, operation_id: str) -> ToolCallRecord | None:
        """Read one durable model-tool operation record for UI/audit tooling."""

        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM tool_call_records WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            return self._tool_call_record_from_row(row) if row is not None else None

    def record_operation_result(
        self,
        *,
        operation_id: str,
        request_id: str,
        turn_id: str,
        tool_call_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a model-originated operation checkpoint exactly once."""

        serialized = _canonical_json(result)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT result_json FROM operation_checkpoints WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                replayed = json.loads(existing["result_json"])
                self._complete_tool_call_in_transaction(connection, operation_id, replayed)
                return replayed
            connection.execute(
                """
                INSERT INTO operation_checkpoints (
                    operation_id, request_id, turn_id, tool_call_id, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (operation_id, request_id, turn_id, tool_call_id, serialized, _utc_now()),
            )
            self._complete_tool_call_in_transaction(connection, operation_id, result)
            return result

    def _artifact_from_manifest(
        self, manifest: ArtifactManifest, manifest_uri: str
    ) -> ArtifactVersion:
        return ArtifactVersion(
            ref=ArtifactRef(artifact_id=manifest.artifact_id, version=manifest.version),
            workspace_id=manifest.workspace_id,
            artifact_type=manifest.artifact_type,
            schema_version=manifest.artifact_schema_version,
            title=manifest.title,
            summary=manifest.summary,
            created_at=manifest.created_at,
            created_by=manifest.created_by,
            supersedes_version=manifest.supersedes_version,
            content=manifest.content,
            intrinsic_links=manifest.intrinsic_links,
            provenance=manifest.provenance,
            manifest_uri=manifest_uri,
            manifest_sha256=manifest.manifest_sha256,
            files=manifest.files,
        )

    def _insert_artifact_version(
        self, connection: sqlite3.Connection, artifact: ArtifactVersion
    ) -> None:
        connection.execute(
            """
            INSERT INTO artifact_versions (
                workspace_id, artifact_id, version, artifact_type, schema_version,
                title, summary, created_at, created_by, supersedes_version,
                content_json, intrinsic_links_json, provenance_json, manifest_uri, manifest_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.workspace_id,
                artifact.ref.artifact_id,
                artifact.ref.version,
                artifact.artifact_type,
                artifact.schema_version,
                artifact.title,
                artifact.summary,
                artifact.created_at.isoformat(),
                artifact.created_by,
                artifact.supersedes_version,
                _canonical_json(artifact.content),
                _canonical_json(
                    [link.model_dump(mode="json") for link in artifact.intrinsic_links]
                ),
                _canonical_json(artifact.provenance),
                artifact.manifest_uri,
                artifact.manifest_sha256,
            ),
        )
        for file in artifact.files:
            connection.execute(
                """
                INSERT INTO artifact_files (
                    workspace_id, artifact_id, version, uri, mime_type, size_bytes, sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.workspace_id,
                    artifact.ref.artifact_id,
                    artifact.ref.version,
                    file.uri,
                    file.mime_type,
                    file.size_bytes,
                    file.sha256,
                ),
            )

    @staticmethod
    def _links_for_artifact(artifact: ArtifactVersion) -> list[ArtifactLinkDraft]:
        links = list(artifact.intrinsic_links)
        if artifact.supersedes_version is not None:
            links.append(
                ArtifactLinkDraft(
                    relation="supersedes",
                    target=ArtifactRef(
                        artifact_id=artifact.ref.artifact_id,
                        version=artifact.supersedes_version,
                    ),
                    intrinsic=True,
                )
            )
        return links

    def _validate_artifact_links(
        self,
        connection: sqlite3.Connection,
        artifact: ArtifactVersion,
    ) -> None:
        """Reject dangling, self-referential, or cyclic typed dependencies before insertion."""

        existing_edges = self._impact_edges(connection, workspace_id=artifact.workspace_id)
        for link in self._links_for_artifact(artifact):
            if link.target == artifact.ref:
                raise ArtifactVersionConflict("Artifact cannot link to itself")
            target = connection.execute(
                """
                SELECT artifact_type FROM artifact_versions
                WHERE workspace_id = ? AND artifact_id = ? AND version = ?
                """,
                (artifact.workspace_id, link.target.artifact_id, link.target.version),
            ).fetchone()
            if target is None:
                raise ArtifactVersionConflict(
                    f"Artifact link target does not exist: {link.target.key}"
                )
            if link.relation == "supersedes" and target["artifact_type"] != artifact.artifact_type:
                raise ArtifactVersionConflict(
                    "An artifact version may only supersede the same artifact type"
                )
            if would_create_propagating_cycle(
                source=artifact.ref,
                target=link.target,
                relation=link.relation,
                existing=existing_edges,
            ):
                raise ArtifactVersionConflict("Intrinsic dependency links may not create a cycle")
            existing_edges.append(
                ImpactEdge(source=artifact.ref, target=link.target, relation=link.relation)
            )

    def _validate_domain_content_refs(
        self,
        connection: sqlite3.Connection,
        artifact: ArtifactVersion,
    ) -> None:
        """Validate exact current-model references without planning or renderer objects."""

        required: list[tuple[ArtifactRef, set[str], str]] = []
        required_links: list[tuple[str, ArtifactRef, str]] = []
        if artifact.artifact_type == "claim":
            content = ClaimContent.model_validate(artifact.content)
            required.extend(
                (item.paper_ref, {"paper"}, "Claim evidence paper_ref") for item in content.evidence
            )
            required_links.extend(
                ("derived_from", item.paper_ref, "Claim evidence paper_ref")
                for item in content.evidence
            )
        elif artifact.artifact_type == "observation":
            content = ObservationContent.model_validate(artifact.content)
            required.extend((ref, set(), "Observation source_ref") for ref in content.source_refs)
            required_links.extend(
                ("derived_from", ref, "Observation source_ref") for ref in content.source_refs
            )
        elif artifact.artifact_type == "hypothesis":
            content = HypothesisContent.model_validate(artifact.content)
            required.extend(
                (ref, set(), "Hypothesis evidence_ref") for ref in content.evidence_refs
            )
            required_links.extend(
                ("motivates", ref, "Hypothesis evidence_ref") for ref in content.evidence_refs
            )
        elif artifact.artifact_type == "experiment":
            content = ExperimentContent.model_validate(artifact.content)
            required.append((content.hypothesis_ref, {"hypothesis"}, "Experiment hypothesis_ref"))
            required.extend(
                (ref, {"dataset"}, "Experiment input_ref") for ref in content.input_refs
            )
            required.extend(
                (
                    ref,
                    {"interactive_view", "observation", "report"},
                    "Experiment result_ref",
                )
                for ref in content.result_refs
            )
            required_links.append(
                ("tests_hypothesis", content.hypothesis_ref, "Experiment hypothesis_ref")
            )
            required_links.extend(
                ("uses_dataset", ref, "Experiment input_ref") for ref in content.input_refs
            )
            required_links.extend(
                ("derived_from", ref, "Experiment result_ref") for ref in content.result_refs
            )
        elif artifact.artifact_type == "decision":
            content = DecisionContent.model_validate(artifact.content)
            required.extend((ref, set(), "Decision subject_ref") for ref in content.subject_refs)
        elif artifact.artifact_type == "interactive_view":
            content = InteractiveViewContent.model_validate(artifact.content)
            required.extend(
                (ref, {"dataset"}, "Interactive view dataset_ref") for ref in content.dataset_refs
            )
            required_links.extend(
                ("uses_dataset", ref, "Interactive view dataset_ref")
                for ref in content.dataset_refs
            )
        elif artifact.artifact_type == "report":
            content = ReportContent.model_validate(artifact.content)
            required.extend((ref, set(), "Report artifact_ref") for ref in content.artifact_refs)
            required_links.extend(
                ("included_in_report", ref, "Report artifact_ref") for ref in content.artifact_refs
            )

        for ref, allowed_types, label in required:
            target = self._require_artifact(
                connection, artifact.workspace_id, ref.artifact_id, ref.version
            )
            if allowed_types and target.artifact_type not in allowed_types:
                expected = ", ".join(sorted(allowed_types))
                raise ArtifactVersionConflict(
                    f"{label} must reference {expected}, found {target.artifact_type}: {ref.key}"
                )
        intrinsic_links = {
            (link.relation, link.target) for link in artifact.intrinsic_links if link.intrinsic
        }
        for relation, ref, label in required_links:
            if (relation, ref) not in intrinsic_links:
                raise ArtifactVersionConflict(
                    f"{label} requires an intrinsic {relation} link to {ref.key}"
                )

    def _insert_artifact_links(
        self,
        connection: sqlite3.Connection,
        artifact: ArtifactVersion,
        *,
        source_event_id: str,
    ) -> None:
        for link in self._links_for_artifact(artifact):
            connection.execute(
                """
                INSERT INTO artifact_links (
                    workspace_id, source_artifact_id, source_version,
                    target_artifact_id, target_version, relation, intrinsic,
                    created_at, source_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.workspace_id,
                    artifact.ref.artifact_id,
                    artifact.ref.version,
                    link.target.artifact_id,
                    link.target.version,
                    link.relation,
                    int(link.intrinsic),
                    _utc_now(),
                    source_event_id,
                ),
            )

    def _mark_superseded(
        self,
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        artifact_id: str,
        version: int,
        source_event_id: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT * FROM artifact_projections
            WHERE workspace_id = ? AND artifact_id = ? AND version = ?
            """,
            (workspace_id, artifact_id, version),
        ).fetchone()
        if row is None:
            raise ArtifactVersionConflict(
                f"Superseded version does not exist: {artifact_id}@v{version:04d}"
            )
        projection = self._projection_from_row(row).model_copy(
            update={
                "lifecycle_state": "superseded",
                "updated_at": datetime.now(timezone.utc),
                "source_event_id": source_event_id,
            }
        )
        self._upsert_projection(connection, projection, workspace_id=workspace_id)

    def _rebuild_impact_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
    ) -> dict[ArtifactRef, ArtifactProjection]:
        rows = connection.execute(
            """
            SELECT p.*, v.artifact_id AS version_artifact_id
            FROM artifact_projections AS p
            JOIN artifact_versions AS v
              ON v.workspace_id = p.workspace_id
             AND v.artifact_id = p.artifact_id
             AND v.version = p.version
            WHERE p.workspace_id = ?
            """,
            (workspace_id,),
        ).fetchall()
        state_rows = connection.execute(
            """
            SELECT * FROM artifact_state_events
            WHERE workspace_id = ? AND active = 1 ORDER BY created_at, state_event_id
            """,
            (workspace_id,),
        ).fetchall()
        state_inputs: dict[ArtifactRef, dict[str, sqlite3.Row]] = {}
        for row in state_rows:
            ref = ArtifactRef(artifact_id=row["artifact_id"], version=int(row["version"]))
            state_inputs.setdefault(ref, {})[row["kind"]] = row
        projections: dict[ArtifactRef, ArtifactProjection] = {}
        for row in rows:
            projection = self._projection_from_row(row)
            projections[projection.ref] = projection
        nodes: list[ImpactNode] = []
        for ref, projection in projections.items():
            inputs = state_inputs.get(ref, {})
            event_row = inputs.get("decision_invalidated") or inputs.get("source_unavailable")
            nodes.append(
                ImpactNode(
                    ref=ref,
                    lifecycle_state=projection.lifecycle_state,
                    source_unavailable="source_unavailable" in inputs,
                    decision_invalidated="decision_invalidated" in inputs,
                    source_event_id=(
                        event_row["source_event_id"]
                        if event_row is not None
                        else projection.source_event_id
                    ),
                )
            )
        impacts = rebuild_impact(nodes, self._impact_edges(connection, workspace_id=workspace_id))
        rebuilt: dict[ArtifactRef, ArtifactProjection] = {}
        for ref, existing in projections.items():
            impact = impacts[ref]
            projection = existing.model_copy(
                update={
                    "impact_state": impact.state,
                    "impact_reasons": impact.reasons,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self._upsert_projection(connection, projection, workspace_id=workspace_id)
            rebuilt[ref] = projection
        return rebuilt

    @staticmethod
    def _impact_edges(connection: sqlite3.Connection, *, workspace_id: str) -> list[ImpactEdge]:
        rows = connection.execute(
            """
            SELECT source_artifact_id, source_version, target_artifact_id, target_version, relation
            FROM artifact_links WHERE workspace_id = ? ORDER BY link_id
            """,
            (workspace_id,),
        ).fetchall()
        return [
            ImpactEdge(
                source=ArtifactRef(
                    artifact_id=row["source_artifact_id"], version=int(row["source_version"])
                ),
                target=ArtifactRef(
                    artifact_id=row["target_artifact_id"], version=int(row["target_version"])
                ),
                relation=row["relation"],
            )
            for row in rows
        ]

    @staticmethod
    def _upsert_projection(
        connection: sqlite3.Connection,
        projection: ArtifactProjection,
        *,
        workspace_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO artifact_projections (
                workspace_id, artifact_id, version, lifecycle_state,
                impact_state, impact_reasons_json, updated_at, source_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, artifact_id, version) DO UPDATE SET
                lifecycle_state = excluded.lifecycle_state,
                impact_state = excluded.impact_state,
                impact_reasons_json = excluded.impact_reasons_json,
                updated_at = excluded.updated_at,
                source_event_id = excluded.source_event_id
            """,
            (
                workspace_id,
                projection.ref.artifact_id,
                projection.ref.version,
                projection.lifecycle_state,
                projection.impact_state,
                _canonical_json(
                    [reason.model_dump(mode="json") for reason in projection.impact_reasons]
                ),
                projection.updated_at.isoformat(),
                projection.source_event_id,
            ),
        )

    def _require_artifact(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        artifact_id: str,
        version: int,
    ) -> ArtifactVersion:
        row = connection.execute(
            """
            SELECT * FROM artifact_versions
            WHERE workspace_id = ? AND artifact_id = ? AND version = ?
            """,
            (workspace_id, artifact_id, version),
        ).fetchone()
        if row is None:
            raise RequestNotFound(f"Artifact version is not found: {artifact_id}@v{version:04d}")
        return self._artifact_from_row(row, connection=connection)

    def _require_projection(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        artifact_id: str,
        version: int,
    ) -> ArtifactProjection:
        row = connection.execute(
            """
            SELECT * FROM artifact_projections
            WHERE workspace_id = ? AND artifact_id = ? AND version = ?
            """,
            (workspace_id, artifact_id, version),
        ).fetchone()
        if row is None:
            raise RequestNotFound(f"Artifact projection is not found: {artifact_id}@v{version:04d}")
        return self._projection_from_row(row)

    @staticmethod
    def _workspace_revision(connection: sqlite3.Connection, workspace_id: str) -> int:
        row = connection.execute(
            "SELECT revision FROM workspace_records WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            raise RequestStoreError(f"Workspace is not open: {workspace_id}")
        return int(row["revision"])

    @staticmethod
    def _bump_workspace_revision(
        connection: sqlite3.Connection,
        workspace_id: str,
    ) -> tuple[int, int]:
        """Advance a workspace revision inside the enclosing domain mutation transaction."""

        previous_revision = RequestStore._workspace_revision(connection, workspace_id)
        workspace_revision = previous_revision + 1
        connection.execute(
            "UPDATE workspace_records SET revision = ?, updated_at = ? WHERE workspace_id = ?",
            (workspace_revision, _utc_now(), workspace_id),
        )
        return previous_revision, workspace_revision

    @staticmethod
    def _require_research_task_row(connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM research_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFound(f"Unknown research task: {task_id}")
        return row

    @classmethod
    def _require_research_task(
        cls, connection: sqlite3.Connection, task_id: str
    ) -> ResearchTaskRecord:
        return cls._research_task_from_row(cls._require_research_task_row(connection, task_id))

    @staticmethod
    def _require_task_revision(
        task: ResearchTaskRecord, expected_task_revision: int | None
    ) -> None:
        if expected_task_revision is not None and expected_task_revision != task.task_revision:
            raise TaskRevisionConflict(task.task_revision)

    @staticmethod
    def _research_task_from_row(row: sqlite3.Row) -> ResearchTaskRecord:
        return ResearchTaskRecord(
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            status=row["status"],
            task_revision=int(row["task_revision"]),
            active_request_id=row["active_request_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _task_workflow_from_row(row: sqlite3.Row) -> TaskWorkflowRecord:
        return TaskWorkflowRecord(
            request_id=row["request_id"],
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            state=row["state"],
            activity=row["activity"],
            heartbeat_at=row["heartbeat_at"],
            failure_fingerprint=row["failure_fingerprint"],
            repeated_failures=int(row["repeated_failures"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _task_transcript_from_row(row: sqlite3.Row) -> TaskTranscriptItem:
        return TaskTranscriptItem(
            item_id=row["item_id"],
            task_id=row["task_id"],
            sequence=int(row["sequence"]),
            role=row["role"],
            text=row["text"],
            request_id=row["request_id"],
            turn_id=row["turn_id"],
            tool_call_id=row["tool_call_id"],
            interrupted=bool(row["interrupted"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _last_assistant_text(messages: tuple[dict[str, Any], ...]) -> str:
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            text = "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
            if text:
                if len(text) <= 8_000:
                    return text
                return text[:4_000] + "\n... [middle omitted] ...\n" + text[-4_000:]
        return ""

    @staticmethod
    def _clear_task_active_request_in_connection(
        connection: sqlite3.Connection,
        *,
        task_id: str,
        request_id: str,
    ) -> None:
        connection.execute(
            """
            UPDATE research_tasks
            SET active_request_id = NULL, task_revision = task_revision + 1, updated_at = ?
            WHERE task_id = ? AND active_request_id = ?
            """,
            (_utc_now(), task_id, request_id),
        )

    @staticmethod
    def _mark_task_transcript_interrupted_in_connection(
        connection: sqlite3.Connection,
        *,
        task_id: str,
        request_id: str,
    ) -> None:
        connection.execute(
            """
            UPDATE task_transcript_items
            SET interrupted = 1
            WHERE task_id = ? AND request_id = ?
            """,
            (task_id, request_id),
        )

    @staticmethod
    def _require_intent_row(connection: sqlite3.Connection, operation_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM artifact_commit_intents WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        if row is None:
            raise ArtifactCommitNotFound(f"Artifact commit intent is not found: {operation_id}")
        return row

    @staticmethod
    def _intent_from_row(row: sqlite3.Row) -> ArtifactCommitIntent:
        return ArtifactCommitIntent(
            operation_id=row["operation_id"],
            request_id=row["request_id"],
            origin_request_id=row["origin_request_id"],
            task_id=row["task_id"],
            task_relation=row["task_relation"],
            workspace_id=row["workspace_id"],
            artifact_id=row["artifact_id"],
            version=int(row["version"]),
            expected_workspace_revision=row["expected_workspace_revision"],
            staging_uri=row["staging_uri"],
            target_uri=row["target_uri"],
            manifest=ArtifactManifest.model_validate_json(row["manifest_json"]),
            status=row["status"],
            quarantine_uri=row["quarantine_uri"],
            committed_event_id=row["committed_event_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _tool_call_record_from_row(row: sqlite3.Row) -> ToolCallRecord:
        return ToolCallRecord(
            operation_id=row["operation_id"],
            request_id=row["request_id"],
            turn_id=row["turn_id"],
            tool_call_id=row["tool_call_id"],
            tool_name=row["tool_name"],
            state=row["state"],
            result=json.loads(row["result_json"]) if row["result_json"] is not None else None,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _complete_tool_call_in_transaction(
        connection: sqlite3.Connection,
        operation_id: str,
        result: dict[str, Any],
    ) -> None:
        """Complete a record when this operation was started through a model tool."""

        connection.execute(
            """
            UPDATE tool_call_records
            SET state = 'completed', result_json = ?, completed_at = ?
            WHERE operation_id = ?
            """,
            (_canonical_json(result), _utc_now(), operation_id),
        )

    @staticmethod
    def _close_active_tool_calls_in_transaction(
        connection: sqlite3.Connection,
        *,
        request_id: str,
        terminal_event_type: str,
    ) -> None:
        """Converge audit/UI state when a request reaches any terminal event.

        A process interruption between the domain action and the model-tool
        receipt must not leave a permanent ``in_progress`` operation.  This is
        lifecycle cleanup only; it never replays or invents a domain mutation.
        """

        result = {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "The parent request reached a terminal state before this tool "
                        "receipt completed."
                    ),
                }
            ],
            "is_error": True,
            "metadata": {
                "request_terminal": True,
                "terminal_event_type": terminal_event_type,
            },
        }
        connection.execute(
            """
            UPDATE tool_call_records
            SET state = 'completed', result_json = ?, completed_at = ?
            WHERE request_id = ? AND state = 'in_progress'
            """,
            (_canonical_json(result), _utc_now(), request_id),
        )

    def _artifact_from_row(
        self,
        row: sqlite3.Row,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> ArtifactVersion:
        active_connection = connection or self._connection
        file_rows = active_connection.execute(
            """
            SELECT uri, mime_type, size_bytes, sha256 FROM artifact_files
            WHERE workspace_id = ? AND artifact_id = ? AND version = ? ORDER BY uri
            """,
            (row["workspace_id"], row["artifact_id"], row["version"]),
        ).fetchall()
        return ArtifactVersion(
            ref=ArtifactRef(artifact_id=row["artifact_id"], version=int(row["version"])),
            workspace_id=row["workspace_id"],
            artifact_type=row["artifact_type"],
            schema_version=row["schema_version"],
            title=row["title"],
            summary=row["summary"],
            created_at=datetime.fromisoformat(row["created_at"]),
            created_by=row["created_by"],
            supersedes_version=row["supersedes_version"],
            content=json.loads(row["content_json"]),
            intrinsic_links=tuple(
                ArtifactLinkDraft.model_validate(item)
                for item in json.loads(row["intrinsic_links_json"])
            ),
            provenance=json.loads(row["provenance_json"]),
            manifest_uri=row["manifest_uri"],
            manifest_sha256=row["manifest_sha256"],
            files=tuple(
                ArtifactFile(
                    uri=file_row["uri"],
                    mime_type=file_row["mime_type"],
                    size_bytes=int(file_row["size_bytes"]),
                    sha256=file_row["sha256"],
                )
                for file_row in file_rows
            ),
        )

    @staticmethod
    def _projection_from_row(row: sqlite3.Row) -> ArtifactProjection:
        return ArtifactProjection(
            ref=ArtifactRef(artifact_id=row["artifact_id"], version=int(row["version"])),
            lifecycle_state=row["lifecycle_state"],
            impact_state=row["impact_state"],
            impact_reasons=tuple(
                ImpactHop.model_validate(item) for item in json.loads(row["impact_reasons_json"])
            ),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source_event_id=row["source_event_id"],
        )

    def _artifact_summary_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        projection = self._projection_from_row(row)
        return {
            "ref": {"artifact_id": row["artifact_id"], "version": int(row["version"])},
            "artifact_type": row["artifact_type"],
            "title": row["title"],
            "summary": row["summary"],
            "projection": projection.model_dump(mode="json"),
        }

    def _persist_event(self, connection: sqlite3.Connection, event: EventEnvelope) -> None:
        connection.execute(
            """
            INSERT INTO event_records (event_id, request_id, workspace_id, event_type, event_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.request_id,
                event.workspace_id,
                event.type,
                event.model_dump_json(),
                _utc_now(),
            ),
        )

    def _commit_terminal_in_transaction(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        event: EventEnvelope,
    ) -> None:
        if event.type not in TERMINAL_EVENT_TYPES:
            raise RequestStoreError(f"Cannot commit non-terminal event {event.type}")
        if event.request_id != request_id:
            raise RequestStoreError("Terminal event request ID does not match the durable request")
        record = self._request_from_row(self._require_request_row(connection, request_id))
        if record.terminal:
            raise RequestStoreError(f"Request is already terminal: {request_id}")
        self._close_active_tool_calls_in_transaction(
            connection,
            request_id=request_id,
            terminal_event_type=event.type,
        )
        self._persist_event(connection, event)
        connection.execute(
            """
            UPDATE request_records
            SET state = ?, terminal_event_json = ?, terminal_event_id = ?, updated_at = ?
            WHERE request_id = ?
            """,
            (
                _state_for_terminal_event(event),
                event.model_dump_json(),
                event.event_id,
                _utc_now(),
                request_id,
            ),
        )

    def _ensure_nonterminal_request(
        self, connection: sqlite3.Connection, request_id: str
    ) -> RequestRecord:
        record = self._request_from_row(self._require_request_row(connection, request_id))
        if record.terminal:
            raise RequestStoreError(f"Request is already terminal: {request_id}")
        return record

    @staticmethod
    def _require_request_row(connection: sqlite3.Connection, request_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM request_records WHERE request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise RequestNotFound(f"Unknown request: {request_id}")
        return row

    @staticmethod
    def _require_interaction_row(
        connection: sqlite3.Connection, interaction_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM task_interactions WHERE interaction_id = ?", (interaction_id,)
        ).fetchone()
        if row is None:
            raise RequestNotFound("Interaction is not found")
        return row

    @staticmethod
    def _interaction_from_row(row: sqlite3.Row) -> PendingInteractionRecord:
        return PendingInteractionRecord(
            interaction_id=row["interaction_id"],
            request_id=row["request_id"],
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            principal=row["principal"],
            kind=row["kind"],
            question=row["question"],
            options=tuple(json.loads(row["options_json"])),
            state=row["state"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    @classmethod
    def _pending_interactions_in_connection(
        cls, connection: sqlite3.Connection, task_id: str
    ) -> list[PendingInteractionRecord]:
        rows = connection.execute(
            "SELECT * FROM task_interactions WHERE task_id = ? AND state = 'pending' ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [cls._interaction_from_row(row) for row in rows]

    @staticmethod
    def _interrupt_interactions_for_request_in_connection(
        connection: sqlite3.Connection, request_id: str
    ) -> None:
        connection.execute(
            "UPDATE task_interactions SET state = 'interrupted', resolved_at = ? WHERE request_id = ? AND state = 'pending'",
            (_utc_now(), request_id),
        )

    @staticmethod
    def _code_execution_from_row(row: sqlite3.Row) -> CodeExecutionRecord:
        return CodeExecutionRecord(
            execution_id=row["execution_id"],
            workspace_id=row["workspace_id"],
            task_id=row["task_id"],
            agent_thread_id=row["agent_thread_id"],
            server_run_id=row["server_run_id"],
            state=row["state"],
            request=json.loads(row["request_json"]),
            result=(json.loads(row["result_json"]) if row["result_json"] is not None else None),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
        )

    @staticmethod
    def _request_from_row(row: sqlite3.Row) -> RequestRecord:
        terminal_json = row["terminal_event_json"]
        return RequestRecord(
            request_id=row["request_id"],
            request_type=row["request_type"],
            canonical_hash=row["canonical_hash"],
            canonical_request=json.loads(row["canonical_request_json"]),
            principal=row["principal"],
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            task_id=row["task_id"],
            state=row["state"],
            terminal_event=parse_event(json.loads(terminal_json)) if terminal_json else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


__all__ = [
    "ACTIVE_REQUEST_STATES",
    "ActiveRefCommit",
    "ArtifactCommit",
    "ArtifactCommitIntent",
    "ArtifactCommitNotFound",
    "ArtifactVersionConflict",
    "CancellationCommit",
    "DisclosurePolicyCommit",
    "PendingInteractionRecord",
    "RequestIdConflict",
    "RequestNotFound",
    "RequestRecord",
    "RequestReservation",
    "RequestStore",
    "RequestStoreError",
    "ToolCallRecord",
    "TERMINAL_REQUEST_STATES",
    "WorkspaceOpenCommit",
    "WorkspaceRevisionConflict",
    "WorkspaceSnapshot",
]

"""Protocol v2 request router with durable terminal-event semantics."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import stat
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import ValidationError

from oceanx import __version__
from oceanx.agent import (
    OceanAgentRuntime,
    OceanAgentRuntimeError,
    OceanAgentRuntimeFactory,
    build_default_ocean_agent_runtime,
    configured_model_id,
    configured_provider_id,
)
from oceanx.agent_contract import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from oceanx.artifacts.files import ArtifactFileError
from oceanx.artifacts.models import (
    ArtifactRef,
    ArtifactVersionDraft,
    PaperContent,
)
from oceanx.artifacts.service import ArtifactService
from oceanx.backend.auth import principal_for_client_kind, required_capability
from oceanx.backend.events import BackendClient, EventBus
from oceanx.backend.store import (
    ArtifactVersionConflict,
    RequestIdConflict,
    RequestNotFound,
    RequestRecord,
    RequestStore,
    RequestStoreError,
    TaskNotFound,
    TaskRevisionConflict,
    TaskWorkflowState,
    WorkspaceRevisionConflict,
    WorkspaceSnapshot,
)
from oceanx.context import ModelDataDisclosurePolicy
from oceanx.desktop_contract import DESKTOP_BACKEND_SCHEMA
from oceanx.doctor import desktop_runtime_capabilities
from oceanx.expert_deliverables import (
    ExpertDeliverableError,
    interactive_view_cache,
)
from oceanx.exports import PortableExportError, PortableExportService
from oceanx.protocol.v2.models import (
    ArtifactCreatedEvent,
    ArtifactCreatedPayload,
    ArtifactCreateRequest,
    ArtifactGetRequest,
    ArtifactListRequest,
    ArtifactResourceGrantRequest,
    ArtifactSummaryPayload,
    ArtifactVersionCreatedEvent,
    ArtifactVersionsRequest,
    AssistantDeltaEvent,
    AssistantDeltaPayload,
    AssistantTurnCompletedEvent,
    AssistantTurnCompletedPayload,
    ContextCompactionProgressEvent,
    ContextCompactionProgressPayload,
    DatasetImportRequest,
    DisclosurePolicyGetRequest,
    DisclosurePolicySetRequest,
    DisclosurePolicySummary,
    ResearchLibraryGetRequest,
    ResearchLibraryMarkRequest,
    ResearchLibraryUpdateRequest,
    DisclosurePolicyUpdatedEvent,
    DisclosurePolicyUpdatedPayload,
    ErrorCode,
    EventEnvelope,
    HypothesisActivateRequest,
    InteractionRequestedEvent,
    InteractionRequestedPayload,
    InteractionRespondRequest,
    LocalSourceImportRequest,
    PaperImportRequest,
    PaperRegisterRequest,
    PortableExportCreateRequest,
    ProtocolErrorPayload,
    RequestAcceptedEvent,
    RequestAcceptedPayload,
    RequestCancelledEvent,
    RequestCancelledPayload,
    RequestCancelRequest,
    RequestCompletedEvent,
    RequestCompletedPayload,
    RequestEnvelope,
    RequestFailedEvent,
    RequestFailedPayload,
    RequestStatusGetRequest,
    SessionOpenRequest,
    SessionSubmitRequest,
    SystemErrorEvent,
    SystemErrorPayload,
    SystemHandshakeRequest,
    SystemReadyEvent,
    SystemReadyPayload,
    SystemShutdownEvent,
    SystemShutdownPayload,
    SystemShutdownRequest,
    TaskAgentTranscriptGetRequest,
    TaskReportReadRequest,
    TaskArchiveRequest,
    TaskCreateRequest,
    TaskDeleteRequest,
    TaskGetRequest,
    TaskListRequest,
    TaskOutputListRequest,
    TaskRenameRequest,
    TaskResultInteractiveViewGetRequest,
    TaskResultResourceGrantRequest,
    TaskSnapshotEvent,
    TaskSnapshotGetRequest,
    TaskSnapshotPayload,
    TeamAgentPayload,
    TeamAgentProfilePayload,
    TeamDependencyPayload,
    TeamInteractionPayload,
    TeamSnapshotEvent,
    TeamSnapshotPayload,
    TeamTodoPayload,
    ToolCallCompletedEvent,
    ToolCallCompletedPayload,
    ToolCallStartedEvent,
    ToolCallStartedPayload,
    TranscriptItemAppendedEvent,
    TranscriptItemAppendedPayload,
    WorkspaceChangedEvent,
    WorkspaceChangedPayload,
    WorkspaceOpenRequest,
    WorkspaceSnapshotEvent,
    WorkspaceSnapshotGetRequest,
    WorkspaceSnapshotPayload,
    new_event_id,
    parse_request,
)
from oceanx.research.services import ResearchServices
from oceanx.skills import LITERATURE_CAPABILITY
from oceanx.storage import is_safe_cross_platform_relative_path
from oceanx.task_results import TaskResultError, TaskResultStore
from oceanx.task_workspace import TaskWorkspaceProjector
from oceanx.team.models import (
    CoordinatorResult,
    EvidenceRef,
)
from oceanx.team.profiles import AGENT_PROFILES
from oceanx.tools import OceanToolServices


def _local_dataset_format(path: Path) -> str:
    """Return a non-authoritative format hint; unknown formats remain importable."""

    if path.is_dir():
        if any(
            (path / marker).is_file()
            for marker in (".zgroup", ".zarray", ".zmetadata", "zarr.json")
        ):
            return "zarr"
        return "directory"
    suffix = path.suffix.lower()
    aliases = {
        ".nc": "netcdf",
        ".nc4": "netcdf",
        ".cdf": "netcdf",
        ".tif": "geotiff",
        ".tiff": "geotiff",
        ".grb": "grib",
        ".grb2": "grib",
        ".grib": "grib",
        ".grib2": "grib",
        ".h5": "hdf5",
        ".hdf": "hdf5",
        ".hdf5": "hdf5",
    }
    return aliases.get(suffix, suffix.lstrip(".") or "unknown")


_LOGGER = logging.getLogger(__name__)


class CrashAfterTerminalCommit(RuntimeError):
    """Test-only crash seam for the commit-before-broadcast recovery contract."""


TerminalCommitHook = Callable[[EventEnvelope], Awaitable[None] | None]


@dataclass
class _AgentSession:
    """One cached model conversation tied to one authenticated Ocean session."""

    session_id: str
    runtime_key: str
    workspace_id: str
    task_id: str | None
    runtime: OceanAgentRuntime


async def _coordinator_events(engine, text: str, request_id: str):
    """Project the native server stream; model retries belong inside the graph."""
    stream = engine.submit_message(text, request_id=request_id)
    try:
        async for event in stream:
            yield event
    finally:
        await stream.aclose()


class OceanRequestRouter:
    """Route validated envelopes while keeping authority and durability server-side."""

    def __init__(
        self,
        *,
        store: RequestStore,
        event_bus: EventBus,
        artifact_service: ArtifactService | None = None,
        portable_export_service: PortableExportService | None = None,
        research_services: ResearchServices | None = None,
        agent_runtime_factory: OceanAgentRuntimeFactory | None = None,
        provider_id_resolver: Callable[[], str] = configured_provider_id,
        model_id_resolver: Callable[[], str] | None = None,
        after_terminal_commit: TerminalCommitHook | None = None,
        task_workspace_projector: TaskWorkspaceProjector | None = None,
        task_results: TaskResultStore | None = None,
    ) -> None:
        self.store = store
        self.event_bus = event_bus
        self.artifact_service = artifact_service
        self.portable_export_service = portable_export_service
        self.research_services = research_services
        self.agent_runtime_factory = agent_runtime_factory or build_default_ocean_agent_runtime
        self.provider_id_resolver = provider_id_resolver
        # Production sessions must be rebuilt when the user changes only the
        # Coordinator model under the same provider. Injected runtimes keep
        # their own lifecycle contract and therefore opt in explicitly.
        self.model_id_resolver = model_id_resolver
        if (
            model_id_resolver is None
            and agent_runtime_factory is None
            and provider_id_resolver is configured_provider_id
        ):
            self.model_id_resolver = configured_model_id
        self.after_terminal_commit = after_terminal_commit
        self.task_workspace_projector = task_workspace_projector
        self.task_results = task_results
        self.shutdown_requested = False
        self._agent_sessions: dict[str, _AgentSession] = {}
        self._agent_tasks: dict[str, asyncio.Task[None]] = {}
        self._agent_request_sessions: dict[str, str] = {}
        self._agent_request_clients: dict[str, BackendClient] = {}
        self._team_snapshot_revisions: dict[str, int] = {}
        # UI projection of native synchronous ``task`` calls. This is not a
        # scheduler or source of truth; execution and completion remain inside
        # DeepAgents and the durable products are report.md/.nc files.
        self._native_task_activity: dict[str, dict[str, dict[str, Any]]] = {}
        # Internal callers such as the frozen evaluator can lower a single
        # follow-up request's remaining budget without changing the user-facing
        # Protocol v2 payload or the router-wide default.
        self._cancelling_agent_requests: set[str] = set()
        self._pending_questions: dict[str, tuple[str, str, asyncio.Future[str]]] = {}
        # "Update now" requests that run off the connection's request loop.
        self._library_updates: set[asyncio.Task[None]] = set()
        # One writer of the project's lessons and tools at a time: "Update now", the regular
        # upkeep and a mark would otherwise overwrite one another's changes.
        self._library_lock = threading.Lock()
        self._closing = False
        self.recovered_events = self.store.recover_incomplete(
            self._interrupted_event,
            self._recovered_completed_event,
        )

    async def handle_payload(self, client: BackendClient, payload: object) -> None:
        """Validate a decoded payload and send a typed error on rejection."""

        try:
            request = parse_request(payload)
        except ValidationError as exc:
            await self._emit_system_error(
                client,
                code="invalid_request",
                message="Request does not satisfy Protocol v2 schema",
                recoverable=True,
                details={
                    "validation": exc.errors(
                        include_url=False,
                        include_context=False,
                        include_input=False,
                    )
                },
            )
            return
        await self.handle(client, request)

    def interrupt_active_requests(self) -> list[EventEnvelope]:
        """Durably terminate work left active when this backend is shutting down."""

        return self.store.recover_incomplete(
            self._interrupted_event,
            self._recovered_completed_event,
        )

    async def shutdown_active_analysis(self) -> None:
        """Stop every foreground operation before request recovery closes the backend."""

        self._closing = True
        for request_id, task in list(self._agent_tasks.items()):
            self._cancelling_agent_requests.add(request_id)
            if not task.done():
                task.cancel()
        tasks = [task for task in self._agent_tasks.values() if not task.done()]
        for task in list(self._library_updates):
            # The request stays in progress and is ended by request recovery, like any other.
            if task.cancel():
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        sessions = list(self._agent_sessions.values())
        self._agent_sessions.clear()
        for session in sessions:
            await session.runtime.close()

    async def handle(self, client: BackendClient, request: RequestEnvelope) -> None:
        """Process one typed request from a registered transport connection."""

        if request.type == "system.handshake":
            await self._handle_handshake(client, request)
            return
        if not client.authenticated:
            await self._emit_system_error(
                client,
                code="permission_denied",
                message="system.handshake must complete before other requests",
                recoverable=True,
                details={},
                request_id=request.request_id,
            )
            return
        if (
            request.context is None
            or request.context.client_id != client.client_id
            or request.context.session_id != client.session_id
        ):
            await self._emit_system_error(
                client,
                code="permission_denied",
                message="Request context does not belong to this authenticated connection",
                recoverable=True,
                details={},
                request_id=request.request_id,
            )
            return
        client.workspace_id = request.context.workspace_id
        capability = required_capability(request.type)
        if (
            capability is None
            or client.principal is None
            or not client.principal.allows(capability)
        ):
            await self._emit_system_error(
                client,
                code="permission_denied",
                message=f"Authenticated client cannot submit {request.type}",
                recoverable=False,
                details={"required_capability": capability},
                request_id=request.request_id,
            )
            return

        try:
            reservation = self.store.reserve(request, principal=client.principal.key)
        except RequestIdConflict:
            await self._emit_system_error(
                client,
                code="request_id_conflict",
                message="request_id was already used for a different semantic request",
                recoverable=False,
                details={},
                request_id=request.request_id,
            )
            return

        if not reservation.created:
            if reservation.record.principal != client.principal.key:
                await self._emit_system_error(
                    client,
                    code="permission_denied",
                    message="Request replay is not available to this principal",
                    recoverable=False,
                    details={},
                    request_id=request.request_id,
                )
                return
            if reservation.record.terminal_event is not None:
                await self.event_bus.emit_local(client, reservation.record.terminal_event)
            else:
                await self.event_bus.emit_local(
                    client,
                    self._accepted_event(client, request, state="in_progress"),
                )
            return

        await self.event_bus.emit_local(
            client, self._accepted_event(client, request, state="accepted")
        )
        self.store.mark_in_progress(request.request_id)
        try:
            await self._dispatch(client, request)
        except CrashAfterTerminalCommit:
            raise
        except WorkspaceRevisionConflict as exc:
            await self._fail_request(
                client,
                request,
                code="workspace_revision_conflict",
                message="Workspace changed since this request was composed",
                recoverable=True,
                details={"current_workspace_revision": exc.current_revision},
            )
        except TaskRevisionConflict as exc:
            await self._fail_request(
                client,
                request,
                code="task_revision_conflict",
                message="Research task changed since this request was composed",
                recoverable=True,
                details={"current_task_revision": exc.current_revision},
            )
        except TaskNotFound:
            await self._fail_request(
                client,
                request,
                code="task_not_found",
                message="Requested research task was not found",
                recoverable=True,
                details={},
            )
        except ArtifactVersionConflict as exc:
            await self._fail_request(
                client,
                request,
                code="artifact_version_conflict",
                message="Artifact version or dependency relation conflicts with durable workspace state",
                recoverable=True,
                details={"reason": str(exc)},
            )
        except ArtifactFileError as exc:
            await self._fail_request(
                client,
                request,
                code="artifact_commit_failed",
                message="Artifact files could not be staged or finalized safely",
                recoverable=True,
                details={"reason": str(exc)},
            )
        except RequestNotFound:
            await self._fail_request(
                client,
                request,
                code="artifact_not_found",
                message="Requested durable record was not found",
                recoverable=True,
                details={},
            )
        except ValidationError as exc:
            artifact_validation = request.type.startswith("artifact.")
            validation = exc.errors(
                include_url=False, include_context=False, include_input=False,
            )
            fields = ", ".join(
                ".".join(str(part) for part in error["loc"]) or "content"
                for error in validation[:3]
            )
            await self._fail_request(
                client,
                request,
                code="invalid_artifact" if artifact_validation else "store_error",
                message=(
                    "Artifact content does not satisfy its declared schema"
                    if artifact_validation
                    else f"Could not complete {request.type}: {exc.title} validation failed ({fields})"
                ),
                recoverable=True,
                details={
                    "operation": request.type,
                    "model": exc.title,
                    "validation": validation,
                },
            )
        except RequestStoreError as exc:
            await self._fail_request(
                client,
                request,
                code="store_error",
                message="Could not persist the request result",
                recoverable=True,
                details={"reason": str(exc)},
            )
        except Exception as exc:  # pragma: no cover - defensive router boundary
            await self._fail_request(
                client,
                request,
                code="store_error",
                message="Backend request handler failed",
                recoverable=True,
                details={"reason": str(exc)},
            )

    async def _handle_handshake(
        self,
        client: BackendClient,
        request: SystemHandshakeRequest,
    ) -> None:
        if client.authenticated:
            await self._emit_system_error(
                client,
                code="invalid_request",
                message="This connection has already completed system.handshake",
                recoverable=False,
                details={},
                request_id=request.request_id,
            )
            return
        if 2 not in request.payload.supported_protocol_versions:
            await self._emit_system_error(
                client,
                code="unsupported_protocol",
                message="Client does not support Protocol v2",
                recoverable=False,
                details={"supported_by_backend": [2]},
                request_id=request.request_id,
            )
            return
        if request.payload.client_kind != client.expected_client_kind:
            await self._emit_system_error(
                client,
                code="permission_denied",
                message="Client kind does not match this transport",
                recoverable=False,
                details={},
                request_id=request.request_id,
            )
            return
        if not await client.validate_handshake(
            request.payload.bootstrap_token,
            request.payload.client_capability,
        ):
            await self._emit_system_error(
                client,
                code="permission_denied",
                message="Desktop bootstrap token is missing, expired, or already used",
                recoverable=False,
                details={},
                request_id=request.request_id,
            )
            return

        client.client_id = (
            client.resume_client_id or f"client_{client.expected_client_kind}_{uuid4().hex}"
        )
        client.session_id = client.resume_session_id or f"ses_{uuid4().hex}"
        client.workspace_id = client.resume_workspace_id
        client.principal = client.resume_principal or principal_for_client_kind(
            client.expected_client_kind
        )
        event = SystemReadyEvent(
            **self._event_fields(
                client,
                request_id=request.request_id,
                workspace_id=request.context.workspace_id if request.context else None,
            ),
            type="system.ready",
            payload=SystemReadyPayload(
                backend_version=__version__,
                backend_schema=DESKTOP_BACKEND_SCHEMA,
                client_id=client.client_id,
                session_id=client.session_id,
                client_kind=client.expected_client_kind,
                capabilities=sorted(client.principal.capabilities),
                runtime_capabilities=desktop_runtime_capabilities(
                    skill_capabilities=(LITERATURE_CAPABILITY,)
                ),
                client_capability=client.client_capability,
            ),
        )
        await self.event_bus.emit_local(client, event)

    async def _dispatch(self, client: BackendClient, request: RequestEnvelope) -> None:
        if isinstance(request, InteractionRespondRequest):
            await self._interaction_respond(client, request)
            return
        if isinstance(request, TaskCreateRequest):
            await self._task_create(client, request)
            return
        if isinstance(request, TaskListRequest):
            await self._task_list(client, request)
            return
        if isinstance(request, TaskGetRequest):
            await self._task_get_or_open(client, request)
            return
        if isinstance(request, TaskRenameRequest):
            await self._task_rename(client, request)
            return
        if isinstance(request, TaskArchiveRequest):
            await self._task_archive_or_reopen(client, request)
            return
        if isinstance(request, TaskDeleteRequest):
            await self._task_delete(client, request)
            return
        if isinstance(request, TaskSnapshotGetRequest):
            await self._task_snapshot(client, request)
            return
        if isinstance(request, TaskAgentTranscriptGetRequest):
            await self._task_agent_transcript(client, request)
            return
        if isinstance(request, TaskReportReadRequest):
            await self._task_report_read(client, request)
            return
        if isinstance(request, TaskOutputListRequest):
            await self._task_output_list(client, request)
            return
        if isinstance(request, SessionOpenRequest):
            await self._session_open(client, request)
            return
        if isinstance(request, SessionSubmitRequest):
            await self._session_submit(client, request)
            return
        if isinstance(request, WorkspaceOpenRequest):
            await self._workspace_open(client, request)
            return
        if isinstance(request, WorkspaceSnapshotGetRequest):
            await self._workspace_snapshot(client, request)
            return
        if isinstance(request, ArtifactListRequest):
            await self._artifact_list(client, request)
            return
        if isinstance(request, ArtifactGetRequest):
            await self._artifact_get(client, request)
            return
        if isinstance(request, ArtifactResourceGrantRequest):
            await self._artifact_resource_grant(client, request)
            return
        if isinstance(request, TaskResultResourceGrantRequest):
            await self._task_result_resource_grant(client, request)
            return
        if isinstance(request, TaskResultInteractiveViewGetRequest):
            await self._task_result_interactive_view_get(client, request)
            return
        if isinstance(request, ArtifactVersionsRequest):
            await self._artifact_versions(client, request)
            return
        if isinstance(request, ArtifactCreateRequest):
            await self._artifact_create(client, request)
            return
        if isinstance(request, DatasetImportRequest):
            await self._dataset_import(client, request)
            return
        if isinstance(request, LocalSourceImportRequest):
            await self._local_source_import(client, request)
            return
        if isinstance(request, PaperImportRequest):
            await self._paper_import(client, request)
            return
        if isinstance(request, PaperRegisterRequest):
            await self._paper_register(client, request)
            return
        if isinstance(request, HypothesisActivateRequest):
            await self._hypothesis_activate(client, request)
            return
        if isinstance(request, PortableExportCreateRequest):
            await self._portable_export_create(client, request)
            return
        if isinstance(request, ResearchLibraryUpdateRequest):
            self._start_library_update(client, request)
            return
        if isinstance(request, (ResearchLibraryGetRequest, ResearchLibraryMarkRequest)):
            await self._research_library(client, request)
            return
        if isinstance(request, DisclosurePolicyGetRequest):
            await self._disclosure_policy_get(client, request)
            return
        if isinstance(request, DisclosurePolicySetRequest):
            await self._disclosure_policy_set(client, request)
            return
        if isinstance(request, RequestStatusGetRequest):
            await self._request_status(client, request)
            return
        if isinstance(request, RequestCancelRequest):
            await self._request_cancel(client, request)
            return
        if isinstance(request, SystemShutdownRequest):
            await self._system_shutdown(client, request)
            return
        raise RequestStoreError(f"No handler for request type {request.type}")

    async def _artifact_list(self, client: BackendClient, request: ArtifactListRequest) -> None:
        workspace_id = self._workspace_id(request)
        artifacts = self.store.list_artifact_summaries(
            workspace_id,
            artifact_type=request.payload.artifact_type,
            limit=request.payload.limit,
        )
        terminal = self._completed_event(client, request, result={"artifacts": artifacts})
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _artifact_get(self, client: BackendClient, request: ArtifactGetRequest) -> None:
        workspace_id = self._workspace_id(request)
        artifact = self.store.get_artifact(workspace_id=workspace_id, ref=request.payload.ref)
        projection = self.store.get_projection(workspace_id=workspace_id, ref=request.payload.ref)
        if artifact is None or projection is None:
            raise RequestNotFound(request.payload.ref.key)
        terminal = self._completed_event(
            client,
            request,
            result={
                "artifact": artifact.model_dump(mode="json"),
                "projection": projection.model_dump(mode="json"),
                "links": {
                    "outgoing": self.store.list_artifact_links(
                        workspace_id=workspace_id,
                        ref=request.payload.ref,
                        direction="outgoing",
                    ),
                    "incoming": self.store.list_artifact_links(
                        workspace_id=workspace_id,
                        ref=request.payload.ref,
                        direction="incoming",
                    ),
                },
            },
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _artifact_resource_grant(
        self, client: BackendClient, request: ArtifactResourceGrantRequest
    ) -> None:
        """Approve one bounded immutable result file for the Desktop viewer path."""

        workspace_id = self._workspace_id(request)
        artifact = self.store.get_artifact(
            workspace_id=workspace_id, ref=request.payload.artifact_ref
        )
        if artifact is None:
            raise RequestNotFound(request.payload.artifact_ref.key)
        file = next(
            (
                item
                for item in artifact.files
                if item.uri.rsplit("/", maxsplit=1)[-1] == request.payload.file_name
            ),
            None,
        )
        if file is None:
            raise RequestStoreError(
                "Requested viewer file is not declared by the artifact manifest"
            )
        policy = {
            "paper_viewer": {
                "artifact_type": "paper",
                "mime_type": "application/pdf",
                "maximum_bytes": 25 * 1024 * 1024,
            },
            "report_viewer": {
                "artifact_type": "report",
                "mime_type": "text/markdown",
                "maximum_bytes": 2 * 1024 * 1024,
            },
            "report_notebook": {
                "artifact_type": "report",
                "mime_type": "application/x-ipynb+json",
                "maximum_bytes": 5 * 1024 * 1024,
            },
            "report_code": {
                "artifact_type": "report",
                "mime_type": "text/x-python",
                "maximum_bytes": 2 * 1024 * 1024,
            },
            "report_environment": {
                "artifact_type": "report",
                "mime_type": "text/plain",
                "maximum_bytes": 512 * 1024,
            },
            "report_inputs": {
                "artifact_type": "report",
                "mime_type": "application/json",
                "maximum_bytes": 2 * 1024 * 1024,
            },
            "report_reproducibility": {
                "artifact_type": "report",
                "mime_type": "application/json",
                "maximum_bytes": 2 * 1024 * 1024,
            },
            "report_image": {
                "artifact_type": "report",
                "mime_type": "image/png",
                "maximum_bytes": 8 * 1024 * 1024,
            },
            "interactive_view_data": {
                "artifact_type": "interactive_view",
                "mime_type": "application/json",
                "maximum_bytes": 8 * 1024 * 1024,
            },
            "interactive_view_preview": {
                "artifact_type": "interactive_view",
                "mime_type": "image/png",
                "maximum_bytes": 8 * 1024 * 1024,
            },
        }[request.payload.purpose]
        if (
            artifact.artifact_type != policy["artifact_type"]
            or file.mime_type != policy["mime_type"]
        ):
            raise RequestStoreError("Requested file is not permitted for this viewer purpose")
        if file.size_bytes > policy["maximum_bytes"]:
            raise RequestStoreError("Requested viewer file exceeds the bounded resource limit")
        terminal = self._completed_event(
            client,
            request,
            result={
                "resource_token": f"res_{uuid4().hex}",
                "resource_uri": file.uri,
                "artifact_ref": artifact.ref.model_dump(mode="json"),
                "file_name": request.payload.file_name,
                "mime_type": file.mime_type,
                "size_bytes": file.size_bytes,
                "sha256": file.sha256,
                "purpose": request.payload.purpose,
            },
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _artifact_versions(
        self, client: BackendClient, request: ArtifactVersionsRequest
    ) -> None:
        """Return a version timeline without loading mutable local files into the protocol."""

        workspace_id = self._workspace_id(request)
        versions = self.store.list_artifact_versions(
            workspace_id=workspace_id,
            artifact_id=request.payload.artifact_id,
        )
        terminal = self._completed_event(
            client,
            request,
            result={"artifact_id": request.payload.artifact_id, "versions": versions},
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _task_result_resource_grant(
        self, client: BackendClient, request: TaskResultResourceGrantRequest
    ) -> None:
        """Grant one declared file directly from a result owned by this task."""

        if self.task_results is None:
            raise RequestStoreError("Task result storage is unavailable")
        ref = request.payload.result_ref
        if request.context.task_id != ref.task_id:
            raise RequestStoreError("Task result does not belong to the current task")
        self._task_in_workspace(ref.task_id, request)
        try:
            result = self.task_results.get(ref)
            path = self.task_results.file_path(ref=ref, relative_path=request.payload.file_name)
        except TaskResultError as exc:
            raise RequestNotFound(ref.key) from exc
        if result.workspace_id != self._workspace_id(request):
            raise RequestStoreError("Task result does not belong to the current workspace")
        declared = next(
            (item for item in result.files if item.path == request.payload.file_name),
            None,
        )
        if declared is None:
            raise RequestStoreError("Requested file is not declared by the task result")
        workspace_files = result.content.get("workspace_files")
        mutable_workspace_file = (
            isinstance(workspace_files, dict)
            and request.payload.file_name in workspace_files
        )
        current_size = path.stat().st_size if mutable_workspace_file else declared.size
        if mutable_workspace_file:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            current_sha256 = digest.hexdigest()
        else:
            current_sha256 = declared.sha256
        # The manifest declares which file may be opened. Mutable supplementary
        # files use their current size/hash because the user is expected to edit
        # them; accepted scientific payloads retain the manifest checksum.
        if current_size > 25 * 1024 * 1024:
            raise RequestStoreError("Requested task result file exceeds the bounded resource limit")
        terminal = self._completed_event(
            client,
            request,
            result={
                "resource_token": f"res_{uuid4().hex}",
                "resource_uri": path.as_uri(),
                "result_ref": ref.model_dump(mode="json"),
                "file_name": request.payload.file_name,
                "mime_type": declared.mime_type,
                "size_bytes": current_size,
                "sha256": current_sha256,
                "purpose": request.payload.purpose,
            },
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _task_result_interactive_view_get(
        self, client: BackendClient, request: TaskResultInteractiveViewGetRequest
    ) -> None:
        """Grant a cached hydrated view without putting arrays in an event frame."""

        if self.task_results is None:
            raise RequestStoreError("Task result storage is unavailable")
        ref = request.payload.result_ref
        if request.context.task_id != ref.task_id:
            raise RequestStoreError("Task result does not belong to the current task")
        self._task_in_workspace(ref.task_id, request)
        try:
            result = self.task_results.get(ref)
        except TaskResultError as exc:
            raise RequestNotFound(ref.key) from exc
        if result.workspace_id != self._workspace_id(request) or result.kind != "interactive_view":
            raise RequestStoreError("Interactive task result is unavailable")
        data_file = result.content.get("data_file")
        if not isinstance(data_file, str):
            raise RequestStoreError("Interactive result manifest is missing")
        try:
            cache_path, raw = interactive_view_cache(
                record=result,
                results=self.task_results,
            )
        except (OSError, ValueError, TaskResultError, ExpertDeliverableError) as exc:
            raise RequestStoreError(str(exc) or "Interactive result could not be loaded") from exc
        terminal = self._completed_event(
            client,
            request,
            result={
                "resource_token": f"res_{uuid4().hex}",
                "resource_uri": cache_path.as_uri(),
                "result_ref": ref.model_dump(mode="json"),
                "file_name": cache_path.name,
                "mime_type": "application/json",
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "purpose": "interactive_view_data",
            },
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _artifact_create(self, client: BackendClient, request: ArtifactCreateRequest) -> None:
        if self.artifact_service is None:
            raise RequestStoreError("Artifact service is not configured")
        if request.payload.artifact_type == "paper":
            raise RequestStoreError(
                "Use paper.import for a local PDF snapshot or paper.register for citation metadata"
            )
        if request.payload.artifact_type == "report":
            raise RequestStoreError(
                "Reports are published by the Expert that performed the computation"
            )
        workspace_id = self._workspace_id(request)
        artifact_id = request.payload.artifact_id or self.artifact_service.new_artifact_id(
            request.payload.artifact_type
        )
        draft = ArtifactVersionDraft(
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            artifact_type=request.payload.artifact_type,
            title=request.payload.title,
            summary=request.payload.summary,
            created_by="user",
            content=request.payload.content,
            intrinsic_links=request.payload.intrinsic_links,
            provenance=request.payload.provenance,
            supersedes_version=request.payload.supersedes_version,
        )

        commit = self.artifact_service.commit(
            draft,
            request_id=request.request_id,
            task_id=self._task_id(request),
            task_relation="source" if self._task_id(request) is not None else None,
            expected_workspace_revision=request.expected_workspace_revision,
            files=None,
            event_factory=self._artifact_event_factory(
                client=client,
                request=request,
                workspace_id=workspace_id,
            ),
        )
        if commit.terminal_event is None:
            raise RequestStoreError("Request-backed artifact commit has no terminal event")
        await self._run_terminal_commit_hook(commit.terminal_event)
        await self.event_bus.emit_workspace(commit.domain_event)
        await self.event_bus.emit_local(client, commit.terminal_event)

    async def _dataset_import(self, client: BackendClient, request: DatasetImportRequest) -> None:
        """Attach one local dataset without copying its bytes by default."""

        if self.artifact_service is None:
            raise RequestStoreError("Artifact service is not configured")
        workspace_id = self._workspace_id(request)
        workspace = self.store.workspace_snapshot(workspace_id)
        if not workspace.path:
            raise RequestStoreError("Open a project-local workspace before importing a dataset")
        source, relative_path, dataset_format, source_kind, source_scope = (
            self._local_dataset_source(
                workspace_path=workspace.path,
                relative_path=request.payload.relative_path,
                local_path=request.payload.local_path,
                allow_external=(
                    (client.transport == "stdio" or client.verified_local_desktop)
                    and client.expected_client_kind == "desktop"
                ),
            )
        )
        if request.payload.desktop_staged:
            if relative_path is None:
                raise RequestStoreError("Desktop-staged imports require a workspace path")
            self._assert_desktop_staged_dataset_path(relative_path)
        snapshot = request.payload.materialization_level == "materialized_snapshot"
        if snapshot:
            files, store_root = self._dataset_snapshot_files(
                source=source,
                source_kind=source_kind,
            )
        else:
            files, store_root = {}, None
        source_stat = source.stat(follow_symlinks=False)
        registered_fingerprint = {
            "size_bytes": source_stat.st_size,
            "modified_ns": source_stat.st_mtime_ns,
        }
        if (
            not snapshot
            and not request.payload.desktop_staged
            and request.payload.artifact_id is None
        ):
            source_locator = relative_path if relative_path is not None else str(source)
            existing = self.store.find_local_dataset_reference(
                workspace_id=workspace_id,
                source_scope=source_scope,
                source_locator=source_locator,
                registered_fingerprint=registered_fingerprint,
            )
            if existing is not None:
                task_id = self._task_id(request)
                if task_id is not None and not any(
                    record.artifact.ref == existing.ref and "source" in record.relations
                    for record in self.store.list_task_artifacts(task_id=task_id)
                ):
                    self.store.link_task_artifact(
                        task_id=task_id,
                        ref=existing.ref,
                        relation="source",
                        origin_request_id=request.request_id,
                    )
                projection = self.store.get_projection(
                    workspace_id=workspace_id,
                    ref=existing.ref,
                )
                if projection is None:
                    raise RequestStoreError("Reusable dataset reference has no projection")
                summary = ArtifactSummaryPayload(
                    ref=existing.ref,
                    artifact_type=existing.artifact_type,
                    title=existing.title,
                    summary=existing.summary,
                    projection=projection,
                )
                terminal = self._completed_event(
                    client,
                    request,
                    result={
                        "artifact": summary.model_dump(mode="json"),
                        "manifest_uri": existing.manifest_uri,
                        "reused": True,
                    },
                    workspace_revision=workspace.revision,
                )
                self.store.commit_terminal(request.request_id, terminal)
                await self._broadcast_committed_terminal(client, terminal)
                return
        artifact_id = request.payload.artifact_id or self.artifact_service.new_artifact_id(
            "dataset"
        )
        draft = ArtifactVersionDraft(
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            artifact_type="dataset",
            schema_version="ocean-dataset/v2" if not snapshot else "ocean-dataset/v1",
            title=request.payload.title or source.stem,
            summary=(
                f"Local read-only {dataset_format.upper()} reference"
                if not snapshot
                else f"Materialized local {dataset_format.upper()} snapshot"
            ),
            created_by="user",
            content={
                "schema_version": "ocean-dataset/v2" if not snapshot else "ocean-dataset/v1",
                "materialization_level": request.payload.materialization_level,
                **(
                    {"source_relative_path": relative_path}
                    if relative_path is not None
                    else {"source_path": str(source)}
                ),
                "source_scope": source_scope,
                "format": dataset_format,
                "source_kind": source_kind,
                "registered_fingerprint": registered_fingerprint,
                **({"store_root": store_root} if store_root is not None else {}),
            },
            provenance={
                "schema_version": "ocean-local-dataset-import/v2",
                "source_scope": source_scope,
                **(
                    {"source_relative_path": relative_path}
                    if relative_path is not None
                    else {"source_path": str(source)}
                ),
                "materialization_acknowledged": request.payload.materialization_acknowledged,
            },
        )
        commit = self.artifact_service.commit(
            draft,
            request_id=request.request_id,
            task_id=self._task_id(request),
            task_relation="source" if self._task_id(request) is not None else None,
            expected_workspace_revision=request.expected_workspace_revision,
            files=files,
            event_factory=self._artifact_event_factory(
                client=client,
                request=request,
                workspace_id=workspace_id,
            ),
        )
        if commit.terminal_event is None:
            raise RequestStoreError("Request-backed dataset import has no terminal event")
        if request.payload.desktop_staged:
            assert relative_path is not None
            self._discard_desktop_staged_dataset(workspace.path, relative_path)
        await self._run_terminal_commit_hook(commit.terminal_event)
        await self.event_bus.emit_workspace(commit.domain_event)
        await self.event_bus.emit_local(client, commit.terminal_event)

    async def _local_source_import(
        self, client: BackendClient, request: LocalSourceImportRequest
    ) -> None:
        """Attach a neutral local file/directory; Agents determine how it is used."""

        if self.artifact_service is None:
            raise RequestStoreError("Artifact service is not configured")
        workspace_id = self._workspace_id(request)
        workspace = self.store.workspace_snapshot(workspace_id)
        if not workspace.path:
            raise RequestStoreError("Open a project-local workspace before importing a source")
        source, relative_path, source_format, source_kind, source_scope = (
            self._local_dataset_source(
                workspace_path=workspace.path,
                relative_path=request.payload.relative_path,
                local_path=request.payload.local_path,
                allow_external=(
                    (client.transport == "stdio" or client.verified_local_desktop)
                    and client.expected_client_kind == "desktop"
                ),
            )
        )
        source_stat = source.stat(follow_symlinks=False)
        artifact_id = request.payload.artifact_id or self.artifact_service.new_artifact_id(
            "source"
        )
        locator = (
            {"source_relative_path": relative_path}
            if relative_path is not None
            else {"source_path": str(source)}
        )
        draft = ArtifactVersionDraft(
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            artifact_type="project_context",
            schema_version="ocean-local-source/v1",
            title=request.payload.title or source.name,
            summary=f"Read-only local {source_kind}",
            created_by="user",
            content={
                "schema_version": "ocean-local-source/v1",
                "materialization_level": "local_reference",
                **locator,
                "source_scope": source_scope,
                "source_kind": source_kind,
                "format": source_format,
                "registered_fingerprint": {
                    "size_bytes": source_stat.st_size,
                    "modified_ns": source_stat.st_mtime_ns,
                },
            },
            provenance={
                "schema_version": "ocean-local-source-import/v1",
                "source_scope": source_scope,
                **locator,
            },
        )
        commit = self.artifact_service.commit(
            draft,
            request_id=request.request_id,
            task_id=self._task_id(request),
            task_relation="source" if self._task_id(request) is not None else None,
            expected_workspace_revision=request.expected_workspace_revision,
            files=None,
            event_factory=self._artifact_event_factory(
                client=client,
                request=request,
                workspace_id=workspace_id,
            ),
        )
        if commit.terminal_event is None:
            raise RequestStoreError("Request-backed source import has no terminal event")
        await self._run_terminal_commit_hook(commit.terminal_event)
        await self.event_bus.emit_workspace(commit.domain_event)
        await self.event_bus.emit_local(client, commit.terminal_event)

    async def _paper_import(self, client: BackendClient, request: PaperImportRequest) -> None:
        """Materialize a local PDF without parsing or disclosing its untrusted document text."""

        if self.artifact_service is None:
            raise RequestStoreError("Artifact service is not configured")
        workspace_id = self._workspace_id(request)
        workspace = self.store.workspace_snapshot(workspace_id)
        if not workspace.path:
            raise RequestStoreError("Open a project-local workspace before importing a paper")
        source, relative_path = self._workspace_pdf_source(
            workspace_path=workspace.path,
            requested_path=request.payload.relative_path,
        )
        artifact_id = request.payload.artifact_id or self.artifact_service.new_artifact_id("paper")
        content = PaperContent(
            citation=request.payload.citation,
            source_kind="local_pdf",
            materialization_level="materialized_snapshot",
        )
        draft = ArtifactVersionDraft(
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            artifact_type="paper",
            title=content.citation.title,
            summary="User-imported local PDF; document text remains opaque to the model",
            created_by="import",
            content=content.model_dump(mode="json"),
            provenance={
                "schema_version": "ocean-local-paper-import/v1",
                "source_relative_path": relative_path,
                "materialization_acknowledged": request.payload.materialization_acknowledged,
                "document_text_exposed_to_model": False,
            },
        )
        commit = self.artifact_service.commit(
            draft,
            request_id=request.request_id,
            task_id=self._task_id(request),
            task_relation="source" if self._task_id(request) is not None else None,
            expected_workspace_revision=request.expected_workspace_revision,
            files={source.name: source},
            event_factory=self._artifact_event_factory(
                client=client,
                request=request,
                workspace_id=workspace_id,
            ),
        )
        if commit.terminal_event is None:
            raise RequestStoreError("Request-backed paper import has no terminal event")
        await self._run_terminal_commit_hook(commit.terminal_event)
        await self.event_bus.emit_workspace(commit.domain_event)
        await self.event_bus.emit_local(client, commit.terminal_event)

    async def _paper_register(self, client: BackendClient, request: PaperRegisterRequest) -> None:
        """Persist user-supplied bibliographic metadata without pretending to own paper bytes."""

        if self.artifact_service is None:
            raise RequestStoreError("Artifact service is not configured")
        workspace_id = self._workspace_id(request)
        artifact_id = request.payload.artifact_id or self.artifact_service.new_artifact_id("paper")
        content = PaperContent(
            citation=request.payload.citation,
            source_kind="metadata_only",
            materialization_level="metadata_only",
        )
        draft = ArtifactVersionDraft(
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            artifact_type="paper",
            title=content.citation.title,
            summary="User-registered citation metadata; no document text or PDF is stored",
            created_by="user",
            content=content.model_dump(mode="json"),
            provenance={
                "schema_version": "ocean-paper-metadata-registration/v1",
                "document_text_exposed_to_model": False,
            },
        )
        commit = self.artifact_service.commit(
            draft,
            request_id=request.request_id,
            task_id=self._task_id(request),
            task_relation="source" if self._task_id(request) is not None else None,
            expected_workspace_revision=request.expected_workspace_revision,
            files=None,
            event_factory=self._artifact_event_factory(
                client=client,
                request=request,
                workspace_id=workspace_id,
            ),
        )
        if commit.terminal_event is None:
            raise RequestStoreError("Request-backed paper registration has no terminal event")
        await self._run_terminal_commit_hook(commit.terminal_event)
        await self.event_bus.emit_workspace(commit.domain_event)
        await self.event_bus.emit_local(client, commit.terminal_event)

    async def _hypothesis_activate(
        self,
        client: BackendClient,
        request: HypothesisActivateRequest,
    ) -> None:
        """Move the active-hypothesis pointer only after an explicit Desktop request."""

        workspace_id = self._workspace_id(request)
        artifact = self.store.get_artifact(
            workspace_id=workspace_id, ref=request.payload.hypothesis_ref
        )
        if artifact is None:
            raise RequestNotFound(request.payload.hypothesis_ref.key)
        if artifact.artifact_type != "hypothesis":
            raise RequestStoreError("hypothesis.activate requires a HypothesisArtifact reference")

        def event_factory(snapshot, previous_revision, workspace_revision):
            changed = WorkspaceChangedEvent(
                **self._event_fields(
                    client, request_id=request.request_id, workspace_id=workspace_id
                ),
                type="workspace.changed",
                payload=WorkspaceChangedPayload(
                    previous_revision=previous_revision,
                    workspace_revision=workspace_revision,
                    change="updated",
                ),
            )
            terminal = self._completed_event(
                client,
                request,
                result={
                    "active_hypothesis": request.payload.hypothesis_ref.model_dump(mode="json"),
                    "workspace": snapshot.as_payload(),
                },
                workspace_revision=workspace_revision,
            )
            return changed, terminal

        commit = self.store.commit_active_ref(
            request_id=request.request_id,
            workspace_id=workspace_id,
            slot="active_hypothesis",
            ref=request.payload.hypothesis_ref,
            expected_workspace_revision=request.expected_workspace_revision,
            event_factory=event_factory,
        )
        await self._run_terminal_commit_hook(commit.terminal_event)
        await self.event_bus.emit_workspace(commit.domain_event)
        await self.event_bus.emit_local(client, commit.terminal_event)

    async def _portable_export_create(
        self, client: BackendClient, request: PortableExportCreateRequest
    ) -> None:
        """Materialize an audited bundle without exposing renderer-visible local paths."""

        if self.portable_export_service is None:
            raise RequestStoreError("Portable export service is not configured")
        workspace_id = self._workspace_id(request)
        try:
            exported = self.portable_export_service.export(
                workspace_id=workspace_id,
                refs=request.payload.artifact_refs,
            )
        except PortableExportError as exc:
            await self._fail_request(
                client,
                request,
                code="tool_error",
                message="Portable export could not be created",
                recoverable=True,
                details={"reason": str(exc)},
            )
            return
        terminal = self._completed_event(
            client,
            request,
            result={
                "export_id": exported.bundle_directory.name,
                "artifact_refs": [ref.model_dump(mode="json") for ref in exported.refs],
                "format": "ocean-portable-export/v1",
                "raw_logs_included": False,
                "local_paper_pdfs_included": False,
            },
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    # --- the project's learned library: lessons and tools ----------------------------
    def _project_research(self):
        from oceanx.research.review import ProjectResearch
        if self.task_workspace_projector is None:
            raise RequestStoreError("Research memory requires an open project.")
        return ProjectResearch(self.task_workspace_projector.paths)

    def _research_tree_stores(self, workspace_id: str) -> list[Path]:
        stores = []
        for task in self.store.list_research_tasks(
                workspace_id=workspace_id, include_archived=True, limit=500):
            try:
                root = self.task_workspace_projector.ensure_task_root(task.task_id)
            except Exception:  # noqa: BLE001 - a broken task folder must not block cleanup
                continue
            candidate = root / "agents" / "coordinator" / "research_tree.sqlite3"
            if candidate.is_file():
                stores.append(candidate)
        return stores

    def _update_library(self, workspace_id: str, *, review: bool, wait: bool = True) -> dict | None:
        """Bring records and call counts up to date; with ``review`` the meta-agent also
        reviews the lessons and learns tools. One update runs at a time: another waits for
        it, or with ``wait`` false is left out (None)."""
        from oceanx.research.llm import default_llm
        if not self._library_lock.acquire(blocking=wait):
            return None
        try:
            if self._closing:
                return None  # it waited its turn until the backend began to close
            llm = default_llm() if review else None
            return self._project_research().update(self._research_tree_stores(workspace_id),
                                                   llm=llm, reviewer=llm)
        finally:
            self._library_lock.release()

    def _mark_library(self, project, kind: str, item_id: str, verdict: str) -> None:
        """The owner's mark. An update that is running has read the library and will write it
        back, so a mark made meanwhile would be lost: it is refused, to be made again."""
        if not self._library_lock.acquire(blocking=False):
            raise ValueError("The lessons and tools are being updated; mark it again when the update is done.")
        try:
            project.mark(kind, item_id, verdict)
        finally:
            self._library_lock.release()

    def _maintain_library(self, workspace_id: str) -> dict | None:
        """Regular upkeep after a research request. Records and call counts are refreshed every
        time (no model call); the meta-agent reviews at most once a day. A frozen library (an
        experiment arm) is never touched."""
        from oceanx.research.review import LIBRARY_FROZEN_ENV
        if os.environ.get(LIBRARY_FROZEN_ENV):
            return None
        due = self._project_research().lessons.review_due()
        try:
            # Left out while an update runs; the upkeep after the next request catches up.
            return self._update_library(workspace_id, review=due, wait=False)
        except Exception:  # e.g. no model configured for the meta-agent
            if not due:
                raise
            _LOGGER.exception("The meta-agent's library review failed; records were kept current")
            return self._update_library(workspace_id, review=False, wait=False)

    def _schedule_research_consolidation(self, request: RequestEnvelope) -> None:
        """Keep the project's library current after research requests, off the request path."""
        if self._closing or self.task_workspace_projector is None:
            return
        try:
            workspace_id = self._workspace_id(request)
        except RequestStoreError:
            return

        async def run() -> None:
            try:
                await asyncio.to_thread(self._maintain_library, workspace_id)
            except Exception:  # noqa: BLE001 - maintenance must never affect research
                _LOGGER.exception("Research library upkeep failed")

        asyncio.get_running_loop().create_task(run())

    def _start_library_update(self, client: BackendClient, request: ResearchLibraryUpdateRequest) -> None:
        """Run "Update now" off the connection's request loop; the reply is sent when it is done.

        A review reads the final answer of every newly finished task and can take many minutes.
        The loop answers one request at a time, so awaited there the update would leave every
        other request of the window unanswered until it ended."""

        async def run() -> None:
            try:
                await self._research_library(client, request)
            except asyncio.CancelledError:
                if not self._closing:
                    raise
            except Exception as exc:  # noqa: BLE001 - nothing awaits this task; the request must still end
                await self._fail_request(client, request, code="store_error",
                                         message="Backend request handler failed",
                                         recoverable=True, details={"reason": str(exc)})

        task = asyncio.get_running_loop().create_task(run(), name=f"ocean-library-{request.request_id}")
        self._library_updates.add(task)
        task.add_done_callback(self._library_updates.discard)

    async def _research_library(self, client: BackendClient, request: RequestEnvelope) -> None:
        """The project's lessons and tools: look at them, update them now, or mark one right
        or wrong."""
        run = asyncio.to_thread
        try:
            project = self._project_research()
            payload = request.payload
            result: dict[str, Any] = {}
            if isinstance(request, ResearchLibraryMarkRequest):
                await run(self._mark_library, project, payload.kind, payload.id, payload.verdict)
            elif isinstance(request, ResearchLibraryUpdateRequest):
                result["update"] = await run(
                    self._update_library, self._workspace_id(request), review=payload.review)
            result["library"] = await run(project.overview)
        except (ValueError, RequestStoreError, OSError) as exc:
            await self._fail_request(client, request, code="invalid_request", message=str(exc),
                                     recoverable=True, details={})
            return
        except Exception as exc:  # noqa: BLE001 - e.g. model not configured for the meta-agent
            await self._fail_request(client, request, code="model_error",
                                     message="Meta model request failed",
                                     recoverable=True, details={"reason": str(exc)})
            return
        terminal = self._completed_event(client, request, result=result)
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _disclosure_policy_get(
        self,
        client: BackendClient,
        request: DisclosurePolicyGetRequest,
    ) -> None:
        """Return the current policy summary without disclosing any protected content."""

        summary = self.store.get_disclosure_policy_summary(self._workspace_id(request))
        policy = DisclosurePolicySummary.model_validate(summary) if summary is not None else None
        terminal = self._completed_event(
            client,
            request,
            result={
                "policy": policy.model_dump(mode="json") if policy is not None else None,
                "versions": self.store.list_disclosure_policy_versions(
                    workspace_id=self._workspace_id(request)
                ),
            },
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _disclosure_policy_set(
        self,
        client: BackendClient,
        request: DisclosurePolicySetRequest,
    ) -> None:
        """Commit a fully specified user confirmation as a versioned workspace policy."""

        workspace_id = self._workspace_id(request)
        policy = ModelDataDisclosurePolicy(
            provider_id=request.payload.provider_id,
            policy_version=1,
            metadata=request.payload.metadata,
            aggregate_statistics=request.payload.aggregate_statistics,
            raw_bounded_sample=request.payload.raw_bounded_sample,
            document_text=request.payload.document_text,
            diagnostic_excerpt=request.payload.diagnostic_excerpt,
        )

        def event_factory(summary, previous_revision, workspace_revision, event_id):
            visible_policy = DisclosurePolicySummary.model_validate(summary)
            domain_event = DisclosurePolicyUpdatedEvent(
                **self._event_fields(
                    client,
                    request_id=request.request_id,
                    workspace_id=workspace_id,
                    event_id=event_id,
                ),
                type="disclosure.policy.updated",
                payload=DisclosurePolicyUpdatedPayload(
                    policy=visible_policy,
                    previous_revision=previous_revision,
                    workspace_revision=workspace_revision,
                ),
            )
            terminal_event = self._completed_event(
                client,
                request,
                result={"policy": visible_policy.model_dump(mode="json"), "confirmed": True},
                workspace_revision=workspace_revision,
            )
            return domain_event, terminal_event

        commit = self.store.commit_disclosure_policy(
            request_id=request.request_id,
            workspace_id=workspace_id,
            provider_id=policy.provider_id,
            policy=policy.as_storage_payload(),
            expected_workspace_revision=request.expected_workspace_revision,
            event_factory=event_factory,
        )
        await self._run_terminal_commit_hook(commit.terminal_event)
        await self.event_bus.emit_workspace(commit.domain_event)
        await self.event_bus.emit_local(client, commit.terminal_event)

    @staticmethod
    def _workspace_dataset_source(
        *, workspace_path: str, requested_path: str
    ) -> tuple[Path, str, str, Literal["file", "directory"]]:
        """Resolve one locally authorized dataset without imposing a format whitelist."""

        if not is_safe_cross_platform_relative_path(requested_path):
            raise RequestStoreError("Dataset import path must be a safe workspace-relative path")
        relative = PurePosixPath(requested_path)
        try:
            root = Path(workspace_path).resolve(strict=True)
        except OSError as exc:
            raise RequestStoreError("Workspace root is unavailable for dataset import") from exc
        if not root.is_dir():
            raise RequestStoreError("Workspace root is not a directory")
        candidate = root.joinpath(*relative.parts)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise RequestStoreError("Dataset import does not permit symlinked paths")
        try:
            source = candidate.resolve(strict=True)
            source.relative_to(root)
        except (OSError, ValueError) as exc:
            raise RequestStoreError(
                "Dataset import path is unavailable or escapes the workspace"
            ) from exc
        if source.is_file() and not source.is_symlink():
            return source, relative.as_posix(), _local_dataset_format(source), "file"
        if source.is_dir() and not source.is_symlink():
            return source, relative.as_posix(), _local_dataset_format(source), "directory"
        raise RequestStoreError("Dataset import source must be a regular file or directory")

    @staticmethod
    def _local_dataset_source(
        *,
        workspace_path: str,
        relative_path: str | None,
        local_path: str | None,
        allow_external: bool,
    ) -> tuple[
        Path,
        str | None,
        str,
        Literal["file", "directory"],
        Literal["workspace", "desktop_authorized"],
    ]:
        """Resolve a user-selected local source without walking or copying it."""

        if local_path is None:
            if relative_path is None:
                raise RequestStoreError("Dataset import has no local source path")
            source, normalized, dataset_format, source_kind = (
                OceanRequestRouter._workspace_dataset_source(
                    workspace_path=workspace_path,
                    requested_path=relative_path,
                )
            )
            return source, normalized, dataset_format, source_kind, "workspace"
        if relative_path is not None:
            raise RequestStoreError("Dataset import must use one source path")
        if not allow_external:
            raise RequestStoreError(
                "External local paths may only be attached by the local Desktop client"
            )
        candidate = Path(local_path).expanduser()
        if not candidate.is_absolute() or candidate.is_symlink():
            raise RequestStoreError("Desktop dataset path must be an absolute non-link path")
        try:
            source = candidate.resolve(strict=True)
        except OSError as exc:
            raise RequestStoreError("Desktop dataset path is unavailable") from exc
        if source.is_file() and not source.is_symlink():
            source_kind: Literal["file", "directory"] = "file"
        elif source.is_dir() and not source.is_symlink():
            source_kind = "directory"
        else:
            raise RequestStoreError("Desktop dataset source must be a regular file or directory")
        return (
            source,
            None,
            _local_dataset_format(source),
            source_kind,
            "desktop_authorized",
        )

    @staticmethod
    def _dataset_snapshot_files(
        *, source: Path, source_kind: Literal["file", "directory"]
    ) -> tuple[dict[str, Path], str | None]:
        if source_kind == "file":
            return {f"data/{source.name}": source}, None
        files: dict[str, Path] = {}
        stack = [source]
        while stack:
            directory = stack.pop()
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name)
            except OSError as exc:
                raise RequestStoreError("Zarr store could not be enumerated safely") from exc
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(source).as_posix()
                is_junction = getattr(path, "is_junction", None)
                file_attributes = getattr(path.lstat(), "st_file_attributes", 0)
                reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                if (
                    path.is_symlink()
                    or (callable(is_junction) and is_junction())
                    or bool(reparse_flag and file_attributes & reparse_flag)
                ):
                    raise RequestStoreError(
                        f"Dataset directory link-like entry is forbidden: {relative}"
                    )
                mode = path.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    stack.append(path)
                elif stat.S_ISREG(mode):
                    files[f"data/{source.name}/{relative}"] = path
                else:
                    raise RequestStoreError(
                        f"Dataset directory special file is forbidden: {relative}"
                    )
        if not files:
            raise RequestStoreError("Dataset directory contains no regular files")
        return files, f"data/{source.name}"

    @staticmethod
    def _assert_desktop_staged_dataset_path(relative_path: str) -> None:
        parts = PurePosixPath(relative_path).parts
        if parts[:3] == (".oceanx", "staging", "desktop-imports"):
            import_index = 3
        else:
            raise RequestStoreError("Desktop-staged dataset path is invalid")
        if (
            len(parts) <= import_index + 1
            or not re.fullmatch(r"desktop_import_[a-f0-9]{32}", parts[import_index])
            or parts[import_index + 1] != "source"
        ):
            raise RequestStoreError("Desktop-staged dataset path is invalid")

    @staticmethod
    def _discard_desktop_staged_dataset(workspace_path: str, relative_path: str) -> None:
        parts = PurePosixPath(relative_path).parts
        if parts[:3] == (".oceanx", "staging", "desktop-imports"):
            import_index = 3
        else:
            return
        if len(parts) <= import_index or not re.fullmatch(
            r"desktop_import_[a-f0-9]{32}", parts[import_index]
        ):
            return
        container = Path(workspace_path).joinpath(*parts[: import_index + 1])
        shutil.rmtree(container, ignore_errors=True)

    @staticmethod
    def _workspace_pdf_source(*, workspace_path: str, requested_path: str) -> tuple[Path, str]:
        """Resolve one local PDF without letting paper import become a file API."""

        if not is_safe_cross_platform_relative_path(requested_path):
            raise RequestStoreError("Paper import path must be a safe workspace-relative path")
        relative = PurePosixPath(requested_path)
        try:
            root = Path(workspace_path).resolve(strict=True)
        except OSError as exc:
            raise RequestStoreError("Workspace root is unavailable for paper import") from exc
        if not root.is_dir():
            raise RequestStoreError("Workspace root is not a directory")
        candidate = root.joinpath(*relative.parts)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise RequestStoreError("Paper import does not permit symlinked paths")
        try:
            source = candidate.resolve(strict=True)
            source.relative_to(root)
        except (OSError, ValueError) as exc:
            raise RequestStoreError(
                "Paper import path is unavailable or escapes the workspace"
            ) from exc
        if not source.is_file() or source.is_symlink():
            raise RequestStoreError("Paper import source must be a regular file")
        if source.suffix.lower() != ".pdf":
            raise RequestStoreError("Paper import accepts PDF files only")
        return source, relative.as_posix()

    def _artifact_event_factory(
        self,
        *,
        client: BackendClient,
        request: RequestEnvelope,
        workspace_id: str,
    ):
        def event_factory(
            artifact,
            projection,
            _previous_revision: int,
            workspace_revision: int,
            event_id: str,
        ):
            summary = ArtifactSummaryPayload(
                ref=artifact.ref,
                artifact_type=artifact.artifact_type,
                title=artifact.title,
                summary=artifact.summary,
                projection=projection,
            )
            event_type = (
                ArtifactCreatedEvent if artifact.ref.version == 1 else ArtifactVersionCreatedEvent
            )
            domain_event = event_type(
                **self._event_fields(
                    client,
                    request_id=request.request_id,
                    workspace_id=workspace_id,
                    event_id=event_id,
                ),
                type="artifact.created"
                if artifact.ref.version == 1
                else "artifact.version.created",
                payload=ArtifactCreatedPayload(
                    artifact=summary,
                    manifest_uri=artifact.manifest_uri,
                    workspace_revision=workspace_revision,
                ),
            )
            terminal_event = self._completed_event(
                client,
                request,
                result={
                    "artifact": summary.model_dump(mode="json"),
                    "manifest_uri": artifact.manifest_uri,
                },
                workspace_revision=workspace_revision,
            )
            return domain_event, terminal_event

        return event_factory

    async def _session_submit(self, client: BackendClient, request: SessionSubmitRequest) -> None:
        """Start one durable, cancellable agent request without blocking control frames."""

        if self.artifact_service is None:
            raise RequestStoreError("Ocean agent services are not configured")
        workspace_id = self._workspace_id(request)
        task_id = self._task_id(request)
        workspace = self.store.workspace_snapshot(workspace_id)
        effective_task_revision = request.expected_task_revision
        revision_refreshed = False
        if workspace.revision != request.expected_workspace_revision:
            # session.submit has not produced an external effect yet.  Rebase
            # this read/plan boundary exactly once when the task has no active
            # writer; later mutating tools still carry normal revision guards.
            task = self.store.get_research_task(task_id) if task_id is not None else None
            if (
                task is None
                or task.workspace_id != workspace_id
                or task.status != "active"
                or task.active_request_id is not None
            ):
                raise WorkspaceRevisionConflict(workspace.revision)
            effective_task_revision = task.task_revision
            revision_refreshed = True
        if not workspace.path:
            await self._fail_request(
                client,
                request,
                code="tool_error",
                message="Open a project-local workspace before submitting an Ocean agent request",
                recoverable=True,
                details={},
            )
            return
        runtime_key = task_id or client.session_id
        if runtime_key is None:
            raise OceanAgentRuntimeError("Authenticated client has no session ID")
        # A terminal event is committed before the request task releases its
        # in-memory runtime slot.  A fast follow-up must wait for that bounded
        # cleanup instead of being misclassified as concurrent work.
        stale_request_ids = [
            request_id
            for request_id, session_key in self._agent_request_sessions.items()
            if session_key == runtime_key
            and (record := self.store.get_request(request_id)) is not None
            and record.terminal
        ]
        stale_tasks = [
            self._agent_tasks[request_id]
            for request_id in stale_request_ids
            if request_id in self._agent_tasks
            and self._agent_tasks[request_id] is not asyncio.current_task()
        ]
        if stale_tasks:
            await asyncio.gather(*stale_tasks, return_exceptions=True)
        if runtime_key in self._agent_sessions and any(
            session_key == runtime_key for session_key in self._agent_request_sessions.values()
        ):
            await self._fail_request(
                client,
                request,
                code="tool_error",
                message="This session already has an active foreground agent request",
                recoverable=True,
                details={},
            )
            return

        try:
            provider_id = self.provider_id_resolver()
            expected_model_id = (
                self.model_id_resolver() if self.model_id_resolver is not None else None
            )
        except OceanAgentRuntimeError as exc:
            await self._fail_request(
                client,
                request,
                code="model_error",
                message="Configured Ocean model provider is unavailable",
                recoverable=True,
                details={"reason": str(exc)},
            )
            return

        try:
            submitted_text = self._submitted_text_with_context_refs(
                workspace_id=workspace_id,
                task_id=task_id,
                text=request.payload.text,
                context_refs=request.payload.context_refs,
            )
        except RequestNotFound as exc:
            await self._fail_request(
                client,
                request,
                code="artifact_not_found",
                message="A selected immutable context reference is unavailable in this workspace",
                recoverable=True,
                details={"reason": str(exc)},
            )
            return

        if task_id is not None:
            current_task_record = self._task_in_workspace(task_id, request)
            if effective_task_revision != current_task_record.task_revision:
                if (
                    current_task_record.status != "active"
                    or current_task_record.active_request_id is not None
                ):
                    raise TaskRevisionConflict(current_task_record.task_revision)
                effective_task_revision = current_task_record.task_revision
                revision_refreshed = True
            self.store.begin_task_request(
                task_id=task_id,
                request_id=request.request_id,
                expected_task_revision=effective_task_revision,
            )
            self.store.start_task_workflow(
                request_id=request.request_id,
                task_id=task_id,
                workspace_id=workspace_id,
            )


        try:
            agent_session = await self._agent_session_for(
                client=client,
                workspace_id=workspace_id,
                workspace_path=Path(workspace.path),
                provider_id=provider_id,
                expected_model_id=expected_model_id,
                task_id=task_id,
            )
        except (OceanAgentRuntimeError, OSError, ValueError) as exc:
            await self._fail_request(
                client,
                request,
                code="model_error",
                message="Ocean agent runtime could not prepare a provider-approved workspace context",
                recoverable=True,
                details={"reason": str(exc)},
            )
            return

        agent_session.runtime.engine.set_request_options(
            literature_acquisition_mode=request.payload.literature_acquisition_mode,
            workflow_mode=request.payload.workflow_mode,
            max_parallel_experts=request.payload.max_parallel_experts,
        )
        self._agent_request_clients[request.request_id] = client
        self._agent_request_sessions[request.request_id] = agent_session.runtime_key
        if revision_refreshed:
            # This is concurrency bookkeeping, not part of the research
            # conversation.  Keep it in backend diagnostics instead of
            # presenting it as if the user or Coordinator said it.
            _LOGGER.info(
                "Refreshed a stale task revision before model execution",
                extra={"task_id": task_id, "request_id": request.request_id},
            )
        self._team_snapshot_revisions[request.request_id] = 0
        await self._emit_team_snapshot(
            workspace_id=workspace_id,
            parent_request_id=request.request_id,
            task_id=task_id,
        )
        task = asyncio.create_task(
            self._execute_agent_request(
                client=client,
                request=request,
                agent_session=agent_session,
                submitted_text=submitted_text,
                visible_text=request.payload.text,
            ),
            name=f"ocean-agent-{request.request_id}",
        )
        self._agent_tasks[request.request_id] = task


    async def _ask_interaction_for_request(
        self,
        client: BackendClient,
        *,
        request_id: str,
        task_id: str | None,
        workspace_id: str,
        question: str,
        kind: Literal["question", "permission", "paper_selection"],
        tool_name: str | None = None,
        options: tuple[dict[str, Any], ...] = (),
    ) -> str:
        """Pause one active model request for a typed researcher interaction."""

        if client.session_id is None:
            raise OceanAgentRuntimeError("Question interaction requires an authenticated session")
        normalized = question.strip()
        if not normalized:
            raise OceanAgentRuntimeError("Question interaction cannot be empty")
        interaction_id = f"int_{uuid4().hex}"
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.store.create_interaction(
            interaction_id=interaction_id,
            request_id=request_id,
            task_id=task_id,
            workspace_id=workspace_id,
            session_id=client.session_id,
            principal=client.principal.key if client.principal is not None else "",
            question=normalized,
            kind=kind,
            options=options,
        )
        self._pending_questions[interaction_id] = (request_id, client.session_id, future)
        await self.event_bus.emit_local(
            client,
            InteractionRequestedEvent(
                **self._event_fields(
                    client,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    task_id=task_id,
                ),
                type="interaction.requested",
                payload=InteractionRequestedPayload(
                    interaction_id=interaction_id,
                    kind=kind,
                    question=self._bounded_text(normalized, 4_000),
                    tool_name=tool_name,
                    options=options,
                ),
            ),
        )
        try:
            return await future
        finally:
            self._pending_questions.pop(interaction_id, None)

    async def _request_paper_selection(
        self,
        *,
        workspace_id: str,
        task_id: str | None,
        payload: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        """Return an explicit paper shortlist selection to the active Search Expert call."""

        request_id = str(context.request_id or "").strip()
        if not request_id:
            raise OceanAgentRuntimeError("Paper selection requires an active request")
        client = self._agent_request_clients.get(request_id)
        if client is None:
            raise OceanAgentRuntimeError("Paper selection request is no longer active")
        raw_papers = payload.get("papers")
        if not isinstance(raw_papers, list) or not raw_papers:
            raise OceanAgentRuntimeError("Paper selection requires a non-empty shortlist")
        papers = tuple(dict(item) for item in raw_papers if isinstance(item, dict))
        if len(papers) != len(raw_papers):
            raise OceanAgentRuntimeError("Paper selection shortlist is malformed")
        question = str(payload.get("question") or "").strip()
        answer = await self._ask_interaction_for_request(
            client,
            request_id=request_id,
            task_id=task_id,
            workspace_id=workspace_id,
            question=question,
            kind="paper_selection",
            tool_name="ocean_request_paper_selection",
            options=papers,
        )
        try:
            response = json.loads(answer)
            selected_ids = response["selected_paper_ids"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise OceanAgentRuntimeError("Paper selection response is malformed") from exc
        if (
            not isinstance(selected_ids, list)
            or not selected_ids
            or any(not isinstance(value, str) for value in selected_ids)
            or len(selected_ids) != len(set(selected_ids))
        ):
            raise OceanAgentRuntimeError("Select at least one unique paper")
        known_by_id = {str(paper.get("paper_id")): paper for paper in papers}
        unknown = sorted(set(selected_ids) - set(known_by_id))
        if unknown:
            raise OceanAgentRuntimeError(
                "Paper selection contains unknown ids: " + ", ".join(unknown)
            )
        selected_set = set(selected_ids)
        selected_papers = [
            known_by_id[str(paper["paper_id"])]
            for paper in papers
            if str(paper["paper_id"]) in selected_set
        ]
        return {
            "selected_paper_ids": selected_ids,
            "selected_papers": selected_papers,
        }

    async def _interaction_respond(
        self, client: BackendClient, request: InteractionRespondRequest
    ) -> None:
        pending = self._pending_questions.get(request.payload.interaction_id)
        if pending is None:
            raise RequestNotFound("Question interaction is no longer pending")
        target_request_id, session_id, future = pending
        if client.session_id != session_id:
            raise RequestStoreError("Question interaction belongs to a different session")
        answer = request.payload.answer.strip()
        terminal = self._completed_event(
            client,
            request,
            result={
                "interaction_id": request.payload.interaction_id,
                "target_request_id": target_request_id,
            },
        )
        self.store.commit_interaction_response(
            interaction_id=request.payload.interaction_id,
            session_id=client.session_id,
            principal=client.principal.key if client.principal is not None else "",
            terminal_event=terminal,
        )
        if not future.done():
            future.set_result(answer)
        await self._broadcast_committed_terminal(client, terminal)

    async def _agent_session_for(
        self,
        *,
        client: BackendClient,
        workspace_id: str,
        workspace_path: Path,
        provider_id: str,
        expected_model_id: str | None,
        task_id: str | None,
    ) -> _AgentSession:
        """Reuse a conversation only while its workspace/provider binding remains valid."""

        if client.session_id is None:
            raise OceanAgentRuntimeError("Authenticated client has no session ID")
        if self.artifact_service is None:
            raise OceanAgentRuntimeError("Ocean agent services are not configured")
        runtime_key = task_id or client.session_id
        existing = self._agent_sessions.get(runtime_key)
        if (
            existing is not None
            and existing.workspace_id == workspace_id
            and existing.runtime.provider_id == provider_id
            and (
                expected_model_id is None
                or existing.runtime.model_id == expected_model_id
            )
        ):
            return existing
        if existing is not None:
            await existing.runtime.close()
            self._agent_sessions.pop(runtime_key, None)
        if task_id is not None:
            active_runtime_keys = set(self._agent_request_sessions.values())
            for cached_key, cached in list(self._agent_sessions.items()):
                if cached_key == runtime_key or cached_key in active_runtime_keys:
                    continue
                if cached.task_id is not None:
                    await cached.runtime.close()
                    self._agent_sessions.pop(cached_key, None)
        if not workspace_path.is_dir():
            raise OceanAgentRuntimeError("Workspace directory is unavailable")
        services = OceanToolServices(
            workspace_id=workspace_id,
            provider_id=provider_id,
            store=self.store,
            artifacts=self.artifact_service,
            task_id=task_id,
            resource_access="routing",
            expert_code_execution=(
                self.research_services.expert_code_execution if self.research_services else None
            ),
            skill_capabilities=(LITERATURE_CAPABILITY,),
            skill_role="coordinator",
            domain_event_emitter=self.event_bus.emit_workspace,
            coordinator_enabled=True,
            agent_thread_id=(
                f"task:{workspace_id}:{task_id}"
                if task_id is not None
                else f"session:{workspace_id}:{client.session_id}"
            ),
        )
        runtime = await self.agent_runtime_factory(
            services,
            workspace_path.resolve(),
            self._operation_id,
        )
        if runtime.provider_id != provider_id:
            await runtime.close()
            raise OceanAgentRuntimeError(
                "Ocean runtime provider does not match the confirmed disclosure policy"
            )
        session = _AgentSession(
            session_id=client.session_id,
            runtime_key=runtime_key,
            workspace_id=workspace_id,
            task_id=task_id,
            runtime=runtime,
        )
        self._agent_sessions[runtime_key] = session
        return session


    def _task_source_refs(
        self,
        *,
        workspace_id: str,
        task_id: str | None,
    ) -> tuple[EvidenceRef, ...]:
        """Freeze every user-visible task source without involving an Agent."""

        if task_id is None:
            return ()
        refs: list[EvidenceRef] = []
        for record in self.store.list_task_artifacts(task_id=task_id):
            artifact = record.artifact
            if artifact.workspace_id != workspace_id or artifact.artifact_type not in {
                "dataset",
                "paper",
            }:
                continue
            if "source" not in record.relations:
                continue
            kind = "dataset" if artifact.artifact_type == "dataset" else "paper"
            evidence = EvidenceRef(
                kind=kind,
                ref=artifact.ref.key,
                locator=f"source_{len(refs) + 1}",
            )
            if evidence not in refs:
                refs.append(evidence)
        return tuple(refs)




    async def _execute_agent_request(
        self,
        *,
        client: BackendClient,
        request: SessionSubmitRequest,
        agent_session: _AgentSession,
        submitted_text: str,
        visible_text: str,
    ) -> None:
        """Map one Ocean agent stream into Protocol v2 and commit one terminal result."""

        usage_input_tokens = 0
        usage_output_tokens = 0
        tool_call_count = 0
        turn_count = 0
        last_assistant_text = ""
        model_error: ErrorEvent | None = None
        # API latency is not a model-resource budget. Token/turn limits bound
        # reasoning; cancellation and tool-progress checks remain independent.
        try:
            await self._append_transcript_item(
                client,
                request,
                role="user",
                # ``submitted_text`` contains server-owned routing identities
                # used by the model.  The durable, user-visible transcript must
                # contain exactly what the researcher submitted.
                text=visible_text,
            )
            stream = _coordinator_events(
                agent_session.runtime.engine, submitted_text, request.request_id,
            ).__aiter__()
            native_team_tools = {"task"}
            while True:
                try:
                    event = await anext(stream)
                except StopAsyncIteration:
                    break
                except asyncio.CancelledError:
                    # Expert products are candidates, not a Coordinator
                    # decision. Never synthesize or accept them in backend
                    # recovery when Coordinator reasoning is interrupted.
                    raise

                if isinstance(event, ToolExecutionCompleted):
                    if event.tool_name == "task":
                        # Text before the assignment is progress narration, not
                        # a conclusion. The next assistant answer is synthesis.
                        last_assistant_text = ""

                if isinstance(event, ToolExecutionStarted) and event.tool_name == "task":
                    now = datetime.now(UTC).isoformat()
                    self._native_task_activity.setdefault(request.request_id, {})[
                        event.tool_call_id
                    ] = {
                        "task_id": event.tool_call_id,
                        "request_id": request.request_id,
                        "agent_name": str(event.tool_input.get("subagent_type") or "expert"),
                        "description": str(event.tool_input.get("description") or "Research subquestion"),
                        "node_id": str(event.tool_input.get("node_id") or "").strip() or None,
                        "status": "running",
                        "created_at": now,
                        "last_updated_at": now,
                    }
                elif isinstance(event, ToolExecutionCompleted) and event.tool_name == "task":
                    item = self._native_task_activity.setdefault(request.request_id, {}).setdefault(
                        event.tool_call_id,
                        {"task_id": event.tool_call_id, "request_id": request.request_id,
                         "agent_name": "expert", "description": "Research subquestion"},
                    )
                    item["status"] = "failed" if event.is_error else "completed"
                    item["last_updated_at"] = datetime.now(UTC).isoformat()
                    item["output"] = event.output
                    if not event.is_error:
                        from oceanx.research.services import parse_expert_receipt
                        summary, report_path = parse_expert_receipt(event.output)
                        item["report_path"] = report_path
                        item["summary"] = summary

                if isinstance(event, AssistantTurnComplete):
                    turn_count += 1
                    usage_input_tokens += event.usage.input_tokens
                    usage_output_tokens += event.usage.output_tokens
                    if event.message.text and not event.message.tool_uses:
                        last_assistant_text = event.message.text
                    # Usage is telemetry, never a reason to stop this research.
                elif isinstance(event, ToolExecutionStarted):
                    tool_call_count += 1
                elif isinstance(event, ErrorEvent):
                    model_error = event

                self._update_task_workflow_for_event(request, event)
                await self._emit_agent_stream_event(client, request, event)
                # The model turn announcing a ``task`` arrives before the
                # native tool-start event has created its activity record.
                # Project the team exactly when DeepAgents starts and finishes
                # the task; an earlier snapshot would still contain only the
                # Coordinator and hide a running Expert until completion.
                refresh_team = (
                    isinstance(event, (ToolExecutionStarted, ToolExecutionCompleted))
                    and event.tool_name in native_team_tools
                )
                if refresh_team:
                    await self._emit_team_snapshot(
                        workspace_id=agent_session.workspace_id,
                        parent_request_id=request.request_id,
                        task_id=agent_session.task_id,
                        heartbeat=False,
                    )

            if request.request_id in self._cancelling_agent_requests or self._closing:
                return
            if model_error is not None:
                await self._fail_request(
                    client,
                    request,
                    code="budget_exhausted" if model_error.code == "budget_exhausted" else "model_error",
                    message=(model_error.message if model_error.retries_exhausted or model_error.code == "budget_exhausted" else
                             "Model call failed: " + model_error.message),
                    recoverable=model_error.recoverable,
                    details={"reason": model_error.message, "model_error_code": model_error.code,
                             "recovery_state": "awaiting_user_retry" if model_error.retries_exhausted
                             else "configuration_required" if model_error.code == "model_configuration_error"
                             else "interrupted"},
                )
                return
            native_tasks = list(self._native_task_activity.get(request.request_id, {}).values())
            coordinator_result = self.store.get_coordinator_result(request.request_id)
            if coordinator_result is None:
                # Agent Server closes its stream after file-backed Coordinator
                # delivery. Its last answer is report text, not the model's
                # interim waiting message or final "saved" acknowledgement.
                fallback_text = last_assistant_text.strip()
                if fallback_text:
                    fallback_evidence = ()
                    fallback_results = ()
                    # The graph already read the backend-assigned Coordinator
                    # report and delivered that exact file content. Keep that
                    # file as the single report instead of copying it into a
                    # second result store or manufacturing a notebook.
                    coordinator_result = CoordinatorResult(
                        answer_markdown=fallback_text,
                        evidence_refs=fallback_evidence,
                        result_refs=fallback_results,
                    )
                    coordinator_result = self.store.record_coordinator_result(
                        request_id=request.request_id,
                        result=coordinator_result,
                    )
            if coordinator_result is None:
                await self._fail_request(
                    client,
                    request,
                    code="model_error",
                    message="OceanX stopped without a user-facing conclusion",
                    recoverable=True,
                    details={},
                )
                return
            final_assistant_text = (
                coordinator_result.answer_markdown
                if coordinator_result is not None
                else last_assistant_text
            )
            if agent_session.task_id is not None:
                self.store.update_task_workflow_progress(
                    request_id=request.request_id,
                    activity="Coordinator response received",
                )
            await self._append_transcript_item(
                client,
                request,
                role="assistant",
                text=final_assistant_text,
            )
            team_provenance = {
                "architecture": "deepagents_native_task",
                "activation_count": len(native_tasks),
                "routing_decision": {
                    "strategy": (
                        "direct"
                        if not native_tasks
                        else "single_delegate"
                        if len(native_tasks) == 1
                        else "team_with_discussion"
                        if any(
                            str(item.get("agent_name")) == "scientific_discussion_partner"
                            for item in native_tasks
                        )
                        else "parallel_team"
                    ),
                    "worker_count": len(native_tasks),
                },
                "actual_usage": {"input_tokens": usage_input_tokens,
                                 "output_tokens": usage_output_tokens,
                                 "turns": turn_count, "tool_calls": tool_call_count},
                "code_executions": [
                    {
                        "execution_id": execution.execution_id,
                        "agent_thread_id": execution.agent_thread_id,
                        "server_run_id": execution.server_run_id,
                        "state": execution.state,
                        "result": execution.result,
                    }
                    for execution in (self.store.list_task_code_executions(
                        workspace_id=agent_session.workspace_id,
                        task_id=agent_session.task_id) if agent_session.task_id else ())
                ],
                "work": native_tasks,
                # Scientific discussion is advisory. Human approval is a
                # separate user decision and is never inferred from consulting
                # the Discussion Partner.
                "human_approval_required": False,
            }

            terminal = self._completed_event(
                client,
                request,
                result={
                    "provider_id": agent_session.runtime.provider_id,
                    "model_id": agent_session.runtime.model_id,
                    "assistant_text": self._bounded_text(final_assistant_text, 64_000),
                    "turn_count": turn_count,
                    "tool_call_count": tool_call_count,
                    "usage": {
                        "input_tokens": usage_input_tokens,
                        "output_tokens": usage_output_tokens,
                    },
                    "team_provenance": team_provenance,
                },
                workspace_revision=self.store.workspace_snapshot(
                    agent_session.workspace_id
                ).revision,
            )
            if agent_session.task_id is None:
                self.store.commit_terminal(request.request_id, terminal)
            else:
                self.store.commit_task_terminal(
                    request_id=request.request_id,
                    terminal_event=terminal,
                )
            await self._emit_team_snapshot(
                workspace_id=agent_session.workspace_id,
                parent_request_id=request.request_id,
                task_id=agent_session.task_id,
                heartbeat=False,
            )
            await self._broadcast_committed_terminal(client, terminal)
        except asyncio.CancelledError:
            if request.request_id in self._cancelling_agent_requests or self._closing:
                return
            raise
        except CrashAfterTerminalCommit:
            raise
        except Exception as exc:  # pragma: no cover - final foreground-task boundary
            if request.request_id not in self._cancelling_agent_requests and not self._closing:
                await self._fail_request(
                    client,
                    request,
                    code="model_error",
                    message="Ocean agent foreground task failed",
                    recoverable=True,
                    details={"reason": str(exc)},
                )
        finally:
            self._agent_tasks.pop(request.request_id, None)
            self._agent_request_sessions.pop(request.request_id, None)
            self._agent_request_clients.pop(request.request_id, None)
            self._team_snapshot_revisions.pop(request.request_id, None)
            self._schedule_research_consolidation(request)

    def _update_task_workflow_for_event(
        self,
        request: SessionSubmitRequest,
        event: StreamEvent,
    ) -> None:
        """Project generic model/tool events onto the durable task lifecycle."""

        if self._task_id(request) is None:
            return
        state: TaskWorkflowState | None = None
        activity: str | None = None
        failure_fingerprint: str | None = None
        if isinstance(event, ToolExecutionStarted):
            if event.tool_name == "ocean_expert_run_code":
                state, activity = "working", "Expert running code"
            elif event.tool_name == "web_search":
                state, activity = "working", "Searching external scientific evidence"
            elif event.tool_name == "jina_reader":
                state, activity = "working", "Reading a selected scientific source"
            elif event.tool_name == "task":
                state, activity = "working", "Delegating a research subquestion"
        elif isinstance(event, ToolExecutionCompleted):
            if event.is_error:
                state = "working"
                activity = "Expert adjusting its method after a tool failure"
                failure_fingerprint = hashlib.sha256(
                    f"{event.tool_name}\0{event.output}".encode()
                ).hexdigest()
            elif event.tool_name == "ocean_expert_run_code":
                state, activity = "working", "Expert interpreting the code result"
            elif event.tool_name == "web_search":
                state, activity = "working", "Reviewing external search evidence"
            elif event.tool_name == "jina_reader":
                state, activity = "working", "Interpreting the selected paper"
            elif event.tool_name == "task":
                state, activity = "working", "Expert result returned"
        elif isinstance(event, AssistantTurnComplete) and not event.message.tool_uses:
            state, activity = "working", "Preparing the final answer"
        if state is not None and activity is not None:
            self.store.transition_task_workflow(
                request_id=request.request_id,
                state=state,
                activity=activity,
                failure_fingerprint=failure_fingerprint,
            )

    async def _emit_agent_stream_event(
        self,
        client: BackendClient,
        request: SessionSubmitRequest,
        event: StreamEvent,
    ) -> None:
        """Translate core events without making assistant turn completion terminal."""

        workspace_id = self._workspace_id(request)
        task_id = self._task_id(request)
        if isinstance(event, AssistantTextDelta):
            if event.turn_id is None:
                return
            await self.event_bus.emit_local(
                client,
                AssistantDeltaEvent(
                    **self._event_fields(
                        client,
                        request_id=request.request_id,
                        workspace_id=workspace_id,
                        task_id=task_id,
                    ),
                    type="assistant.delta",
                    payload=AssistantDeltaPayload(
                        turn_id=event.turn_id,
                        text=self._bounded_text(event.text, 16_000),
                    ),
                ),
            )
            return
        if isinstance(event, AssistantTurnComplete):
            if event.turn_id is None:
                return
            if event.message.text.strip():
                await self._append_transcript_item(
                    client,
                    request,
                    role="assistant",
                    text=event.message.text,
                    turn_id=event.turn_id,
                )
            await self.event_bus.emit_local(
                client,
                AssistantTurnCompletedEvent(
                    **self._event_fields(
                        client,
                        request_id=request.request_id,
                        workspace_id=workspace_id,
                        task_id=task_id,
                    ),
                    type="assistant.turn.completed",
                    payload=AssistantTurnCompletedPayload(
                        turn_id=event.turn_id,
                        text=self._bounded_text(event.message.text, 64_000),
                        tool_call_ids=tuple(item.id for item in event.message.tool_uses),
                        input_tokens=event.usage.input_tokens,
                        output_tokens=event.usage.output_tokens,
                    ),
                ),
            )
            return
        if isinstance(event, ToolExecutionStarted):
            if event.turn_id is None or event.tool_call_id is None:
                return
            await self.event_bus.emit_local(
                client,
                ToolCallStartedEvent(
                    **self._event_fields(
                        client,
                        request_id=request.request_id,
                        workspace_id=workspace_id,
                        task_id=task_id,
                    ),
                    type="tool.call.started",
                    payload=ToolCallStartedPayload(
                        turn_id=event.turn_id,
                        tool_call_id=event.tool_call_id,
                        operation_id=event.operation_id,
                        tool_name=event.tool_name,
                        input=event.tool_input,
                    ),
                ),
            )
            return
        if isinstance(event, ToolExecutionCompleted):
            if event.turn_id is None or event.tool_call_id is None:
                return
            output = self._bounded_text(event.output, 64_000)
            activity_only = bool(
                event.metadata is not None and event.metadata.get("display") == "activity"
            )
            await self.event_bus.emit_local(
                client,
                ToolCallCompletedEvent(
                    **self._event_fields(
                        client,
                        request_id=request.request_id,
                        workspace_id=workspace_id,
                        task_id=task_id,
                    ),
                    type="tool.call.completed",
                    payload=ToolCallCompletedPayload(
                        turn_id=event.turn_id,
                        tool_call_id=event.tool_call_id,
                        operation_id=event.operation_id,
                        tool_name=event.tool_name,
                        # Tool responses remain available to the model but are not user-chat
                        # content. Ocean tools explicitly mark their detailed contracts private.
                        output="" if activity_only else output,
                        is_error=event.is_error,
                        duration_seconds=event.duration_seconds,
                        metadata=event.metadata,
                    ),
                ),
            )
            return
        if isinstance(event, CompactProgressEvent):
            await self.event_bus.emit_local(
                client,
                ContextCompactionProgressEvent(
                    **self._event_fields(
                        client,
                        request_id=request.request_id,
                        workspace_id=workspace_id,
                        task_id=task_id,
                    ),
                    type="context.compaction.progress",
                    payload=ContextCompactionProgressPayload(
                        phase=event.phase,
                        trigger=event.trigger,
                        message=event.message,
                        attempt=event.attempt,
                        checkpoint=event.checkpoint,
                        metadata=event.metadata,
                    ),
                ),
            )
            return
        if isinstance(event, (StatusEvent, ErrorEvent)):
            await self._append_transcript_item(
                client,
                request,
                role="system",
                text=self._bounded_text(event.message, 64_000),
            )

    async def _append_transcript_item(
        self,
        client: BackendClient,
        request: SessionSubmitRequest,
        *,
        role: Literal["user", "assistant", "tool", "system"],
        text: str,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        item_id = f"tr_{uuid4().hex}"
        task_id = self._task_id(request)
        if task_id is not None:
            self.store.append_task_transcript_item(
                task_id=task_id,
                item_id=item_id,
                role=role,
                text=self._bounded_text(text, 64_000),
                request_id=request.request_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
            )
        event = TranscriptItemAppendedEvent(
            **self._event_fields(
                client,
                request_id=request.request_id,
                workspace_id=self._workspace_id(request),
                task_id=task_id,
            ),
            type="transcript.item.appended",
            payload=TranscriptItemAppendedPayload(
                item_id=item_id,
                role=role,
                text=self._bounded_text(text, 64_000),
                turn_id=turn_id,
                tool_call_id=tool_call_id,
            ),
        )
        await self.event_bus.emit_local(client, event)

    async def _cancel_agent_request(
        self,
        client: BackendClient,
        *,
        cancel_request: RequestEnvelope,
        target_request_id: str,
        reason: str,
    ) -> None:
        """Stop the model loop before committing both durable cancellation terminals."""

        target = self.store.get_request(target_request_id)
        if target is None:
            raise RequestNotFound(target_request_id)
        self._cancelling_agent_requests.add(target_request_id)
        task = self._agent_tasks.get(target_request_id)
        if task is not None and not task.done():
            # The foreground asyncio Task owns the Coordinator stream and any
            # currently awaited task/Expert subtree. Cancelling that
            # task is the single supported DeepAgent interruption boundary;
            # DeepAgentEngine deliberately has no parallel cancel_active API.
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        refreshed_target = self.store.get_request(target_request_id)
        if refreshed_target is None:
            raise RequestNotFound(target_request_id)
        target_event: EventEnvelope | None = None
        if not refreshed_target.terminal:
            target_event = RequestCancelledEvent(
                **self._event_fields(
                    client,
                    request_id=target_request_id,
                    workspace_id=refreshed_target.workspace_id,
                    session_id=refreshed_target.session_id,
                    task_id=refreshed_target.task_id,
                ),
                type="request.cancelled",
                payload=RequestCancelledPayload(reason=reason),
            )
        terminal = self._completed_event(
            client,
            cancel_request,
            result={
                "target_request_id": target_request_id,
                "target_state": "cancelled" if target_event is not None else refreshed_target.state,
            },
        )
        commit = self.store.commit_cancellation(
            cancel_request_id=cancel_request.request_id,
            target_request_id=target_request_id,
            target_event=target_event,
            terminal_event=terminal,
        )
        self._cancelling_agent_requests.discard(target_request_id)
        await self._emit_team_snapshot(
            workspace_id=refreshed_target.workspace_id,
            parent_request_id=target_request_id,
            task_id=refreshed_target.task_id,
            heartbeat=False,
            client=client,
        )
        await self._run_terminal_commit_hook(terminal)
        if commit.target_terminal_event is not None:
            await self.event_bus.emit_request_session(
                commit.target_terminal_event,
                session_id=refreshed_target.session_id,
                principal_key=refreshed_target.principal,
            )
        await self.event_bus.emit_local(client, terminal)

    @staticmethod
    def _operation_id(request_id: str, turn_id: str, tool_call_id: str) -> str:
        material = "\x1f".join((request_id, turn_id, tool_call_id)).encode("utf-8")
        return f"op_{hashlib.sha256(material).hexdigest()}"

    @staticmethod
    def _bounded_text(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 3)] + "..."

    async def _task_report_read(self, client, request):
        workspace_id = self._workspace_id(request)
        self._task_in_workspace(request.payload.task_id, request)
        del workspace_id
        root = (self.task_workspace_projector.ensure_task_root(request.payload.task_id) /
                "agents").resolve()
        report = Path(request.payload.report_path).resolve()
        if (not report.is_relative_to(root) or report.name != "report.md"
                or report.is_symlink() or not report.is_file()):
            raise RequestStoreError("Report is unavailable in this task")
        # UI-only paging keeps long Markdown out of snapshot frames and model context.
        with report.open(encoding="utf-8") as stream:
            remaining = request.payload.offset
            while remaining:
                skipped = stream.read(min(remaining, 16_000))
                if not skipped:
                    break
                remaining -= len(skipped)
            text = stream.read(16_000)
            more = bool(stream.read(1))
        terminal = self._completed_event(client, request, result={
            "text": text, "next_offset": request.payload.offset + len(text) if more else None})
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _native_team_snapshot_payload(
        self, *, workspace_id: str, parent_request_id: str,
        task_id: str | None, revision: int,
        native_tasks: list[dict[str, Any]] | None = None,
        include_unassigned: bool = True,
    ) -> TeamSnapshotPayload:
        """Project native ``task`` events for the UI; never persist a scheduler."""
        request = self.store.get_request(parent_request_id)
        terminal = request is not None and request.state in {"completed", "failed", "cancelled", "interrupted"}
        team_status = (
            "completed" if request and request.state == "completed"
            else "failed" if request and request.state == "failed"
            else "incomplete" if terminal
            else "working"
        )
        coordinator_activity = (
            "Task completed" if team_status == "completed"
            else "Task failed" if team_status == "failed"
            else "Task stopped before completion" if team_status == "incomplete"
            else "Coordinating research"
        )
        agents = [TeamAgentPayload(
            agent_id="coordinator", profile_id=None, semantic_role="Coordinator",
            authority="coordinator", status=team_status,
            activity=coordinator_activity,
            created_at=request.created_at if request is not None else None,
            updated_at=request.updated_at if request is not None else None,
        )]
        dependencies = []
        interactions = []
        todos = []
        native: list[dict[str, Any]] = []
        if native_tasks is not None:
            native = [
                item for item in native_tasks
                if item.get("request_id") == parent_request_id
                or (include_unassigned and not item.get("request_id"))
            ]
        else:
            native = list(self._native_task_activity.get(parent_request_id, {}).values())
        from oceanx.research.services import expert_agent_key, expert_result_preview
        participants: dict[str, TeamAgentPayload] = {}
        for item in native:
            call_id = str(item.get("task_id") or item.get("thread_id") or "")
            if not call_id:
                continue
            profile_id = str(item.get("agent_name") or item.get("subagent_type") or "expert")
            question = str(item.get("description") or item.get("input") or "Research subquestion")
            child_id = str(item.get("agent_key") or expert_agent_key(
                task_id or "", profile_id, question, item.get("node_id")))
            question = self._bounded_text(question, 8_000)
            profile = next((p for p in AGENT_PROFILES if p.profile_id == profile_id), None)
            raw_status = str(item.get("status") or "pending").lower()
            if raw_status in {"completed", "success", "succeeded", "done"}:
                status = "completed"
            elif raw_status in {"failed", "error", "timeout"}:
                status = "failed"
            elif raw_status == "cancelled":
                status = "skipped"
            elif raw_status == "interrupted":
                status = "incomplete"
            elif raw_status in {"pending", "queued"}:
                status = "planning"
            else:
                status = "working"
            # A terminal parent cannot still be waiting for a synchronous task.
            # Missing task-end events mean interrupted work, not successful delivery.
            if terminal and status in {"working", "planning"}:
                status = "incomplete"
            report_path = item.get("report_path") if isinstance(item.get("report_path"), str) else None
            summary = item.get("summary") if isinstance(item.get("summary"), str) else ""
            report_preview = expert_result_preview(summary)
            run_id = str(item.get("run_id") or call_id)
            activity = (
                self._bounded_text(report_preview, 320) if status == "completed" and report_preview
                else "Result returned" if status == "completed"
                else "Expert run failed" if status == "failed"
                else "Expert run was cancelled" if status == "skipped"
                else "Expert run was interrupted" if status == "incomplete"
                else self._bounded_text(question, 512)
            )
            participant = TeamAgentPayload(
                agent_id=child_id, expert_key=child_id, profile_id=profile_id,
                semantic_role=profile.display_name if profile else profile_id,
                authority=(profile.authority.value if profile else "expert"),
                status=status, activity=activity,
                agent_run_id=run_id, task_goal=question, report_path=report_path,
                report_title=(self._bounded_text(report_preview, 220) or "Research report")
                if report_path else None,
                created_at=str(item.get("run_created_at") or item.get("created_at") or "") or None,
                updated_at=str(
                    item.get("run_updated_at") or item.get("last_updated_at")
                    or item.get("last_checked_at") or ""
                ) or None,
            )
            previous = participants.get(child_id)
            # Keep one participant for repeat assignments. A still-active call
            # takes precedence over another call's completion, regardless of
            # completion order. Otherwise the latest assignment is displayed.
            if previous is None or status in {"working", "planning"} or previous.status not in {"working", "planning"}:
                participants[child_id] = participant
            todos.append(TeamTodoPayload(
                todo_id=call_id, expert_key=child_id, question=question, depends_on=(), profile_id=profile_id,
                expected_outputs=(), state=("result_returned" if status == "completed"
                                            else "stopped" if status in {"failed", "skipped", "incomplete"}
                                            else "pending" if status == "planning" else "working"),
                agent_run_id=run_id, session_round=None, report_path=report_path,
                report_title=(self._bounded_text(report_preview, 220) or "Research report")
                if report_path else None,
                created_at=str(item.get("run_created_at") or item.get("created_at") or "") or None,
                updated_at=str(
                    item.get("run_updated_at") or item.get("last_updated_at")
                    or item.get("last_checked_at") or ""
                ) or None,
            ))
            interactions.append(TeamInteractionPayload(
                interaction_id=f"interaction_{call_id}",
                from_agent_id="coordinator", to_agent_id=child_id,
                kind="delegation", summary=self._bounded_text(question, 512),
                state="active" if status in {"working", "planning"} else "completed"))
        agents.extend(participants.values())
        dependencies = [TeamDependencyPayload(
            from_agent_id="coordinator", to_agent_id=key, kind="delegation") for key in participants]
        strategy = ("direct" if not participants else "single_delegate" if len(participants) == 1
                    else "team_with_discussion" if any(
                        str(item.get("agent_name")) == "scientific_discussion_partner" for item in native)
                    else "parallel_team")
        return TeamSnapshotPayload(
            request_id=parent_request_id, revision=max(1, revision), status=team_status,
            strategy=strategy,
            role_pool=tuple(TeamAgentProfilePayload(
                profile_id=p.profile_id, display_name=p.display_name,
                authority=p.authority.value, category=p.category, summary=p.summary)
                for p in AGENT_PROFILES),
            agents=tuple(agents), todos=tuple(todos), dependencies=tuple(dependencies),
            interactions=tuple(interactions),
        )

    async def _emit_team_snapshot(
        self,
        *,
        workspace_id: str,
        parent_request_id: str,
        task_id: str | None,
        heartbeat: bool = True,
        client: BackendClient | None = None,
    ) -> None:
        client = client or self._agent_request_clients.get(parent_request_id)
        if client is None:
            return
        if heartbeat:
            self.store.update_task_workflow_progress(
                request_id=parent_request_id,
                activity="Coordinating active team members",
            )
        revision = self._team_snapshot_revisions.get(parent_request_id, 0) + 1
        self._team_snapshot_revisions[parent_request_id] = revision
        await self.event_bus.emit_local(
            client,
            TeamSnapshotEvent(
                **self._event_fields(
                    client,
                    request_id=parent_request_id,
                    workspace_id=workspace_id,
                    task_id=task_id,
                ),
                type="team.snapshot",
                payload=await self._native_team_snapshot_payload(
                    workspace_id=workspace_id,
                    parent_request_id=parent_request_id,
                    task_id=task_id,
                    revision=revision,
                ),
            ),
        )

    async def _session_open(self, client: BackendClient, request: SessionOpenRequest) -> None:
        terminal = self._completed_event(
            client,
            request,
            result={
                "session_id": client.session_id,
                "workspace_id": request.payload.requested_workspace_id
                or (request.context.workspace_id if request.context else None),
            },
        )
        self.store.commit_session_open(
            request_id=request.request_id,
            session_id=client.session_id or "",
            principal=client.principal.key if client.principal else "",
            workspace_id=request.payload.requested_workspace_id
            or (request.context.workspace_id if request.context else None),
            terminal_event=terminal,
        )
        await self._broadcast_committed_terminal(client, terminal)

    async def _workspace_open(self, client: BackendClient, request: WorkspaceOpenRequest) -> None:
        workspace_id = self._workspace_id(request)

        def event_factory(
            snapshot: WorkspaceSnapshot,
            previous_revision: int,
            change: str | None,
        ) -> tuple[EventEnvelope | None, EventEnvelope]:
            changed_event: EventEnvelope | None = None
            if change is not None:
                changed_event = WorkspaceChangedEvent(
                    **self._event_fields(
                        client, request_id=request.request_id, workspace_id=workspace_id
                    ),
                    type="workspace.changed",
                    payload=WorkspaceChangedPayload(
                        previous_revision=previous_revision,
                        workspace_revision=snapshot.revision,
                        change=change,
                    ),
                )
            return changed_event, self._completed_event(
                client,
                request,
                result=snapshot.as_payload(),
                workspace_revision=snapshot.revision,
            )

        commit = self.store.commit_workspace_open(
            request_id=request.request_id,
            workspace_id=workspace_id,
            path=request.payload.path,
            expected_revision=request.expected_workspace_revision,
            event_factory=event_factory,
        )
        await self._run_terminal_commit_hook(commit.terminal_event)
        if commit.changed_event is not None:
            await self.event_bus.emit_workspace(commit.changed_event)
        await self.event_bus.emit_local(client, commit.terminal_event)

    async def _workspace_snapshot(
        self,
        client: BackendClient,
        request: WorkspaceSnapshotGetRequest,
    ) -> None:
        snapshot = self.store.workspace_snapshot(self._workspace_id(request))
        snapshot_event = WorkspaceSnapshotEvent(
            **self._event_fields(
                client, request_id=request.request_id, workspace_id=snapshot.workspace_id
            ),
            type="workspace.snapshot",
            payload=WorkspaceSnapshotPayload(**snapshot.as_payload()),
        )
        terminal = self._completed_event(
            client,
            request,
            result=snapshot.as_payload(),
            workspace_revision=snapshot.revision,
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._run_terminal_commit_hook(terminal)
        await self.event_bus.emit_local(client, snapshot_event)
        await self.event_bus.emit_local(client, terminal)

    async def _task_create(self, client: BackendClient, request: TaskCreateRequest) -> None:
        task = self.store.create_research_task(
            workspace_id=self._workspace_id(request), title=request.payload.title
        )
        await self._sync_task_workspace(task.task_id)
        terminal = self._completed_event(client, request, result={"task": task.as_summary()})
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _task_list(self, client: BackendClient, request: TaskListRequest) -> None:
        tasks = self.store.list_research_tasks(
            workspace_id=self._workspace_id(request),
            include_archived=request.payload.include_archived,
            limit=request.payload.limit,
        )
        terminal = self._completed_event(
            client, request, result={"tasks": [task.as_summary() for task in tasks]}
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _task_get_or_open(self, client: BackendClient, request: TaskGetRequest) -> None:
        task = self._task_in_workspace(request.payload.task_id, request)
        if request.type == "task.open":
            # The canonical Task can predate user-visible task folders.  Reconcile
            # that lightweight projection before returning the snapshot; this creates
            # the stable folder/manifest only and never inspects source payloads.
            await self._ensure_task_workspace_root(task.task_id)
            await self._emit_task_snapshot(client, request, task_id=task.task_id)
            return
        terminal = self._completed_event(client, request, result={"task": task.as_summary()})
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _task_rename(self, client: BackendClient, request: TaskRenameRequest) -> None:
        self._task_in_workspace(request.payload.task_id, request)
        task = self.store.rename_research_task(
            task_id=request.payload.task_id,
            title=request.payload.title,
            expected_task_revision=request.expected_task_revision,
        )
        await self._sync_task_workspace(task.task_id)
        terminal = self._completed_event(client, request, result={"task": task.as_summary()})
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _task_archive_or_reopen(
        self, client: BackendClient, request: TaskArchiveRequest
    ) -> None:
        self._task_in_workspace(request.payload.task_id, request)
        task = self.store.set_research_task_status(
            task_id=request.payload.task_id,
            status="archived" if request.type == "task.archive" else "active",
            expected_task_revision=request.expected_task_revision,
        )
        await self._sync_task_workspace(task.task_id)
        terminal = self._completed_event(client, request, result={"task": task.as_summary()})
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _task_delete(self, client: BackendClient, request: TaskDeleteRequest) -> None:
        self._task_in_workspace(request.payload.task_id, request)
        self.store.delete_research_task(
            task_id=request.payload.task_id,
            expected_task_revision=request.expected_task_revision,
            in_flight_request_id=request.request_id,
        )
        terminal = self._completed_event(
            client, request, result={"task_id": request.payload.task_id}
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _task_snapshot(self, client: BackendClient, request: TaskSnapshotGetRequest) -> None:
        self._task_in_workspace(request.payload.task_id, request)
        await self._emit_task_snapshot(client, request, task_id=request.payload.task_id)

    async def _task_agent_transcript(
        self,
        client: BackendClient,
        request: TaskAgentTranscriptGetRequest,
    ) -> None:
        """Return one selected participant's durable conversation on demand."""

        workspace_id = self._workspace_id(request)
        task_id = request.payload.task_id
        self._task_in_workspace(task_id, request)
        parent = self.store.get_request(request.payload.parent_request_id)
        if (
            parent is None
            or parent.workspace_id != workspace_id
            or parent.task_id != task_id
            or parent.request_type != "session.submit"
        ):
            raise RequestStoreError("Agent transcript parent request is not part of this task")

        if request.payload.agent_id == "coordinator":
            coordinator_items = self.store.list_task_transcript_for_request(
                task_id=task_id,
                request_id=request.payload.parent_request_id,
            )
            messages = [
                {
                    "message_id": item.item_id,
                    "role": "coordinator" if item.role == "assistant" else item.role,
                    "blocks": [{"type": "text", "text": item.text}],
                    "created_at": item.created_at,
                    "interrupted": item.interrupted,
                }
                for item in coordinator_items
            ]
            result = {
                "agent_id": "coordinator",
                "agent_run_id": "coordinator",
                "messages": messages,
                "updated_at": messages[-1]["created_at"] if messages else None,
            }
        else:
            task = self._native_task_activity.get(request.payload.parent_request_id, {}).get(
                request.payload.agent_run_id or request.payload.agent_id
            )
            if task is None:
                raise RequestStoreError("Selected native Expert task was not found")
            created_at = task.get("created_at")
            updated_at = task.get("last_updated_at")
            messages = [{
                "message_id": f"{request.payload.agent_id}:assignment",
                "role": "coordinator",
                "blocks": [{"type": "text", "text": str(task.get("description") or "")}],
                "created_at": created_at,
                "interrupted": False,
            }]
            if task.get("output"):
                messages.append({
                    "message_id": f"{request.payload.agent_id}:receipt",
                    "role": "expert",
                    "blocks": [{"type": "text", "text": str(task["output"])}],
                    "created_at": updated_at,
                    "interrupted": task.get("status") != "completed",
                })
            result = {
                "agent_id": request.payload.agent_id,
                "agent_run_id": str(request.payload.agent_run_id or request.payload.agent_id),
                "messages": messages,
                "updated_at": updated_at,
            }

        terminal = self._completed_event(client, request, result=result)
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    @staticmethod
    def _renderer_agent_messages(
        messages: tuple[dict[str, Any], ...],
        *,
        message_times: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Remove binary image bodies while preserving every conversational block."""

        rendered: list[dict[str, Any]] = []
        message_times = message_times or {}
        for message_index, message in enumerate(messages):
            raw_role = str(message.get("role") or message.get("type") or "")
            role = (
                "coordinator" if raw_role in {"user", "human"}
                else "tool" if raw_role == "tool"
                else "system" if raw_role == "system"
                else "expert"
            )
            blocks: list[dict[str, Any]] = []
            raw_blocks = message.get("content")
            if isinstance(raw_blocks, str):
                if raw_role == "tool":
                    blocks.append({
                        "type": "tool_result",
                        "tool_call_id": str(message.get("tool_call_id") or ""),
                        "text": raw_blocks,
                        "is_error": str(message.get("status") or "") == "error",
                    })
                elif raw_blocks:
                    blocks.append({"type": "text", "text": raw_blocks})
                raw_blocks = []
            elif not isinstance(raw_blocks, list):
                raw_blocks = []
            for block in raw_blocks:
                if isinstance(block, str):
                    blocks.append({"type": "text", "text": block})
                    continue
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type in {"text", "output_text", "input_text"}:
                    blocks.append({"type": "text", "text": str(block.get("text", ""))})
                elif block_type == "tool_use":
                    blocks.append(
                        {
                            "type": "tool_call",
                            "tool_call_id": str(block.get("id", "")),
                            "tool_name": str(block.get("name", "Tool")),
                            "input": block.get("input")
                            if isinstance(block.get("input"), dict)
                            else {},
                        }
                    )
                elif block_type == "tool_result":
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_call_id": str(block.get("tool_use_id", "")),
                            "text": str(block.get("content", "")),
                            "is_error": bool(block.get("is_error", False)),
                        }
                    )
                elif block_type == "image":
                    blocks.append(
                        {
                            "type": "attachment",
                            "media_type": str(block.get("media_type", "image")),
                            "source_path": str(block.get("source_path", "")),
                        }
                    )
            for call in message.get("tool_calls") or ():
                if not isinstance(call, dict):
                    continue
                blocks.append({
                    "type": "tool_call",
                    "tool_call_id": str(call.get("id") or ""),
                    "tool_name": str(call.get("name") or "Tool"),
                    "input": call.get("args") if isinstance(call.get("args"), dict) else {},
                })
            native_message_id = str(message.get("id") or "")
            rendered_message = {
                "message_id": native_message_id or f"agent-message-{message_index + 1}",
                "role": role,
                "blocks": blocks,
            }
            created_at = message_times.get(native_message_id) if native_message_id else None
            if created_at:
                rendered_message["created_at"] = created_at
            rendered.append(rendered_message)
        return rendered

    async def _task_output_list(
        self, client: BackendClient, request: TaskOutputListRequest
    ) -> None:
        self._task_in_workspace(request.payload.task_id, request)
        outputs = self.store.list_task_output_summaries(
            task_id=request.payload.task_id, limit=request.payload.limit
        )
        from oceanx.delivery import build_delivery_manifests

        terminal = self._completed_event(
            client,
            request,
            result={
                "outputs": outputs,
                "delivery_manifests": [
                    manifest.model_dump(mode="json")
                    for manifest in build_delivery_manifests(outputs)
                ],
                "task_results": (
                    list(self.task_results.list_payloads(task_id=request.payload.task_id))
                    if self.task_results is not None
                    else []
                ),
            },
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _emit_task_snapshot(
        self, client: BackendClient, request: RequestEnvelope, *, task_id: str
    ) -> None:
        # Snapshot reads do not project the filesystem.  ``task.open`` performs one
        # bounded reconciliation immediately before entering this method so legacy
        # canonical Tasks still acquire their stable user-visible folder.
        if isinstance(request, TaskSnapshotGetRequest):
            limit = request.payload.transcript_limit
            before_sequence = request.payload.before_sequence
        else:
            limit = 100
            before_sequence = None
        snapshot = self.store.task_snapshot(
            task_id=task_id,
            transcript_limit=limit,
            before_sequence=before_sequence,
        )
        payload_data = snapshot.as_payload()
        # Keep interactive navigation latency independent of the number of
        # durable result manifests. The desktop asks for ``task.output.list``
        # immediately after rendering ``task.open``; explicit snapshot reads
        # retain their complete payload for protocol compatibility.
        payload_data["task_results"] = (
            list(self.task_results.list_payloads(task_id=task_id))
            if isinstance(request, TaskSnapshotGetRequest) and self.task_results is not None
            else []
        )
        team_request_id = snapshot.task.active_request_id or (
            snapshot.workflow.request_id if snapshot.workflow is not None else None
        )
        team_snapshots = []
        for workflow in self.store.list_task_workflows(task_id):
            team_snapshots.append(await self._native_team_snapshot_payload(
                workspace_id=snapshot.task.workspace_id,
                parent_request_id=workflow.request_id,
                task_id=task_id,
                revision=self._team_snapshot_revisions.get(workflow.request_id, 1),
                native_tasks=list(self._native_task_activity.get(workflow.request_id, {}).values()),
                include_unassigned=False,
            ))
        payload_data["team_snapshots"] = [item.model_dump(mode="json") for item in team_snapshots]
        current_team = next(
            (item for item in team_snapshots if item.request_id == team_request_id),
            None,
        )
        payload_data["team_snapshot"] = (
            current_team.model_dump(mode="json") if current_team is not None else None
        )
        payload = TaskSnapshotPayload.model_validate(payload_data)
        snapshot_event = TaskSnapshotEvent(
            **self._event_fields(
                client,
                request_id=request.request_id,
                workspace_id=snapshot.task.workspace_id,
                task_id=task_id,
            ),
            type="task.snapshot",
            payload=payload,
        )
        terminal = self._completed_event(client, request, result=payload.model_dump(mode="json"))
        self.store.commit_terminal(request.request_id, terminal)
        await self._run_terminal_commit_hook(terminal)
        await self.event_bus.emit_local(client, snapshot_event)
        await self.event_bus.emit_local(client, terminal)

    async def _request_status(
        self, client: BackendClient, request: RequestStatusGetRequest
    ) -> None:
        target = self.store.get_request(request.payload.target_request_id)
        if target is None or client.principal is None or target.principal != client.principal.key:
            raise RequestNotFound(request.payload.target_request_id)
        result: dict[str, Any] = {
            "request_id": target.request_id,
            "request_type": target.request_type,
            "state": target.state,
        }
        if target.terminal_event is not None:
            result["terminal_event"] = target.terminal_event.model_dump(mode="json")
        terminal = self._completed_event(client, request, result=result)
        self.store.commit_terminal(request.request_id, terminal)
        await self._broadcast_committed_terminal(client, terminal)

    async def _request_cancel(self, client: BackendClient, request: RequestCancelRequest) -> None:
        target = self.store.get_request(request.payload.target_request_id)
        if target is None or client.principal is None or target.principal != client.principal.key:
            raise RequestNotFound(request.payload.target_request_id)
        if request.payload.target_request_id in self._agent_tasks:
            await self._cancel_agent_request(
                client,
                cancel_request=request,
                target_request_id=request.payload.target_request_id,
                reason=request.payload.reason or "Cancelled by user",
            )
            return
        target_event: EventEnvelope | None = None
        if not target.terminal:
            target_event = RequestCancelledEvent(
                **self._event_fields(
                    client,
                    request_id=target.request_id,
                    workspace_id=target.workspace_id,
                    session_id=target.session_id,
                    task_id=target.task_id,
                ),
                type="request.cancelled",
                payload=RequestCancelledPayload(
                    reason=request.payload.reason or "Cancelled by user"
                ),
            )
        terminal = self._completed_event(
            client,
            request,
            result={"target_request_id": target.request_id, "target_state": "cancelled"},
        )
        commit = self.store.commit_cancellation(
            cancel_request_id=request.request_id,
            target_request_id=target.request_id,
            target_event=target_event,
            terminal_event=terminal,
        )
        await self._run_terminal_commit_hook(terminal)
        if commit.target_terminal_event is not None:
            await self.event_bus.emit_request_session(
                commit.target_terminal_event,
                session_id=target.session_id,
                principal_key=target.principal,
            )
        await self.event_bus.emit_local(client, terminal)

    async def _system_shutdown(self, client: BackendClient, request: SystemShutdownRequest) -> None:
        terminal = self._completed_event(client, request, result={"shutdown": "requested"})
        shutdown = SystemShutdownEvent(
            **self._event_fields(client, request_id=request.request_id),
            type="system.shutdown",
            payload=SystemShutdownPayload(reason=request.payload.reason),
        )
        self.store.commit_terminal(request.request_id, terminal)
        await self._run_terminal_commit_hook(terminal)
        await self.event_bus.emit_local(client, terminal)
        await self.event_bus.emit_system(shutdown)
        self.shutdown_requested = True

    async def _fail_request(
        self,
        client: BackendClient,
        request: RequestEnvelope,
        *,
        code: ErrorCode,
        message: str,
        recoverable: bool,
        details: dict[str, Any],
    ) -> None:
        event = self._failed_event(
            client,
            request,
            code=code,
            message=message,
            recoverable=recoverable,
            details=details,
        )
        record = self.store.get_request(request.request_id)
        if record is not None and not record.terminal:
            if isinstance(request, SessionSubmitRequest) and record.task_id is not None:
                self.store.commit_task_terminal(
                    request_id=request.request_id, terminal_event=event
                )
            else:
                self.store.commit_terminal(request.request_id, event)
            if isinstance(request, SessionSubmitRequest):
                await self._emit_team_snapshot(
                    workspace_id=record.workspace_id,
                    parent_request_id=request.request_id,
                    task_id=record.task_id,
                    heartbeat=False,
                )
            await self._broadcast_committed_terminal(client, event)
    async def _broadcast_committed_terminal(
        self,
        client: BackendClient,
        event: EventEnvelope,
    ) -> None:
        await self._run_terminal_commit_hook(event)
        await self.event_bus.emit_local(client, event)

    async def _run_terminal_commit_hook(self, event: EventEnvelope) -> None:
        if event.task_id is not None:
            await self._sync_task_workspace(event.task_id)
        if self.after_terminal_commit is None:
            return
        result = self.after_terminal_commit(event)
        if inspect.isawaitable(result):
            await result

    async def _sync_task_workspace(self, task_id: str) -> None:
        """Refresh a derived task folder without weakening a durable committed request."""

        if self.task_workspace_projector is None:
            return
        try:
            await asyncio.to_thread(self.task_workspace_projector.sync, task_id)
        except Exception:
            # Canonical SQLite/artifact/run state has already committed at each call site.
            # A recoverable user-facing projection must never turn that success into a
            # misleading request failure; task.open retries this idempotently.
            _LOGGER.exception("Could not refresh OceanX task folder for %s", task_id)

    async def _ensure_task_workspace_root(self, task_id: str) -> None:
        """Create only the stable task-folder shell required for navigation."""

        if self.task_workspace_projector is None:
            return
        try:
            await asyncio.to_thread(self.task_workspace_projector.ensure_task_root, task_id)
        except Exception:
            _LOGGER.exception("Could not ensure OceanX task folder for %s", task_id)

    async def _emit_system_error(
        self,
        client: BackendClient,
        *,
        code: ErrorCode,
        message: str,
        recoverable: bool,
        details: dict[str, Any],
        request_id: str | None = None,
    ) -> None:
        event = SystemErrorEvent(
            **self._event_fields(client, request_id=request_id),
            type="system.error",
            payload=SystemErrorPayload(
                error=ProtocolErrorPayload(
                    code=code,
                    message=message,
                    recoverable=recoverable,
                    details=details,
                )
            ),
        )
        await self.event_bus.emit_local(client, event)

    def _accepted_event(
        self,
        client: BackendClient,
        request: RequestEnvelope,
        *,
        state: str,
    ) -> RequestAcceptedEvent:
        return RequestAcceptedEvent(
            **self._event_fields(
                client, request_id=request.request_id, task_id=self._task_id(request)
            ),
            type="request.accepted",
            payload=RequestAcceptedPayload(request_type=request.type, state=state),
        )

    def _completed_event(
        self,
        client: BackendClient,
        request: RequestEnvelope,
        *,
        result: dict[str, Any],
        workspace_revision: int | None = None,
    ) -> RequestCompletedEvent:
        return RequestCompletedEvent(
            **self._event_fields(
                client, request_id=request.request_id, task_id=self._task_id(request)
            ),
            type="request.completed",
            payload=RequestCompletedPayload(
                result=result,
                workspace_revision=workspace_revision,
            ),
        )

    def _failed_event(
        self,
        client: BackendClient,
        request: RequestEnvelope,
        *,
        code: ErrorCode,
        message: str,
        recoverable: bool,
        details: dict[str, Any],
    ) -> RequestFailedEvent:
        return RequestFailedEvent(
            **self._event_fields(
                client, request_id=request.request_id, task_id=self._task_id(request)
            ),
            type="request.failed",
            payload=RequestFailedPayload(
                error=ProtocolErrorPayload(
                    code=code,
                    message=message,
                    recoverable=recoverable,
                    details=details,
                )
            ),
        )

    def _interrupted_event(self, record: RequestRecord) -> RequestFailedEvent:
        return RequestFailedEvent(
            protocol_version=2,
            event_id=new_event_id(),
            session_id=record.session_id,
            workspace_id=record.workspace_id,
            task_id=record.task_id,
            request_id=record.request_id,
            sequence=0,
            timestamp=datetime.now(UTC),
            type="request.failed",
            payload=RequestFailedPayload(
                error=ProtocolErrorPayload(
                    code="request_interrupted",
                    message="Backend restarted before this request finished",
                    recoverable=True,
                    details={},
                )
            ),
        )

    def _recovered_completed_event(
        self,
        record: RequestRecord,
        result: CoordinatorResult,
    ) -> RequestCompletedEvent:
        """Close a crashed request from its already-accepted durable conclusion."""

        return RequestCompletedEvent(
            protocol_version=2,
            event_id=new_event_id(),
            session_id=record.session_id,
            workspace_id=record.workspace_id,
            task_id=record.task_id,
            request_id=record.request_id,
            sequence=0,
            timestamp=datetime.now(UTC),
            type="request.completed",
            payload=RequestCompletedPayload(
                result={
                    "assistant_text": self._bounded_text(result.answer_markdown, 64_000),
                    "coordinator_result": result.model_dump(mode="json"),
                    "recovered_from_durable_receipt": True,
                }
            ),
        )

    def _event_fields(
        self,
        client: BackendClient,
        *,
        request_id: str | None,
        workspace_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "protocol_version": 2,
            "event_id": event_id or new_event_id(),
            "session_id": session_id if session_id is not None else client.session_id,
            "workspace_id": workspace_id if workspace_id is not None else client.workspace_id,
            "task_id": task_id,
            "request_id": request_id,
            "sequence": 0,
            "timestamp": datetime.now(UTC),
        }

    @staticmethod
    def _workspace_id(request: RequestEnvelope) -> str:
        if request.context is None or request.context.workspace_id is None:
            raise RequestStoreError("This request requires context.workspace_id")
        return request.context.workspace_id

    @staticmethod
    def _task_id(request: RequestEnvelope) -> str | None:
        return request.context.task_id if request.context is not None else None

    def _submitted_text_with_context_refs(
        self,
        *,
        workspace_id: str,
        task_id: str | None,
        text: str,
        context_refs: tuple[ArtifactRef, ...],
    ) -> str:
        """Attach the task's durable source memory to every Coordinator turn.

        The renderer may add exact immutable references for a single turn, but the task's
        source links are server-owned and automatically inherited. This keeps the
        sidebar and task source set aligned on which inputs belong to the task.
        """

        refs: list[ArtifactRef] = []
        if task_id is not None:
            for record in self.store.list_task_artifacts(task_id=task_id):
                artifact = record.artifact
                if artifact.workspace_id != workspace_id:
                    continue
                if "source" in record.relations and artifact.artifact_type in {"dataset", "paper"}:
                    refs.append(artifact.ref)
        refs.extend(context_refs)
        unique_refs = list(dict.fromkeys(refs))
        if not unique_refs:
            return text
        lines = [
            "[Task-owned immutable sources available to this turn. These are routing identities; "
            "delegate scientific content inspection to the relevant Expert:]"
        ]
        for index, ref in enumerate(unique_refs, start=1):
            artifact = self.store.get_artifact(workspace_id=workspace_id, ref=ref)
            if artifact is None:
                raise RequestNotFound(ref.key)
            lines.append(
                f"- source_{index}: {ref.artifact_id}@v{ref.version} "
                f"({artifact.artifact_type}; {artifact.title})"
            )
        return f"{text}\n\n" + "\n".join(lines)

    def _task_in_workspace(self, task_id: str, request: RequestEnvelope):
        task = self.store.get_research_task(task_id, workspace_id=self._workspace_id(request))
        if task is None:
            raise TaskNotFound(task_id)
        return task

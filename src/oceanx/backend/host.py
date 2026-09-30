"""Protocol v2 stdio host; stdout is reserved exclusively for OHJSON frames."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import BinaryIO

from oceanx.artifacts.files import ArtifactFileStore
from oceanx.artifacts.service import ArtifactService
from oceanx.backend.events import BackendClient, EventBus
from oceanx.backend.router import OceanRequestRouter
from oceanx.backend.store import RequestStore
from oceanx.cache_cleanup import TaskCacheCleaner
from oceanx.expert_execution import ExpertCodeExecutionService
from oceanx.exports import PortableExportService
from oceanx.protocol.v2.models import ClientKind, EventEnvelope
from oceanx.research.services import ResearchServices
from oceanx.storage import OceanPaths
from oceanx.task_results import TaskResultStore
from oceanx.task_workspace import TaskWorkspaceProjector
from oceanx.workspace import WorkspaceService

FrameWriter = Callable[[str], Awaitable[None] | None]
PROTOCOL_PREFIX = "OHJSON:"
_CACHE_SWEEP_INTERVAL_SECONDS = 6 * 60 * 60
_LOGGER = logging.getLogger(__name__)


class JsonlStdioAdapter:
    """Adapt raw JSON-lines input to Protocol v2 without exposing logs on stdout."""

    def __init__(
        self,
        *,
        router: OceanRequestRouter,
        event_bus: EventBus,
        write_frame: FrameWriter,
        expected_client_kind: ClientKind = "desktop",
    ) -> None:
        self.router = router
        self.event_bus = event_bus
        self.write_frame = write_frame
        self.client = BackendClient(
            transport="stdio",
            expected_client_kind=expected_client_kind,
            sender=self._send_event,
        )
        self._started = False
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        if not self._started:
            await self.event_bus.register(self.client)
            self._started = True

    async def close(self) -> None:
        if self._started:
            await self.event_bus.unregister(self.client)
            self._started = False

    async def handle_line(self, raw: str) -> None:
        """Process one input JSON object; malformed input becomes a typed event."""

        await self.start()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        await self.router.handle_payload(self.client, payload)

    async def run(
        self,
        *,
        input_stream: BinaryIO | None = None,
    ) -> int:
        """Read UTF-8 JSONL until EOF or a successful system.shutdown request."""

        stream = input_stream or sys.stdin.buffer
        await self.start()
        try:
            while not self.router.shutdown_requested:
                raw = await asyncio.to_thread(stream.readline)
                if not raw:
                    break
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if line.strip():
                    await self.handle_line(line)
        finally:
            await self.close()
        return 0

    async def _send_event(self, event: EventEnvelope) -> None:
        frame = f"{PROTOCOL_PREFIX}{event.model_dump_json()}\n"
        async with self._write_lock:
            result = self.write_frame(frame)
            if isinstance(result, Awaitable):
                await result


class OceanBackendHost:
    """Own the Phase 1 store, shared event bus, router, and stdio adapter."""

    def __init__(
        self,
        state_directory: Path,
        *,
        write_frame: FrameWriter,
        expected_client_kind: ClientKind = "desktop",
    ) -> None:
        self.paths = OceanPaths.for_state_root(state_directory).ensure()
        self.store = RequestStore(self.paths.database)
        self.task_workspace_projector = TaskWorkspaceProjector(
            paths=self.paths,
            store=self.store,
        )
        self.task_results = TaskResultStore(
            task_workspaces=self.task_workspace_projector,
        )
        self.cache_cleaner = TaskCacheCleaner(
            store=self.store,
            task_workspaces=self.task_workspace_projector,
        )
        self._cache_maintenance_stop = asyncio.Event()
        self._cache_maintenance_task: asyncio.Task[None] | None = None
        self.artifact_service = ArtifactService(
            store=self.store,
            files=ArtifactFileStore(self.paths),
        )
        self.portable_export_service = PortableExportService(
            paths=self.paths,
            store=self.store,
            files=ArtifactFileStore(self.paths),
        )
        self.workspace_service = WorkspaceService(store=self.store)
        self.expert_code_execution = ExpertCodeExecutionService(
            store=self.store,
            paths=self.paths,
            task_workspaces=self.task_workspace_projector,
        )
        self.event_bus = EventBus()
        # Filesystem intents are recovered before active request records are marked interrupted.
        self.recovered_artifact_operations = self.artifact_service.recover_pending()
        self.research = ResearchServices(self)
        self.router = OceanRequestRouter(
            store=self.store,
            event_bus=self.event_bus,
            artifact_service=self.artifact_service,
            portable_export_service=self.portable_export_service,
            research_services=self.research,
            task_workspace_projector=self.task_workspace_projector,
            task_results=self.task_results,
        )
        self.stdio = JsonlStdioAdapter(
            router=self.router,
            event_bus=self.event_bus,
            write_frame=write_frame,
            expected_client_kind=expected_client_kind,
        )

    async def run_stdio(self, *, input_stream: BinaryIO | None = None) -> int:
        self.start_cache_maintenance()
        return await self.stdio.run(input_stream=input_stream)

    def start_cache_maintenance(self) -> None:
        """Sweep expired task caches at startup and periodically thereafter."""
        if self._cache_maintenance_task is None:
            self._cache_maintenance_task = asyncio.create_task(self._maintain_cache())

    async def _maintain_cache(self) -> None:
        while not self._cache_maintenance_stop.is_set():
            try:
                candidates = await asyncio.to_thread(self.cache_cleaner.candidates)
                for candidate in candidates:
                    # A task may have received a new request since the query.
                    current = self.store.get_research_task(candidate.task_id)
                    if current is None or current.active_request_id is not None:
                        continue
                    agents = self.task_workspace_projector.ensure_task_root(candidate.task_id) / "agents"
                    for key in tuple(self.expert_code_execution.kernels.kernels):
                        if Path(key).is_relative_to(agents):
                            await self.expert_code_execution.kernels.close(key)
                    await asyncio.to_thread(self.cache_cleaner.clean_task, candidate.task_id)
            except Exception:
                _LOGGER.exception("Task cache maintenance failed")
            try:
                await asyncio.wait_for(
                    self._cache_maintenance_stop.wait(), timeout=_CACHE_SWEEP_INTERVAL_SECONDS,
                )
            except TimeoutError:
                pass

    async def close(self) -> None:
        self._cache_maintenance_stop.set()
        if self._cache_maintenance_task is not None:
            await self._cache_maintenance_task
        await self.stdio.close()
        await self.router.shutdown_active_analysis()
        if not self.router.shutdown_requested:
            self.router.interrupt_active_requests()
        await self.expert_code_execution.kernels.close()
        self.store.close()


async def run_stdio_backend(
    state_directory: Path,
    *,
    expected_client_kind: ClientKind = "desktop",
) -> int:
    """Run the production stdio adapter using stdout only for protocol frames."""

    from oceanx.research.launcher import run_desktop_gateway
    return await run_desktop_gateway(state_directory, expected_client_kind=expected_client_kind)


__all__ = [
    "PROTOCOL_PREFIX",
    "JsonlStdioAdapter",
    "OceanBackendHost",
    "run_stdio_backend",
]

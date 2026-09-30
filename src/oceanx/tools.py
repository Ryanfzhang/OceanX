"""Minimal model-visible capabilities for OceanX's hierarchical team.

Scientific methods are written by Experts as ordinary code.  This module owns
only infrastructure boundaries: resource discovery, team assignment, bounded
Expert code execution, candidate delivery, and Coordinator-owned result
publication.
The tool surface stays limited to infrastructure needed by Coordinator and Experts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from oceanx.agent_tools import (
    BaseTool,
    ToolEffect,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
)
from oceanx.artifacts.models import ArtifactRef
from oceanx.artifacts.service import ArtifactService
from oceanx.backend.store import RequestStore, RequestStoreError
from oceanx.expert_execution import (
    ExpertCodeExecutionError,
    ExpertCodeExecutionService,
)
from oceanx.jina_reader import JinaReaderTool
from oceanx.protocol.v2.models import (
    EventEnvelope,
    TaskResultsChangedEvent,
    TaskResultsChangedPayload,
    new_event_id,
)
from oceanx.sandbox.runtime_probe import runtime_capabilities
from oceanx.web_search import WebSearchTool


class OceanToolInput(BaseModel):
    """Strict base model for every OceanX model-visible call."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class OceanToolServices:
    """Server-owned bindings; model input never supplies infrastructure state."""

    workspace_id: str
    provider_id: str
    store: RequestStore
    artifacts: ArtifactService | None = None
    task_id: str | None = None
    resource_access: Literal["routing", "inspection"] = "inspection"
    skill_capabilities: tuple[str, ...] = ()
    skill_role: str | None = None
    domain_event_emitter: Callable[[EventEnvelope], Awaitable[None]] | None = None
    coordinator_enabled: bool = False
    paper_selection_sink: (
        Callable[[dict[str, Any], ToolExecutionContext], Awaitable[dict[str, Any]]] | None
    ) = None
    expert_result_origin_request_id: str | None = None
    agent_run_id: str | None = None
    server_run_id: str | None = None
    expert_code_execution: ExpertCodeExecutionService | None = None
    # Stable LangGraph identity. Focused follow-ups reuse it; independent todos
    # receive different threads even when they use the same professional role.
    agent_thread_id: str | None = None
    exploration_belief_sampler: Callable[[str, str], Awaitable[dict]] | None = None
    native_vision: bool = False


@dataclass(frozen=True)
class ModelToolOperation:
    request_id: str
    turn_id: str
    tool_call_id: str
    operation_id: str


class _OceanTool(BaseTool):
    services: OceanToolServices

    def __init__(self, services: OceanToolServices) -> None:
        self.services = services

    @staticmethod
    def _json(value: Any, *, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            output=json.dumps(value, ensure_ascii=True, sort_keys=True),
            metadata={"display": "activity", **(metadata or {})},
        )

    @staticmethod
    def _error(message: str) -> ToolResult:
        return ToolResult(
            output=message,
            is_error=True,
            metadata={"display": "activity"},
        )

    @staticmethod
    def _model_operation(context: ToolExecutionContext) -> ModelToolOperation | None:
        values = (
            context.request_id,
            context.turn_id,
            context.tool_call_id,
            context.operation_id,
        )
        if not any(values):
            return None
        if not all(values):
            raise RequestStoreError("Model tool operation is missing durable correlation fields")
        return ModelToolOperation(
            request_id=context.request_id,
            turn_id=context.turn_id,
            tool_call_id=context.tool_call_id,
            operation_id=context.operation_id,
        )

    async def _run_mutation(
        self,
        context: ToolExecutionContext,
        action: Callable[[], Awaitable[ToolResult]],
    ) -> ToolResult:
        """Apply a model mutation once and replay its durable receipt."""

        operation: ModelToolOperation | None = None
        try:
            operation = self._model_operation(context)
            if operation is None:
                return await action()
            self.services.store.begin_tool_call(
                operation_id=operation.operation_id,
                request_id=operation.request_id,
                turn_id=operation.turn_id,
                tool_call_id=operation.tool_call_id,
                tool_name=self.name,
            )
            previous = self.services.store.operation_result(operation.operation_id)
            if previous is not None:
                return ToolResult(
                    output=str(previous["output"]),
                    is_error=bool(previous["is_error"]),
                    metadata={"display": "activity", "replayed": True},
                )
            result = await action()
            self.services.store.record_operation_result(
                operation_id=operation.operation_id,
                request_id=operation.request_id,
                turn_id=operation.turn_id,
                tool_call_id=operation.tool_call_id,
                result={"output": result.output, "is_error": result.is_error},
            )
            return result
        except (RequestStoreError, RuntimeError, ValueError) as exc:
            result = self._error(str(exc))
            # A rejected mutation is still a terminal tool result.  Persist the
            # error receipt so request replay and the UI never retain an orphan
            # ``in_progress`` operation.
            if operation is not None:
                try:
                    self.services.store.record_operation_result(
                        operation_id=operation.operation_id,
                        request_id=operation.request_id,
                        turn_id=operation.turn_id,
                        tool_call_id=operation.tool_call_id,
                        result={"output": result.output, "is_error": True},
                    )
                except RequestStoreError:
                    pass
            return result


class OceanResourcesInput(OceanToolInput):
    artifact_ref: ArtifactRef | None = None


class OceanResourcesTool(_OceanTool):
    name = "ocean_resources"
    description = (
        "List current workspace resources or inspect one immutable resource. The Coordinator sees "
        "source identity for the current task. Use this when continuing an interrupted task. "
        "results_directory is the task's agents directory; each Agent owns its report and outputs. "
        "Use read_file on the report paths supplied by native task receipts."
    )
    input_model = OceanResourcesInput

    def is_read_only(self, arguments: OceanResourcesInput) -> bool:
        del arguments
        return True

    async def execute(
        self, arguments: OceanResourcesInput, context: ToolExecutionContext
    ) -> ToolResult:
        del context
        service = self.services.expert_code_execution
        results_directory = str(service.task_results_root(self.services.task_id)) \
            if service is not None and self.services.task_id else None
        if arguments.artifact_ref is None:
            if self.services.agent_run_id:
                return self._json({"results_directory": results_directory})
            if self.services.resource_access == "routing":
                task_sources: list[dict[str, str]] = []
                if self.services.task_id is not None:
                    for record in self.services.store.list_task_artifacts(
                        task_id=self.services.task_id
                    ):
                        artifact = record.artifact
                        if "source" not in record.relations:
                            continue
                        if (
                            artifact.artifact_type == "project_context"
                            and artifact.schema_version == "ocean-local-source/v1"
                        ):
                            from oceanx.local_sources import LocalSourceError, resolve_local_source

                            try:
                                source = resolve_local_source(
                                    store=self.services.store,
                                    workspace_id=self.services.workspace_id,
                                    ref=artifact.ref,
                                )
                                task_sources.append(
                                    {
                                        "handle": f"source_{len(task_sources) + 1}",
                                        "kind": source.kind,
                                        "title": artifact.title,
                                        "format": source.format,
                                        "path": str(source.path),
                                        "access": "read_only",
                                    }
                                )
                            except LocalSourceError as exc:
                                task_sources.append(
                                    {
                                        "handle": f"source_{len(task_sources) + 1}",
                                        "kind": "unavailable",
                                        "title": artifact.title,
                                        "path_error": str(exc),
                                    }
                                )
                            continue
                        if artifact.artifact_type not in {"dataset", "paper"}:
                            continue
                        task_sources.append(
                            {
                                "handle": f"source_{len(task_sources) + 1}",
                                "kind": artifact.artifact_type,
                                "title": artifact.title,
                            }
                        )
                        if artifact.artifact_type == "dataset":
                            from oceanx.datasets import DatasetSourceError, resolve_dataset_source
                            try:
                                source = resolve_dataset_source(store=self.services.store,
                                    paths=self.services.artifacts.files.paths,
                                    workspace_id=self.services.workspace_id, ref=artifact.ref)
                                task_sources[-1].update(path=str(source.path), access="read_only")
                            except DatasetSourceError as exc:
                                task_sources[-1]["path_error"] = str(exc)
                return self._json(
                    {
                        "workspace_revision": self.services.store.workspace_snapshot(
                            self.services.workspace_id
                        ).revision,
                        "access_scope": "routing",
                        "task_sources": task_sources,
                        "results_directory": results_directory,
                        "runtime_capabilities": runtime_capabilities(),
                    }
                )
            summaries = self.services.store.list_artifact_summaries(self.services.workspace_id)
            return self._json(
                {
                    "workspace_revision": self.services.store.workspace_snapshot(
                        self.services.workspace_id
                    ).revision,
                    "access_scope": self.services.resource_access,
                    "resources": summaries,
                }
            )
        artifact = self.services.store.get_artifact(
            workspace_id=self.services.workspace_id,
            ref=arguments.artifact_ref,
        )
        if self.services.resource_access == "routing":
            allowed = {
                record.artifact.ref
                for record in (
                    self.services.store.list_task_artifacts(task_id=self.services.task_id)
                    if self.services.task_id is not None
                    else ()
                )
                if "source" in record.relations
            }
            if arguments.artifact_ref not in allowed:
                return self._error("Resource is not attached to the current task")
        projection = self.services.store.get_projection(
            workspace_id=self.services.workspace_id,
            ref=arguments.artifact_ref,
        )
        if artifact is None or projection is None:
            return self._error("Resource version was not found")
        if self.services.resource_access == "routing":
            return self._json(
                {
                    "access_scope": "routing",
                    "resource": {
                        "ref": artifact.ref.model_dump(mode="json"),
                        "type": artifact.artifact_type,
                        "title": artifact.title,
                    },
                    "inspection_required_for_content_claims": True,
                }
            )
        return self._json(
            {
                "access_scope": "inspection",
                "resource": {
                    "ref": artifact.ref.model_dump(mode="json"),
                    "type": artifact.artifact_type,
                    "title": artifact.title,
                    "summary": artifact.summary,
                    "projection": projection.model_dump(mode="json"),
                    "files": [item.model_dump(mode="json") for item in artifact.files],
                },
            }
        )






class OceanExpertRunCodeInput(OceanToolInput):
    purpose: str = Field(min_length=1, max_length=2_000)
    code: str = Field(min_length=1, max_length=200_000)


class OceanExpertRunCodeTool(_OceanTool):
    name = "ocean_expert_run_code"
    description = (
        "Run Python on the source paths in your assignment. The current directory and "
        "OCEAN_WORK_DIR are persistent task scratch for reusable intermediate files; "
        "scratch may be cleaned after the task becomes idle. Save deliverable files under "
        "os.environ['OCEAN_OUTPUT_DIR']; only explicitly published results persist. "
        "For a user-facing scientific figure, read result-api.md and save one self-describing .nc "
        "with oceanx.scientific_view.ScientificFigure. Ordinary .nc files remain data files. "
        "Do not upload local data or download replacement datasets without user authorization."
    )
    input_model = OceanExpertRunCodeInput

    def effect_for(self, arguments: OceanExpertRunCodeInput) -> ToolEffect:
        del arguments
        return ToolEffect.EXTERNAL_IO

    def concurrency_key(self, arguments: OceanExpertRunCodeInput) -> str:
        del arguments
        return f"expert-code:{self.services.agent_run_id or self.services.workspace_id}"

    async def execute(
        self, arguments: OceanExpertRunCodeInput, context: ToolExecutionContext
    ) -> ToolResult:
        del context
        service = self.services.expert_code_execution
        if (
            service is None
            or self.services.task_id is None
            or self.services.agent_thread_id is None
            or self.services.server_run_id is None
        ):
            return self._error("Expert code execution is unavailable in this session")
        try:
            result = await service.run_python(
                workspace_id=self.services.workspace_id,
                task_id=self.services.task_id,
                agent_thread_id=self.services.agent_thread_id,
                server_run_id=self.services.server_run_id,
                origin_request_id=self.services.expert_result_origin_request_id,
                purpose=arguments.purpose,
                code=arguments.code,
            )
            raw = result.as_payload()
            payload = {
                key: raw[key] for key in (
                    "execution_id", "state", "returncode", "stdout", "stderr", "logs",
                )
            }
            payload["saved_code_path"] = str(Path(result.work_root) / "analysis.py")
            payload["output_directory"] = str(Path(result.work_root) / "outputs")
            payload["output_files"] = [
                str(Path(name) if Path(name).is_absolute() else Path(result.work_root) / "outputs" / name)
                for name in result.changed_output_files
            ]
            if result.invalid_candidate_results:
                payload["file_errors"] = list(result.invalid_candidate_results)
            if result.discovered_results and self.services.domain_event_emitter is not None:
                result_ids = tuple(
                    str(item.get("data_output") or item.get("title") or "result")
                    for item in result.discovered_results
                )
                await self.services.domain_event_emitter(TaskResultsChangedEvent(
                    protocol_version=2,
                    event_id=new_event_id(),
                    session_id=None,
                    workspace_id=self.services.workspace_id,
                    task_id=self.services.task_id,
                    request_id=self.services.expert_result_origin_request_id,
                    sequence=0,
                    timestamp=datetime.now(UTC),
                    type="task.results.changed",
                    payload=TaskResultsChangedPayload(result_ids=result_ids),
                ))
            for stream_name in ("stdout", "stderr"):
                stream = str(payload[stream_name])
                if len(stream) > 2_400:
                    payload[stream_name] = (
                        stream[:1_120] + "\n... [full text at logs." + stream_name + "] ...\n"
                        + stream[-1_120:]
                    )
            return self._json(payload)
        except (ExpertCodeExecutionError, RequestStoreError, RuntimeError, ValueError) as exc:
            return self._error(str(exc))


class OceanPaperCandidateInput(OceanToolInput):
    """One stable item in a Search Expert-curated shortlist."""

    paper_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
        description="Stable short identifier used to return the researcher's selection.",
    )
    title: str = Field(min_length=1, max_length=1_000)
    topic: str = Field(
        min_length=1,
        max_length=500,
        description="One concise phrase stating why this paper is relevant to the research task.",
    )
    evidence_scope: Literal["metadata_only", "abstract", "public_excerpt"] = Field(
        description=(
            "The deepest source material actually inspected during discovery. This prevents a "
            "candidate assessment from being presented as a full-text conclusion."
        ),
    )
    evidence_summary: str = Field(
        min_length=1,
        max_length=2_000,
        description=(
            "Concrete methods, variables, reported findings, or boundaries this paper can "
            "contribute, based only on the declared evidence_scope; not a generic abstract recap."
        ),
    )
    validation_target: str = Field(
        min_length=1,
        max_length=1_500,
        description=(
            "The specific observation, diagnostic, threshold, mechanism, or comparison in the "
            "current research task that this paper could support, challenge, or help reproduce."
        ),
    )
    citation: str | None = Field(
        default=None,
        max_length=2_000,
        description="Compact authors, venue, and year metadata when known.",
    )
    url: str | None = Field(
        default=None,
        max_length=4_096,
        description="Canonical landing-page or full-text URL when known.",
    )


class OceanRequestPaperSelectionInput(OceanToolInput):
    question: str = Field(
        default="Which papers should OceanX use for the next stage?",
        min_length=1,
        max_length=4_000,
        description="A short decision prompt shown above the paper table.",
    )
    papers: tuple[OceanPaperCandidateInput, ...] = Field(
        min_length=1,
        max_length=30,
        description=(
            "Candidate papers for user selection, with source identity and inspected evidence."
        ),
    )

    @model_validator(mode="after")
    def validate_papers(self) -> OceanRequestPaperSelectionInput:
        ids = [paper.paper_id for paper in self.papers]
        if len(ids) != len(set(ids)):
            raise ValueError("paper_id values must be unique")
        return self


class OceanRequestPaperSelectionTool(_OceanTool):
    name = "ocean_request_paper_selection"
    description = (
        "Show an interactive paper selection table and wait for the user's selected paper_ids "
        "before downloading full texts."
    )
    input_model = OceanRequestPaperSelectionInput

    def effect_for(self, arguments: OceanRequestPaperSelectionInput) -> ToolEffect:
        del arguments
        return ToolEffect.EXTERNAL_IO

    def concurrency_key(self, arguments: OceanRequestPaperSelectionInput) -> str:
        del arguments
        return f"paper-selection:{self.services.workspace_id}"

    async def execute(
        self,
        arguments: OceanRequestPaperSelectionInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        if self.services.paper_selection_sink is None:
            return self._error("Interactive paper selection is unavailable")

        async def action() -> ToolResult:
            value = await self.services.paper_selection_sink(
                arguments.model_dump(mode="json"), context
            )
            return self._json(value, metadata={"paper_selection": value})

        return await self._run_mutation(context, action)


def create_ocean_tool_registry(services: OceanToolServices) -> ToolRegistry:
    return create_ocean_lead_tool_registry(services)


def _create_web_search_tool(services: OceanToolServices) -> WebSearchTool:
    del services
    return WebSearchTool()


def create_ocean_lead_tool_registry(services: OceanToolServices) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        OceanResourcesTool(services),
        _create_web_search_tool(services),
    ):
        registry.register(tool)
    return registry


def create_ocean_expert_tool_registry(services: OceanToolServices) -> ToolRegistry:
    registry = ToolRegistry()
    if "web.search" in services.skill_capabilities:
        registry.register(_create_web_search_tool(services))
    if "jina.reader" in services.skill_capabilities:
        registry.register(JinaReaderTool())
    if services.paper_selection_sink is not None:
        registry.register(OceanRequestPaperSelectionTool(services))
    if services.expert_code_execution is not None:
        registry.register(OceanResourcesTool(services))
        registry.register(OceanExpertRunCodeTool(services))
    return registry


def create_ocean_discussion_tool_registry(services: OceanToolServices) -> ToolRegistry:
    del services
    # The Discussion Partner only discusses frozen evidence with the
    # Coordinator. It has no domain mutations, execution or learning tools.
    return ToolRegistry()


__all__ = [
    "OceanToolServices",
    "create_ocean_discussion_tool_registry",
    "create_ocean_expert_tool_registry",
    "create_ocean_lead_tool_registry",
    "create_ocean_tool_registry",
]

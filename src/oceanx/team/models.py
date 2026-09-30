"""Small user-facing result contracts; Agent Server owns child lifecycle."""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from oceanx.task_results import TaskResultRef

NonEmptyText = Annotated[str, Field(min_length=1)]


class ChildAuthority(str, Enum):
    EXPERT = "expert"
    DISCUSSION = "discussion"


class WorkFailureCode(str, Enum):
    BACKEND_INTERRUPTED = "backend_interrupted"
    UNKNOWN = "unknown"


class CoordinatorDecision(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    GOAL_MISMATCH = "goal_mismatch"
    BLOCKED = "blocked"


class CoordinatorAnswerBasis(str, Enum):
    GENERAL_KNOWLEDGE = "general_knowledge"
    WORKSPACE_CATALOG = "workspace_catalog"
    EXPERT_EVIDENCE = "expert_evidence"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceRef(FrozenModel):
    kind: Literal["artifact", "code_execution", "dataset", "paper", "external"]
    ref: Annotated[str, Field(min_length=1, max_length=1_024)]
    checksum: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    locator: Annotated[str, Field(min_length=1, max_length=2_048)] | None = None


class CoordinatorResult(FrozenModel):
    answer_markdown: NonEmptyText
    # Retained for persisted-result compatibility. Only the Coordinator may
    # supply a scientific decision; transport code leaves it unset.
    decision: CoordinatorDecision | None = None
    research_outcome: Literal["answered", "insufficient_evidence", "partial", "blocked"] | None = None
    # Legacy receipt metadata. Transport must not infer scientific provenance.
    answer_basis: CoordinatorAnswerBasis | None = None
    evidence_refs: tuple[EvidenceRef, ...] = Field(default=(), max_length=256)
    result_refs: tuple[TaskResultRef, ...] = Field(default=(), max_length=64)
    limitations: tuple[NonEmptyText, ...] = Field(default=(), max_length=64)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def unique_evidence(self):
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("Coordinator result evidence refs must be unique")
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("Coordinator result task result refs must be unique")
        return self


__all__ = [
    "ChildAuthority", "CoordinatorAnswerBasis", "CoordinatorDecision",
    "CoordinatorResult", "EvidenceRef", "WorkFailureCode",
]

"""The single model-facing scientific decision-tree editor (Coordinator only)."""
from __future__ import annotations

import asyncio
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


# One tree change under a policy without hypothesis nodes. (A class docstring would reach the
# model-visible schema, so these classes use comments.)
class QuestionTreeChange(BaseModel):
    action: Literal[
        "add", "revise", "set_status", "close", "reopen", "link", "prune", "decline",
    ] = Field(description="One semantic tree change.")
    target: str = Field(description="ROOT, an existing parent, or the node being changed.")
    question: str | None = None
    why_it_matters: str | None = None
    relation: Literal["independent", "dependency", "alternative", "extension"] | None = None
    from_proposal: str | None = Field(
        default=None, description="add only: the Expert proposal this question pursues, e.g. "
        "B1.2#1. Set it whenever the question comes from a proposal.")
    origin_type: str | None = Field(
        default=None, description="add only: why a question that is not an Expert proposal exists, "
        "e.g. contradiction or evidence_gap.")
    origin_refs: list[str] | None = None
    dependencies: list[str] | None = None
    branch_key: str | None = None
    expert_role: str | None = None
    status: Literal["candidate", "selected", "completed", "failed"] | None = None
    reason: str | None = None
    other: str | None = None
    link_type: Literal["supports", "conflicts", "depends_on", "related"] | None = None


# Adds hypothesis nodes, their verdicts and evidence links, for policies that enable them.
class ResearchTreeChange(QuestionTreeChange):
    action: Literal[
        "add", "revise", "set_status", "close", "reopen", "link", "prune", "decline",
        "set_verdict",
    ] = Field(description="One semantic tree change.")
    link_type: Literal[
        "supports", "refutes", "inconclusive", "conflicts", "depends_on", "related"
    ] | None = None
    kind: Literal["question", "hypothesis"] | None = None
    verdict: Literal["supported", "refuted", "unresolved"] | None = None


class QuestionTreeUpdate(BaseModel):
    changes: list[QuestionTreeChange] = Field(
        default_factory=list,
        description="One atomic decision batch. Empty reads the current view.",
    )
    view: Literal["decision", "full"] = Field(
        default="decision",
        description="Use full only once when writing the final Research Tree section.",
    )


class ResearchTreeUpdate(QuestionTreeUpdate):
    changes: list[ResearchTreeChange] = Field(
        default_factory=list,
        description="One atomic decision batch. Empty reads the current view.",
    )


_DESCRIPTION = (
    "Read or atomically update the scientific decision tree. Candidate directions are nodes, not "
    "a separate pool. A ROOT add creates the active research-question anchor and is never delegated. "
    "A child add defaults to candidate; use set_status selected only after choosing it for execution. "
    "The frontier lists selected questions that are ready to run. Native task completion only "
    "attaches the report Summary; its numbered Further analysis items appear as proposals such as "
    "B1.2#1, which become nodes only if you add them with from_proposal (you may reword); "
    "unadopted proposals need no action. After reading each returned Summary, explicitly "
    "set_status completed only when the question is scientifically answered; otherwise add/select "
    "follow-up work or close it with a scientific reason; decline closes a candidate you will not "
    "explore, with the reason (reopen revives it). link records only a useful "
    "supports/conflicts/depends_on relationship; depends_on also makes the question wait for "
    "the other node's result. "
    "The response is text: one line per node; after an edit only changed nodes, the frontier and "
    "live candidates are returned, and the complete view whenever the tree changed elsewhere. "
    "Before the final research report, read once with changes=[] and view=full to render the "
    "complete Research Tree. Never store methods, transcripts, report text or agent lifecycle here. "
    "Use DeepAgents' native task tool separately for delegation."
)
_HYPOTHESES = (
    " Hypotheses: add kind=hypothesis under the question it would explain; it is a claim, never "
    "selected or delegated. Link a question to a hypothesis with supports, refutes or inconclusive, "
    "and change its verdict with set_verdict and a reason."
)


def research_tree_tool(tree):
    """Return one tree tool; it never starts, monitors, resumes or cancels agents."""
    last_seen: dict[str, int | None] = {"revision": None}

    def update(changes=None, view: str = "decision") -> str:
        try:
            payload = [change.model_dump(exclude_none=True) for change in (changes or [])]
            text, last_seen["revision"] = tree.view_text(
                payload, full=view == "full", last_seen_revision=last_seen["revision"])
            return text
        except (ValueError, OSError) as exc:
            return f"Tree unchanged: {exc}"

    async def aupdate(changes=None, view: str = "decision") -> str:
        return await asyncio.to_thread(update, changes, view)

    hypotheses = bool(getattr(tree.policy, "hypotheses", False))
    return StructuredTool.from_function(
        name="update_research_tree", func=update, coroutine=aupdate, infer_schema=False,
        # Offer hypothesis options only when the policy accepts them.
        args_schema=ResearchTreeUpdate if hypotheses else QuestionTreeUpdate,
        description=_DESCRIPTION + (_HYPOTHESES if hypotheses else ""),
    )


__all__ = ["QuestionTreeChange", "QuestionTreeUpdate", "ResearchTreeChange", "ResearchTreeUpdate",
           "research_tree_tool"]

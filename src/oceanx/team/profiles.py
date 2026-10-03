"""Trusted professional profiles for OceanX's hierarchical science team.

Three Experts answer assigned questions using their own methods.
One Discussion Partner challenges ideas without
acting as an acceptance gate. Code execution is infrastructure, never a peer Agent role.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from oceanx.team.models import ChildAuthority

ProfileCategory = Literal[
    "science",
    "methods",
    "evidence",
    "discussion",
]


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """One server-owned specialist identity available to the Coordinator."""

    profile_id: str
    display_name: str
    authority: ChildAuthority
    category: ProfileCategory
    summary: str
    instructions: str


EXPERT_BASE_INSTRUCTIONS = """\
Answer only the assigned subquestion. Choose the supporting inspection, analysis, statistics and figures
needed to answer it; profiles and Skills are expertise, not method checklists or boundaries. Separate
direct evidence from interpretation, including material uncertainty or contradiction. A justified
evidence-limited answer is complete. For a specified non-research output, produce that output without
turning it into a research project. Save reusable results with coordinates, units and variable meanings.
"""


AGENT_PROFILES: tuple[AgentProfile, ...] = (
    AgentProfile(
        profile_id="ocean_process_expert",
        display_name="Ocean Expert",
        authority=ChildAuthority.EXPERT,
        category="science",
        summary=(
            "Owns physically discriminating ocean diagnostics, competing mechanisms, and physical "
            "interpretation at the relevant scales."
        ),
        instructions=(
            "Use ocean physics to distinguish explanations supported by the supplied evidence. "
            "Separate a mechanism-compatible pattern from a demonstrated mechanism."
        ),
    ),
    AgentProfile(
        profile_id="statistical_inference_expert",
        display_name="Statistic Expert",
        authority=ChildAuthority.EXPERT,
        category="methods",
        summary=(
            "Owns estimands, comparisons, dependence, uncertainty, robustness, and the boundary between "
            "description and inference."
        ),
        instructions=(
            "Use statistical evidence to answer the question, explaining effect size, uncertainty "
            "and assumptions relevant to the inference. Statistical association is not causal attribution."
        ),
    ),
    AgentProfile(
        profile_id="literature_reproduction_expert",
        display_name="Search Expert",
        authority=ChildAuthority.EXPERT,
        category="evidence",
        summary=(
            "Finds and reviews literature, supports reproduction, and handles explicitly user-requested "
            "dataset acquisition."
        ),
        instructions=(
            "Handle user-requested dataset acquisition or download scripts and answer literature or "
            "reproduction questions with traceable sources. Distinguish read evidence from unread full text "
            "and paper findings from interpretation. For framing or on-demand consultation, identify "
            "established and disputed explanations, discriminating evidence and relevant data gaps. Inform "
            "Coordinator choices without choosing the tree or workflow. A consultation reads sources and "
            "reports; it does not analyse the task's data. When sources conflict, or only a numerical check "
            "can decide, say so and stop: the Coordinator assigns the check to a data Expert. Run code only "
            "when the assignment explicitly asks to reproduce a result or download data. When paper "
            "selection is required, stop before full-text acquisition and use the paper-selection tool."
        ),
    ),
    AgentProfile(
        profile_id="scientific_discussion_partner",
        display_name="Scientific Discussion Partner",
        authority=ChildAuthority.DISCUSSION,
        category="discussion",
        summary=(
            "Challenges ideas, develops alternatives, and discusses scientific interpretations with "
            "the Coordinator without acting as an acceptance gate."
        ),
        instructions=(
            "Discuss the Coordinator's question, hypotheses, candidate explanation, and saved Expert reports "
            "without inheriting hidden Expert context. Challenge assumptions, propose alternative mechanisms or "
            "methods, identify discriminating evidence, and preserve unresolved disagreement. You do not approve, "
            "reject, or mechanically validate another Agent's response. The Coordinator alone decides whether "
            "the user's goal is satisfied."
        ),
    ),
)


EXPERT_PROFILE_IDS = frozenset(
    profile.profile_id
    for profile in AGENT_PROFILES
    if profile.authority is ChildAuthority.EXPERT
)

_PROFILES_BY_ID = {profile.profile_id: profile for profile in AGENT_PROFILES}

def get_agent_profile(profile_id: str) -> AgentProfile:
    """Return one trusted current profile."""

    try:
        return _PROFILES_BY_ID[profile_id]
    except KeyError as exc:
        available = ", ".join(_PROFILES_BY_ID)
        raise ValueError(
            f"unknown OceanX agent profile {profile_id!r}; available profiles: {available}"
        ) from exc


def bind_agent_profile(payload: dict[str, object]) -> AgentProfile | None:
    """Bind trusted identity without silently expanding work through Manuals."""

    raw_profile_id = payload.get("profile_id")
    if not isinstance(raw_profile_id, str) or not raw_profile_id:
        return None
    profile = get_agent_profile(raw_profile_id)
    submitted_authority = payload.get("authority")
    if submitted_authority is not None and ChildAuthority(submitted_authority) is not profile.authority:
        raise ValueError(
            f"agent profile {profile.profile_id!r} requires {profile.authority.value} authority"
        )
    payload["profile_id"] = profile.profile_id
    payload["authority"] = profile.authority.value
    payload["semantic_role"] = profile.display_name
    return profile


def profile_system_prompt(profile: AgentProfile) -> str:
    """Return the complete responsibility prompt for one trusted profile."""

    role = (
        EXPERT_BASE_INSTRUCTIONS + "\n\n# Domain ownership\n" + profile.instructions
        if profile.profile_id in EXPERT_PROFILE_IDS
        else profile.instructions
    )
    return (
        f"Professional profile: {profile.display_name} ({profile.profile_id}).\n"
        f"{role.strip()}"
    )


def agent_profile_prompt_section() -> str:
    """Render the authoritative, compact selection catalog for Coordinator."""

    lines = [
        "# OceanX Hierarchical Professional Team",
        "Profiles are capabilities, not checklists. Choose the expertise needed for the question.",
        "Available profiles:",
    ]
    for profile in AGENT_PROFILES:
        lines.append(
            f"- {profile.profile_id} | {profile.display_name} | {profile.authority.value} | "
            f"{profile.summary}"
        )
    return "\n".join(lines)


__all__ = [
    "AGENT_PROFILES",
    "EXPERT_BASE_INSTRUCTIONS",
    "EXPERT_PROFILE_IDS",
    "AgentProfile",
    "ProfileCategory",
    "agent_profile_prompt_section",
    "bind_agent_profile",
    "get_agent_profile",
    "profile_system_prompt",
]

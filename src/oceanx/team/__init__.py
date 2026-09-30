"""OceanX participant profiles and final result contracts."""

from oceanx.team.models import (
    ChildAuthority,
    CoordinatorAnswerBasis,
    CoordinatorDecision,
    CoordinatorResult,
    EvidenceRef,
    WorkFailureCode,
)
from oceanx.team.profiles import (
    AGENT_PROFILES,
    AgentProfile,
    agent_profile_prompt_section,
    get_agent_profile,
)

__all__ = [
    "AGENT_PROFILES", "AgentProfile", "ChildAuthority",
    "CoordinatorAnswerBasis", "CoordinatorDecision", "CoordinatorResult",
    "EvidenceRef", "WorkFailureCode", "agent_profile_prompt_section",
    "get_agent_profile",
]

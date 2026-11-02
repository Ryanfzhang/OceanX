"""The research time budget a benchmark run sets from its own time limit, so that the run ends with a
final report instead of being cut off: after one share of it the Coordinator starts no new Expert
assignment (graphs.ResearchBudgetMiddleware), after a later share no code runs (expert_execution.py).
Without a budget neither happens."""
from __future__ import annotations

import os

RESEARCH_BUDGET_ENV = "OCEANX_RESEARCH_BUDGET_MINUTES"
RESEARCH_BUDGET_STOP = 0.75  # share of the budget after which no new Expert assignment starts
# Share after which no code runs. Code has no time limit of its own since 2026-11-02, so an Expert that
# started a long computation near the end held the run until it was cut off without a report; the rest of
# the budget is for the Experts' reports and the final report.
CODE_BUDGET_STOP = 0.85


def research_budget_minutes() -> float | None:
    """An optional limit on research time; the benchmark sets it from its own time limit."""
    try:
        minutes = float(os.environ.get(RESEARCH_BUDGET_ENV) or 0)
    except ValueError:
        return None
    return minutes if minutes > 0 else None


__all__ = ["CODE_BUDGET_STOP", "RESEARCH_BUDGET_ENV", "RESEARCH_BUDGET_STOP", "research_budget_minutes"]

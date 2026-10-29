"""One agent works on each request first; the research team takes over the open research problems.

The single agent has the Experts' tools and the data and search Experts' skills, answers in chat and
can give independent parts of a request to helpers of its own. When a request turns out to be an
open research problem it calls hand_to_research_team, and the same server run goes on with the
Coordinator and its Experts in research mode (graphs.coordinator). On a simple request the choice
costs nothing extra: the agent makes it on the call that starts the work.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

SINGLE_AGENT = "single_agent"
HELPER = "helper"
TEAM = "team"  # the Coordinator and its Experts, as the writer of a message
AGENT_TAG = "oceanx_agent"  # which of SINGLE_AGENT and TEAM wrote a message of the task's conversation
HANDOFF_TOOL = "hand_to_research_team"
HELPER_TOOL = "assign_helper"

SINGLE_AGENT_CALL_LIMIT = 100
HELPER_CALL_LIMIT = 20
MAX_HELPERS = 3  # helpers of one request that work at once
BUDGET_NOTE_CALLS = 5  # the last calls of a budget end their tool result with the calls left

WORKFLOW_MODES = ("auto", "standard", "research")


def workflow_mode(config) -> str:
    """auto: the single agent first and the team for an open research problem (the desktop);
    standard: the single agent alone; research: the team at once (the default of headless runs)."""
    mode = config["configurable"].get("request_options", {}).get("workflow_mode", "research")
    return mode if mode in WORKFLOW_MODES else "research"


def team_config(config):
    """The run's configuration with research mode on, for the team that takes a request over."""
    c = config["configurable"]
    return {**config, "configurable": {**c, "request_options": {
        **c.get("request_options", {}), "workflow_mode": "research"}}}


HANDOFF_POLICY = """\
## Routing — decide before starting work

Classify by the FINAL DELIVERABLE, not by the steps involved.

EXECUTE yourself when the deliverable is a known, checkable artifact
and the method is given or standard:
- reproducing a figure/table/number from a paper (the paper supplies
  the method and a reference result)
- downloading data, running computations, fitting specified models, plotting
- debugging or explaining discrepancies that arise while doing the above
Difficulty, length, or number of steps alone is NOT a reason to hand off.

HAND OFF to the research team when the user explicitly asks for
something whose answer is not known in advance, e.g.:
- proposing or testing new hypotheses, mechanisms, or methods
- open questions ("why does…", "what drives…", "find new patterns in…")
- going beyond a paper to draw new conclusions
- comparing competing approaches with no given criterion

Mixed requests: if open research is an explicit goal, hand off the
whole task (the team will do any reproduction as a first step).

Default: if the user did not explicitly ask for new findings,
explanations, or exploration, EXECUTE.

Before acting, output: ROUTE: EXECUTE|RESEARCH — <one-line reason>
"""

HELPER_POLICY = f"""\
# Helpers
{HELPER_TOOL} gives one part of the request to a helper that has your tools, skills and data but not this
conversation, and returns the helper's reply. Use helpers for parts that are independent of each other and each
need several steps, such as the same analysis for three variables or periods: call {HELPER_TOOL} several times in
one turn, and up to {MAX_HELPERS} helpers work at once. Do short or dependent work yourself. A helper starts from
nothing, so make each part complete: what to do, the data and files to use (full paths) and what to return.
"""

BOUNDED_WORK_POLICY = """\
# Bounded work
The requested output (a figure, number, table, route or file) is the finish line. First cut the data to the
variables, region, depth and period the request needs; never load a whole field or water column when a slice
answers it. Compute it with one defensible method, publish it, answer and stop. Do not add sensitivity tests,
extra figures or statistics, investigations of individual cells or values, or re-checks of saved outputs unless a
result is clearly wrong or the request asks for them. Do not open {saved_view} of a figure you just saved. State a
remaining limitation in one sentence instead of investigating it. Each code run stops after {seconds} s; if one
times out, read less data (a smaller region or period, or a coarser stride) instead of repeating the same read.
Reproducing or testing a paper's analysis is not bounded this way: it is finished only when every quantity
and budget term of the paper that the data allow is computed as the paper defines it and compared with the paper's
values, every figure is redrawn to look like the paper's, and a term counts as missing only after deriving it from
the stored variables has failed; /skills/paper-reproduction/SKILL.md describes how.
"""

LAST_CALL = ("# Last model call\nThis is the last model call of your budget, and no tools are available on it. "
             "Answer the researcher now from what you have, and say plainly what is unfinished.")
LAST_CALL_HANDOFF = (
    "# Last model call\nThis is the last model call of your budget, and only "
    f"{HANDOFF_TOOL} is available on it. If you have answered the request, give the final answer now. "
    f"Otherwise call {HANDOFF_TOOL}, saying what you did, which saved files can be reused and what is "
    "unfinished.")
HELPER_LAST_CALL = ("# Last model call\nThis is the last model call of your budget, and no tools are "
                    "available on it. Reply now with what you found and saved, and say plainly what is "
                    "unfinished.")
PLAIN_TEXT_RETRY = "No tool can be called on this call, so reply in plain text now."


def call_budget_sentence(limit: int) -> str:
    return (f"Call budget: you have {limit} model calls for this request, and one call can run several "
            f"tools. The last {BUDGET_NOTE_CALLS} tool results show how many remain.\n")


def _tool_name(tool) -> str | None:
    return tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)


def _markup_only(request, response) -> bool:
    """The tool-free last call answered with tool-call markup instead of text."""
    from oceanx.research.graphs import _prose
    messages = getattr(response, "result", None)
    reply = messages[-1] if messages else response
    return not request.tools and isinstance(reply, AIMessage) and not _prose(reply)


class QuickCallBudgetMiddleware(ModelCallLimitMiddleware):
    """A fixed number of model calls: the last ones say how many remain, and the very last one may only
    answer (or, for the single agent in auto mode, hand the request over)."""

    def __init__(self, limit: int, *, last_call: str, last_tools: frozenset[str] = frozenset()) -> None:
        super().__init__(run_limit=limit, exit_behavior="end")
        self.last_call, self.last_tools = last_call, last_tools

    def _prepare(self, request):
        left = self.run_limit - int(request.state.get("run_model_call_count", 0))  # with this call
        if left > 1:
            return _with_calls_left(request, left) if left <= BUDGET_NOTE_CALLS else request
        base = request.system_message.text if request.system_message else ""
        return request.override(
            tools=[tool for tool in request.tools if _tool_name(tool) in self.last_tools],
            system_message=SystemMessage(content=f"{base}\n\n{self.last_call}".strip()))

    def wrap_model_call(self, request, handler):
        request = self._prepare(request)
        response = handler(request)
        if _markup_only(request, response):
            response = handler(request.override(
                messages=[*request.messages, HumanMessage(content=PLAIN_TEXT_RETRY)]))
        return response

    async def awrap_model_call(self, request, handler):
        request = self._prepare(request)
        response = await handler(request)
        if _markup_only(request, response):
            response = await handler(request.override(
                messages=[*request.messages, HumanMessage(content=PLAIN_TEXT_RETRY)]))
        return response


def _with_calls_left(request, left: int):
    """End the last tool result of this request, never the saved conversation, with the calls left."""
    messages = list(request.messages)
    if not messages or not isinstance(messages[-1], ToolMessage):
        return request
    note = f"[Budget: {left} model calls left, this one included; the last has no tools.]"
    last = messages[-1]
    content = ([*last.content, {"type": "text", "text": note}] if isinstance(last.content, list)
               else f"{last.content}\n\n{note}")
    messages[-1] = last.model_copy(update={"content": content})
    return request.override(messages=messages)


class HandoffInput(BaseModel):
    reason: str = Field(description=(
        "One sentence shown to the researcher, in the researcher's language, saying that the research "
        "team takes this request over and why."))
    progress: str = Field(default="", description=(
        "For the research team: what you already did, which saved files or results it can reuse (full "
        "paths) and what is unfinished. Empty when you have not started."))


HANDOFF_DESCRIPTION = (
    "Hand this request to OceanX's research team (a Coordinator and Experts), which takes over at once and "
    "answers the researcher. Use this tool for RESEARCH under 'Routing — decide before starting work'.")
HANDOFF_RECEIPT = "The research team takes this request over now."


def handed_over(messages) -> bool:
    """The tool results of the latest model turn include the handoff."""
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            return False
        if message.name == HANDOFF_TOOL:
            return True
    return False


class HandoffMiddleware(AgentMiddleware):
    """hand_to_research_team, and the end of the single agent's run right after it."""

    def __init__(self) -> None:
        super().__init__()

        def hand_over(reason: str, progress: str = "") -> str:
            del reason, progress  # read from the call by graphs.coordinator
            return HANDOFF_RECEIPT

        async def ahand_over(reason: str, progress: str = "") -> str:
            return hand_over(reason, progress)

        self.tools = [StructuredTool.from_function(
            func=hand_over, coroutine=ahand_over, name=HANDOFF_TOOL,
            description=HANDOFF_DESCRIPTION, args_schema=HandoffInput)]

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        return {"jump_to": "end"} if handed_over(state.get("messages") or ()) else None

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)


def handoff_request(messages) -> dict[str, str] | None:
    """The reason and progress of the latest hand_to_research_team call among ``messages``."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call.get("name") == HANDOFF_TOOL:
                    args = call.get("args") or {}
                    return {"reason": str(args.get("reason") or "").strip(),
                            "progress": str(args.get("progress") or "").strip()}
    return None


def handoff_note(handoff: dict[str, str], folder) -> str:
    """What the Coordinator is told about a request the single agent handed over."""
    progress = handoff.get("progress") or ""
    return ("\n# Handed over by the single agent\n"
            "OceanX's single agent, which works alone, received this request first and handed it to the "
            f"research team. Its reason: {handoff.get('reason') or 'none given'}\n"
            + (f"What it did: {progress}\n" if progress else "It had not started on it.\n")
            + f"Its files are in {folder}, read-only for the team; reuse what helps.\n")


def budget_handoff(limit: int) -> dict[str, str]:
    return {"reason": f"The single agent used all {limit} model calls without finishing the request.",
            "progress": "See its last messages and its files."}


class HelperInput(BaseModel):
    task: str = Field(description=(
        "The part for the helper, complete in itself: what to do, the data and files to use (full paths) "
        "and what to return. The helper does not see this conversation."))


HELPER_DESCRIPTION = (
    "Give one independent part of the request to a helper with your tools, skills and data, and get its "
    f"reply. Several calls in one turn run in parallel, up to {MAX_HELPERS} at once.")


class HelperMiddleware(AgentMiddleware):
    """assign_helper for the single agent; ``run_helper`` builds and runs one helper (graphs.py)."""

    def __init__(self, run_helper: Callable[[str], Awaitable[str]], *, limit: int = MAX_HELPERS) -> None:
        super().__init__()
        slots = asyncio.Semaphore(limit)

        async def assign_helper(task: str) -> str:
            async with slots:
                try:
                    return await run_helper(task)
                except Exception as exc:  # noqa: BLE001 - the single agent does the part itself instead
                    return f"The helper failed ({type(exc).__name__}: {exc}). Do this part yourself."

        self.tools = [StructuredTool.from_function(
            coroutine=assign_helper, name=HELPER_TOOL, description=HELPER_DESCRIPTION,
            args_schema=HelperInput)]


def tagged(messages, agent: str) -> list:
    """``messages`` marked as written by ``agent``."""
    return [message.model_copy(update={"additional_kwargs": {
        **(message.additional_kwargs or {}), AGENT_TAG: agent}}) for message in messages]


def seen_by(messages, agent: str) -> list:
    """The task's conversation as ``agent`` sees it: the researcher's messages, its own work, and only
    the answers of the other agent, whose tool calls and results are left out."""
    return [message for message in messages
            if isinstance(message, HumanMessage)
            or (message.additional_kwargs or {}).get(AGENT_TAG, agent) == agent
            or (isinstance(message, AIMessage) and not message.tool_calls and message.text.strip())]


def last_answer(messages) -> str:
    return next((message.text.strip() for message in reversed(messages)
                 if isinstance(message, AIMessage) and not message.tool_calls and message.text.strip()), "")


__all__ = [
    "AGENT_TAG", "BOUNDED_WORK_POLICY", "HANDOFF_POLICY", "HANDOFF_TOOL", "HELPER", "HELPER_CALL_LIMIT",
    "HELPER_LAST_CALL", "HELPER_POLICY", "HELPER_TOOL", "LAST_CALL", "LAST_CALL_HANDOFF", "MAX_HELPERS",
    "SINGLE_AGENT", "SINGLE_AGENT_CALL_LIMIT", "TEAM", "HandoffMiddleware", "HelperMiddleware",
    "QuickCallBudgetMiddleware", "budget_handoff", "call_budget_sentence", "handed_over", "handoff_note",
    "handoff_request", "last_answer", "seen_by", "tagged", "team_config", "workflow_mode",
]

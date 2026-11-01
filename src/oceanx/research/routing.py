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
from pathlib import Path

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

SINGLE_AGENT_CALL_LIMIT = 200
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


HANDOFF_POLICY = f"""\
## Routing — decide before starting work

OceanX handles four kinds of tasks. Handle these yourself:
- basic Q&A
- making plots or maps
- reproducing a paper or applying its method, including to different data or periods

Hand this one to the research team:
- research questions: the user wants conclusions about what happened
  and why (causes, mechanisms, or whether a model captures them) that
  no given paper or method already settles.

Decide from the request text alone, before reading files or data.
The number of steps, datasets or figures does not decide the route,
and specifying data, methods or figures does not turn a research
question into one of the other three.

For research questions, your first and only tool call must be {HANDOFF_TOOL}, then stop.

If, while doing a task you handled yourself, the work reveals an open
research question, call {HANDOFF_TOOL} with your progress and
reusable files, then stop. Do not inspect data to decide the initial route.
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
Reproducing, testing or applying a paper's analysis is not bounded work: it is finished only when every analysis
of the paper that the data allow is done, each quantity and budget term computed as the paper defines it and
checked, and each figure redrawn to look like the paper's, with every panel, curve and term the data allow. A term
counts as missing only after deriving it from the stored variables has failed, and nothing the data allow is
withheld or left as an offer for later; /skills/paper-reproduction/SKILL.md describes how.
For any other request, the requested output (a figure, number, table, route or file) is the finish line. Compute it
with one defensible method, verify the requested output, publish it, answer and stop. Open {saved_view} of a figure
you saved and correct errors before delivery.
Do not add unrequested sensitivity tests, extra figures or statistics, or investigations beyond the requested
objective. Checking and correcting the requested output is part of the task. State a
remaining limitation in one sentence instead of investigating it.
For every request, read only the variables, region, depth and period the work needs, sliced in the read itself;
never load a whole field or water column when a slice answers it. {long_runs} Reading every n-th time step
changes the result: say so, and where the request or the paper's method uses every step, compare the two on a
common part, such as one year, before relying on it.
"""
# What the single agent, its helpers and the Experts are told about long runs (expert_execution.py).
LONG_RUNS = ("Code runs until it ends, with no time limit. For long work, have a script print its progress, "
             "such as each year done, and save each part's result to a file instead of repeating the same read.")

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
    "answers the researcher. Use this tool for research questions under 'Routing — decide before starting work'.")
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


PAPER_SKILL = "/skills/paper-reproduction/SKILL.md"
# Named only in the text note of an attached paper, the skill was not opened in a run of
# 2026-11-01; opened, read_file shows the first 100 of its about 200 lines, and a summary later
# replaces what was read. So the agent decides on the call that starts the work, and the skill it
# opens stays in its instructions for the rest of the request (PaperSkillMiddleware).
PAPER_RULE = (
    "\n# Attached paper\nThe researcher attached a paper; the extracted text of each PDF, which "
    "names its page and figure images, is at {texts}. Decide from the request, and the "
    "conversation it continues, whether it asks to reproduce, test or apply the paper's analysis, "
    f"with the paper's data or other data. If it does, read {PAPER_SKILL} before any other tool "
    "call: from your next call on, that skill, with the sections it points to, is part of these "
    "instructions in full, also after a summary replaces earlier messages.\n")


def paper_rule(texts: list[str]) -> str:
    """PAPER_RULE for a task with attached papers, given the paths of their extracted texts."""
    return PAPER_RULE.format(texts=", ".join(texts)) if texts else ""


def opened_in_request(messages, path: str) -> bool:
    """Whether the agent read ``path`` with read_file since the researcher's latest message."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return False
        if isinstance(message, AIMessage) and any(
                call.get("name") == "read_file"
                and str((call.get("args") or {}).get("file_path", "")).endswith(path)
                for call in message.tool_calls):
            return True
    return False


class PaperSkillMiddleware(AgentMiddleware):
    """From the call after the single agent opened the paper skill, the skill as its library holds
    it, with the sections it points to, ends its instructions on every call of that request. It is
    looked for in the saved messages, which a summary leaves in place."""

    def __init__(self, skill: Path) -> None:
        super().__init__()
        text = skill.read_text(encoding="utf-8")
        body = text.split("\n---\n", 1)[-1].strip()  # without its header
        self.block = (f"# Paper skill\nYou opened {PAPER_SKILL} for this request; here it is in "
                      "full, with the sections it points to, for the rest of the request.\n\n"
                      + body)

    def _prepare(self, request):
        if not opened_in_request(request.state.get("messages") or (), PAPER_SKILL):
            return request
        content = request.system_message.content if request.system_message else ""
        content = ([*content, {"type": "text", "text": self.block}] if isinstance(content, list)
                   else f"{content}\n\n{self.block}".strip())
        return request.override(system_message=SystemMessage(content=content))

    def wrap_model_call(self, request, handler):
        return handler(self._prepare(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._prepare(request))


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
    "HELPER_LAST_CALL", "HELPER_POLICY", "HELPER_TOOL", "LAST_CALL", "LAST_CALL_HANDOFF", "LONG_RUNS",
    "MAX_HELPERS", "PAPER_RULE", "PAPER_SKILL", "SINGLE_AGENT", "SINGLE_AGENT_CALL_LIMIT", "TEAM",
    "HandoffMiddleware", "HelperMiddleware", "PaperSkillMiddleware", "QuickCallBudgetMiddleware",
    "budget_handoff", "call_budget_sentence", "handed_over", "handoff_note", "handoff_request",
    "last_answer", "opened_in_request", "paper_rule", "seen_by", "tagged", "team_config",
    "workflow_mode",
]

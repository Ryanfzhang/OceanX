"""OceanX graphs built from native DeepAgents subagents.

The Coordinator is one Agent Server run. Its ``task`` calls invoke compiled
Expert graphs directly and return compact file-backed receipts to the same run;
OceanX does not mirror child lifecycle, enqueue callbacks, or resume a second
Coordinator run. Each Expert works as a background job of that run, so the
Coordinator is called again when the next one returns rather than when the whole
batch has (background_experts.py).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import NotRequired

from deepagents.graph import DeepAgentState
from deepagents.middleware.filesystem import FilesystemState
from deepagents.middleware.skills import SkillsState
from deepagents.middleware.summarization import SummarizationState
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from oceanx.agent_tools import ToolRegistry
from oceanx.deep_runtime import build_deep_agent_graph
from oceanx.expert_execution import STANDARD_MODE_CODE_SECONDS
from oceanx.figure_reference import DRAFT_RULE, figure_call_skeleton, figure_reading_rule
from oceanx.figure_delivery import static_figures
from oceanx.model_config import load_model_profile
from oceanx.research.background_experts import (
    AWAIT_TOOL, BackgroundDelegationMiddleware, RunningExperts, appended)
from oceanx.research.metering import INSIDE_EXPERT
from oceanx.research.services import (
    AgentRun,
    file_revision,
    format_expert_receipt,
    host,
    report_summary,
)
from oceanx.runtime import build_ocean_discussion_runtime, build_ocean_expert_runtime, build_ocean_runtime
from oceanx.skills import JINA_READER_CAPABILITY, LITERATURE_CAPABILITY, WEB_SEARCH_CAPABILITY
from oceanx.team.profiles import AGENT_PROFILES, get_agent_profile, profile_system_prompt
from oceanx.research.tool_calls import ToolCallRepairMiddleware
from oceanx.tools import OceanToolServices


_LOGGER = logging.getLogger(__name__)


def _expert_call_limit() -> int:
    """Model calls one Expert run may use: 60 on the desktop, lowered by the benchmark's setting."""
    try:
        return max(10, int(os.environ.get("OCEANX_EXPERT_CALL_LIMIT", "60")))
    except ValueError:
        return 60


def _expert_call_phases(limit: int) -> tuple[int, int, int]:
    """Where the report checkpoint, the wind-down and the final call fall in a budget of ``limit`` calls.

    Half, four fifths and the last call, which is 30, 48 and 59 of 60; a lower limit keeps the shape.
    """
    return limit // 2, limit * 4 // 5, limit - 1


EXPERT_MODEL_CALL_LIMIT = _expert_call_limit()
EXPERT_REPORT_CHECKPOINT_START, EXPERT_WIND_DOWN_START, EXPERT_FINAL_CALL = _expert_call_phases(
    EXPERT_MODEL_CALL_LIMIT)


def _parallel_expert_limit() -> int:
    try:
        return max(1, int(os.environ.get("OCEANX_MAX_PARALLEL_EXPERTS", "2")))
    except ValueError:
        return 2


def _parallel_search_expert_limit() -> int:
    try:
        return max(1, int(os.environ.get("OCEANX_MAX_PARALLEL_SEARCH_EXPERTS", "1")))
    except ValueError:
        return 1


# Data Expert runs that may work at once across the whole app; Search has its own small pool below.
# Data runs load arrays and execute code on this machine, so their pool bounds local CPU and memory.
MAX_PARALLEL_EXPERTS = _parallel_expert_limit()
MAX_PARALLEL_SEARCH_EXPERTS = _parallel_search_expert_limit()
PARALLEL_EXPERTS_CEILING = 8  # the largest value a request may ask for


class _Slots:
    """Experts that may work at once; the limit can change while some hold a slot or wait for one."""

    def __init__(self, limit: int) -> None:
        self.limit, self.active = limit, 0
        self._freed = asyncio.Event()  # set, and replaced, whenever a waiting Expert may look again

    def locked(self) -> bool:
        return self.active >= self.limit

    def resize(self, limit: int) -> None:
        if limit != self.limit:
            self.limit = limit
            self._wake()

    def _wake(self) -> None:
        freed, self._freed = self._freed, asyncio.Event()
        freed.set()

    async def __aenter__(self) -> None:
        while self.active >= self.limit:
            await self._freed.wait()
        self.active += 1

    async def __aexit__(self, *_exc) -> None:
        self.active -= 1
        self._wake()


_EXPERT_SLOTS: tuple[asyncio.AbstractEventLoop, _Slots] | None = None
_SEARCH_EXPERT_SLOTS: tuple[asyncio.AbstractEventLoop, _Slots] | None = None


def _expert_slots(limit: int | None = None) -> _Slots:
    """The app-wide slot pool; the Agent Server runs every graph on one event loop.

    ``limit`` is the desktop's setting, which each request carries; a Coordinator run applies it
    when it starts, so the pool follows the newest request.
    """
    global _EXPERT_SLOTS
    loop = asyncio.get_running_loop()
    if _EXPERT_SLOTS is None or _EXPERT_SLOTS[0] is not loop:
        _EXPERT_SLOTS = (loop, _Slots(MAX_PARALLEL_EXPERTS))
    if limit is not None:
        _EXPERT_SLOTS[1].resize(limit)
    return _EXPERT_SLOTS[1]


def _search_expert_slots() -> _Slots:
    """A small independent pool so source consultation cannot block data analysis."""
    global _SEARCH_EXPERT_SLOTS
    loop = asyncio.get_running_loop()
    if _SEARCH_EXPERT_SLOTS is None or _SEARCH_EXPERT_SLOTS[0] is not loop:
        _SEARCH_EXPERT_SLOTS = (loop, _Slots(MAX_PARALLEL_SEARCH_EXPERTS))
    return _SEARCH_EXPERT_SLOTS[1]


def _requested_parallel_experts(config) -> int | None:
    """The data-Expert limit this request asks for (the desktop's setting), or None for the default."""
    value = config["configurable"].get("request_options", {}).get("max_parallel_experts")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return min(value, PARALLEL_EXPERTS_CEILING)


_WIND_DOWN_TOOLS = frozenset({"ls", "glob", "grep", "read_file", "write_file", "edit_file"})
COORDINATOR_FILESYSTEM_TOOLS = (
    "ls",
    "glob",
    "grep",
    "read_file",
    "write_file",
    "edit_file",
)

COORDINATOR_VISUAL_DELIVERY_POLICY = """\
# Requested visual delivery
Do not execute analysis code or create figures, images or result files yourself. Delegate a requested map,
plot, figure or other reusable scientific view to the responsible Expert as part of its first assignment.
A visual is delivered only when that Expert's native receipt lists a suitable server-verified key under
Published results. A filename, ordinary NetCDF file or PNG path is not a desktop result.

If the Expert answered the scientific question but omitted a visual that the user explicitly asked for, you may
make one and only one follow-up task call to the same Expert role, for the same node_id when the question is a
research-tree node, so it works in the same folder. A visual that you added yourself in an Expert assignment
does not qualify. Ask it only to publish the requested view from its saved evidence and include the previous
report; do not request new analysis, visual polishing or another Expert. Never make a second visual-delivery
follow-up and never create a replacement yourself. If that one follow-up still returns no suitable Published
results key, finish honestly that the interactive visual was not delivered. When a suitable key exists, cite it
next to the supported conclusion in the final answer.
A .preview.png is only the fallback owned by a registered interactive result, never a standalone result.
"""

# The same duties for a static-delivery run, where a figure is an image file (see figure_delivery.py).
STATIC_COORDINATOR_VISUAL_DELIVERY_POLICY = """\
# Requested visual delivery
Do not execute analysis code or create figures, images or result files yourself. Delegate a requested map,
plot, figure or other reusable scientific view to the responsible Expert as part of its first assignment.
A figure is delivered only when that Expert's native receipt lists its image file under Saved figures.

If the Expert answered the scientific question but omitted a visual that the user explicitly asked for, you may
make one and only one follow-up task call to the same Expert role, for the same node_id when the question is a
research-tree node, so it works in the same folder. A visual that you added yourself in an Expert assignment
does not qualify. Ask it only to save the requested figure from its saved evidence and include the previous
report; do not request new analysis, visual polishing or another Expert. Never make a second visual-delivery
follow-up and never create a replacement yourself. If that one follow-up still lists no suitable figure under
Saved figures, finish honestly that the figure was not delivered. When a suitable figure is listed, cite its
path next to the supported conclusion in the final answer.
"""


def _visual_delivery_policy() -> str:
    return STATIC_COORDINATOR_VISUAL_DELIVERY_POLICY if static_figures() else COORDINATOR_VISUAL_DELIVERY_POLICY


def _tool_name(tool) -> str | None:
    if isinstance(tool, dict):
        return tool.get("name")
    return getattr(tool, "name", None)


def _wind_down_request(request):
    """Use the native model-call count to reserve the end of one Expert run."""
    call_count = int(request.state.get("run_model_call_count", 0))
    if call_count < EXPERT_WIND_DOWN_START:
        return request

    base_prompt = request.system_message.text if request.system_message else ""
    if call_count >= EXPERT_FINAL_CALL:
        tools = []
        instruction = (
            "# Final delivery call\n"
            "No tools are available on this final model call, and none can be called. Do not begin or "
            "claim new work. If report.md is complete and current, return a concise, honest final answer "
            "from it. Otherwise write the complete report as this reply, in plain Markdown beginning with "
            "## Summary (Result, Evidence and limitations, Further analysis), from the evidence already "
            "saved; the backend saves it as report.md. State any incompleteness explicitly."
        )
    else:
        tools = [tool for tool in request.tools if _tool_name(tool) in _WIND_DOWN_TOOLS]
        instruction = (
            "# Reserved report wind-down\n"
            "The research phase is over. Do not start new searches, calculations, delegation, or "
            "scientific branches. Use only the available filesystem tools to read existing evidence "
            "and finish the backend-assigned report.md. Preserve supported result bindings. Keep "
            "partial or inconclusive findings honest. Ensure the short ## Summary states Result, "
            "Evidence and limitations, and Further analysis before finishing normally."
        )
    return request.override(
        tools=tools,
        system_message=SystemMessage(content=f"{base_prompt}\n\n{instruction}".strip()),
    )


def _call_budget_sentence() -> str:
    """The Expert's whole budget, once, in its instructions (the same for the whole run)."""
    return (
        f"Call budget: you have {EXPERT_MODEL_CALL_LIMIT} model calls for this assignment, and one call "
        f"can run several tools. Analysis tools work through call {EXPERT_WIND_DOWN_START}; calls "
        f"{EXPERT_WIND_DOWN_START + 1} to {EXPERT_FINAL_CALL} may only finish the report, and call "
        f"{EXPERT_MODEL_CALL_LIMIT} has no tools. The end of each tool result shows which call you are on "
        "and how many remain.\n"
    )


def _budget_note(call_count: int) -> str:
    """Where the next model call falls in the budget; ``call_count`` calls have been made."""
    call, limit = call_count + 1, EXPERT_MODEL_CALL_LIMIT
    if call_count >= EXPERT_FINAL_CALL:
        return f"[Budget: model call {call} of {limit}, the last; no tools.]"
    if call_count >= EXPERT_WIND_DOWN_START:
        return (f"[Budget: model call {call} of {limit}; analysis is over, {limit - call_count} left only to "
                "finish the report; the last has no tools.]")
    return (f"[Budget: model call {call} of {limit}; {EXPERT_WIND_DOWN_START - call_count} left for analysis, "
            f"then {limit - EXPERT_WIND_DOWN_START} only to finish the report.]")


def _with_budget_note(request):
    """End the last tool result of this request with the calls that remain.

    Only this request carries the note, never the saved conversation, so the cached prompt prefix does
    not change; the first call has no tool result, and the instructions state the budget.
    """
    messages = list(request.messages)
    if not messages or not isinstance(messages[-1], ToolMessage):
        return request
    note = _budget_note(int(request.state.get("run_model_call_count", 0)))
    last = messages[-1]
    content = ([*last.content, {"type": "text", "text": note}] if isinstance(last.content, list)
               else f"{last.content}\n\n{note}")
    messages[-1] = last.model_copy(update={"content": content})
    return request.override(messages=messages)


WIND_DOWN_REFUSAL = (
    "Not run: the analysis phase of this assignment is over and only file tools work now. "
    "Write or update report.md from the evidence you already have, then finish."
)
REPORT_CHECKPOINT_REFUSAL = (
    "Not run: first save the defensible partial answer you already have to the backend-assigned "
    "report.md. After that checkpoint, analysis tools become available again."
)


def _refused_tool_call(request):
    """Refuse a non-file tool that a wind-down call (49-59) still requested.

    The count already includes the call that asked for the tool, so tools from
    call 48, the last analysis call, still run.
    """
    state = request.state if isinstance(request.state, dict) else {}
    call = request.tool_call
    if int(state.get("run_model_call_count", 0)) <= EXPERT_WIND_DOWN_START or (
            call.get("name") in _WIND_DOWN_TOOLS):
        return None
    return ToolMessage(content=WIND_DOWN_REFUSAL, tool_call_id=call["id"],
                       name=call.get("name"), status="error")


# Tool-call markup a model can print as text when no tool is bound (DeepSeek's starts with "<｜").
_TOOL_MARKUP = ("<｜", "<|tool", "<tool_call", "<function_call")
PLAIN_TEXT_RETRY = ("No tool can be called on this final call, so your reply must be plain Markdown: "
                    "write the report text now, beginning with ## Summary.")


def _prose(message) -> str:
    """A reply's text up to any tool-call markup; empty for a tool call or markup alone."""
    if not isinstance(message, AIMessage) or message.tool_calls:
        return ""
    text = message.text
    cut = min((index for index in map(text.find, _TOOL_MARKUP) if index >= 0), default=len(text))
    return text[:cut].strip()


def _undelivered(request, response) -> bool:
    """The tool-free final call answered with markup instead of a report or answer."""
    if int(request.state.get("run_model_call_count", 0)) < EXPERT_FINAL_CALL:
        return False
    messages = getattr(response, "result", None)
    reply = messages[-1] if messages else response
    return isinstance(reply, AIMessage) and not _prose(reply)


def _plain_text_request(request):
    return request.override(messages=[*request.messages, HumanMessage(content=PLAIN_TEXT_RETRY)])


RESEARCH_BUDGET_ENV = "OCEANX_RESEARCH_BUDGET_MINUTES"
RESEARCH_BUDGET_STOP = 0.75  # share of the budget after which no new Expert assignment starts
BUDGET_REFUSAL = ("Not started: most of the research time budget is used. Start no new Expert "
                  "assignment; write the final report from the results you have.")


def research_budget_minutes() -> float | None:
    """An optional limit on research time; the benchmark sets it from its own time limit."""
    try:
        minutes = float(os.environ.get(RESEARCH_BUDGET_ENV) or 0)
    except ValueError:
        return None
    return minutes if minutes > 0 else None


class ResearchBudgetMiddleware(AgentMiddleware):
    """Each Expert receipt tells the Coordinator how long the research has run and how many
    assignments it made. With a budget, no new assignment starts after RESEARCH_BUDGET_STOP of
    it, so the run ends with a synthesis instead of a timeout. The status rides on the receipt,
    so the cached prompt prefix never changes."""

    def __init__(self, budget_minutes: float | None = None, clock=time.monotonic) -> None:
        super().__init__()
        self.budget, self.clock = budget_minutes, clock
        self.started, self.assignments = clock(), 0

    def _closed(self) -> bool:
        minutes = (self.clock() - self.started) / 60
        return self.budget is not None and minutes >= RESEARCH_BUDGET_STOP * self.budget

    def _status(self) -> str:
        status = f"Research status: {(self.clock() - self.started) / 60:.0f} min elapsed"
        if self.budget is not None:
            status += f" of a {self.budget:.0f}-minute budget"
        status += f"; {self.assignments} Expert assignments so far."
        return status + (" Start no new assignment; write the final report." if self._closed() else "")

    def _start(self, request):
        """The refusal when the budget is used, otherwise None after counting the assignment."""
        call = request.tool_call
        if call.get("name") != "task":
            return None
        if self._closed():
            return ToolMessage(content=BUDGET_REFUSAL, tool_call_id=call["id"], name="task",
                               status="error")
        self.assignments += 1
        return None

    def _with_status(self, request, result):
        if request.tool_call.get("name") not in {"task", AWAIT_TOOL}:
            return result
        return appended(result, self._status())

    def wrap_tool_call(self, request, handler):
        return self._start(request) or self._with_status(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._start(request) or self._with_status(request, await handler(request))


class ExpertCallBudgetMiddleware(ModelCallLimitMiddleware):
    """Own the native call count and report wind-down in one middleware instance.

    Keeping both behaviours on the same middleware prevents the wind-down from
    depending on private state owned by a separate middleware instance.  Calls
    49--59 of the default 60 (the last fifth, before the final call) retain only
    report/file tools, and any other tool they still request is refused without
    running; the last call is a tool-free delivery call.
    """

    def __init__(self, *, report_path: Path | None = None) -> None:
        super().__init__(run_limit=EXPERT_MODEL_CALL_LIMIT, exit_behavior="end")
        self.report_path = report_path

    def _report_missing(self) -> bool:
        if self.report_path is None:
            return False
        try:
            return not (self.report_path.is_file() and self.report_path.stat().st_size > 0)
        except OSError:
            return True

    def _checkpoint_pending(self, request) -> bool:
        """Whether this model call must first save the report: from the 31st call until call 48."""
        call_count = int(request.state.get("run_model_call_count", 0))
        return (EXPERT_REPORT_CHECKPOINT_START <= call_count < EXPERT_WIND_DOWN_START
                and self._report_missing())

    def _refused_checkpoint_tool_call(self, request):
        """Refuse a non-file tool that a checkpoint call (31-48) still requested.

        As in the wind-down, the count already includes the call that asked for the tool, so a tool
        from call 30, made before the checkpoint began and with every tool offered, still runs.
        """
        state = request.state if isinstance(request.state, dict) else {}
        call = request.tool_call
        count = int(state.get("run_model_call_count", 0))
        if not (EXPERT_REPORT_CHECKPOINT_START < count <= EXPERT_WIND_DOWN_START
                and self._report_missing()) or call.get("name") in _WIND_DOWN_TOOLS:
            return None
        return ToolMessage(content=REPORT_CHECKPOINT_REFUSAL, tool_call_id=call["id"],
                           name=call.get("name"), status="error")

    def _prepare_request(self, request):
        request = _wind_down_request(request)
        if not self._checkpoint_pending(request):
            return _with_budget_note(request)
        base_prompt = request.system_message.text if request.system_message else ""
        instruction = (
            "# Required report checkpoint\n"
            "Pause further analysis. Use the available filesystem tools now to write the first "
            "defensible partial answer to the backend-assigned report.md. Keep limitations honest. "
            "This is an updatable checkpoint, not the end of the assignment; after it is saved, "
            "the analysis tools return on the next call."
        )
        return _with_budget_note(request.override(
            tools=[tool for tool in request.tools if _tool_name(tool) in _WIND_DOWN_TOOLS],
            system_message=SystemMessage(content=f"{base_prompt}\n\n{instruction}".strip()),
        ))

    def wrap_model_call(self, request, handler):
        request = self._prepare_request(request)
        response = handler(request)
        return handler(_plain_text_request(request)) if _undelivered(request, response) else response

    async def awrap_model_call(self, request, handler):
        request = self._prepare_request(request)
        response = await handler(request)
        return await handler(_plain_text_request(request)) if _undelivered(request, response) else response

    def wrap_tool_call(self, request, handler):
        return (self._refused_checkpoint_tool_call(request) or _refused_tool_call(request)
                or handler(request))

    async def awrap_tool_call(self, request, handler):
        return (self._refused_checkpoint_tool_call(request) or _refused_tool_call(request)
                or await handler(request))


class ResearchState(FilesystemState, SummarizationState, SkillsState, DeepAgentState):
    research_complete: NotRequired[bool]
    final_answer: NotRequired[str]


class ExpertState(FilesystemState, SummarizationState, SkillsState, DeepAgentState):
    question: NotRequired[str]
    previous_report_revision: NotRequired[tuple[int, int, int] | None]


def research_tree_path(task_id: str) -> Path:
    return (host().task_workspace_projector.ensure_task_root(task_id) /
            "agents" / "coordinator" / "research_tree.json")


def _project():
    from oceanx.research.review import ProjectResearch
    return ProjectResearch(host().paths)


def research_tree(task_id: str):
    """The task tree bound to the research policy (v2-nested unless an experiment selects one).

    The recorded version also names the lessons and tools the task runs with, so experiments
    can attribute outcomes to the policy and the learned library together.
    """
    from oceanx.research.tree import ResearchTree
    project = _project()
    policy, library = project.policy(), project.version()
    return ResearchTree(research_tree_path(task_id), policy=policy,
                        policy_version=f"{policy.version}+{library}" if library else None)


def _library_record(tree, final_report: str) -> dict:
    """Which lessons and tools this task ran with, and which lessons it named. The project's
    periodic update reads this to see what is used (lessons.py, toolbook.py)."""
    from oceanx.research.lessons import cited_lessons
    project = _project()
    shown = project.lessons.shown_ids()
    texts = [final_report, json.dumps(tree.document(), ensure_ascii=False)]
    for attempt in tree.attempts():
        report = Path(str(attempt.get("report_path") or ""))
        try:
            if report.is_file():
                texts.append(report.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return {"lessons_shown": shown, "lessons_cited": cited_lessons(shown, texts),
            "tools_mounted": [tool["name"] for tool in project.tools.mounted()]}


def research_mode(config) -> bool:
    """The desktop's research toggle; headless runs default to research."""
    return config["configurable"].get("request_options", {}).get("workflow_mode", "research") == "research"


def _standard_expert_policy(saved_view: str) -> str:
    return f"""\
# Bounded request (research mode is off)
The requested output (a figure, number, table, route or file) is the finish line. First cut the data to the
variables, region, depth and period the request needs; never load a whole field or water column when a slice
answers it. Compute it with one defensible method, publish it, write the report and stop. Do not add
sensitivity tests, extra figures or statistics, investigations of individual cells or values, or re-checks of
saved outputs unless a result is clearly wrong or the researcher asked. Do not open {saved_view} of a
figure you just saved. State a remaining limitation in one sentence instead of investigating it. Each code run stops after {STANDARD_MODE_CODE_SECONDS} s; if one times
out, read less data (a smaller region or period, or a coarser stride) instead of repeating the same read.
"""


STANDARD_EXPERT_POLICY = _standard_expert_policy("the .preview.png")
# A static run has no preview file beside a figure: the saved image is the figure.
STATIC_STANDARD_EXPERT_POLICY = _standard_expert_policy("the image")

STANDARD_COORDINATOR_POLICY = """\
# Research mode is off
First judge whether the request is an open research problem: it asks why something happens, which mechanism or
explanation holds, or otherwise needs open-ended investigation across competing explanations. If it clearly is,
do not delegate: reply in one or two sentences that it looks like an open research question, and ask whether to
switch on Research mode or give a brief bounded answer now; then stop. A bounded request, even a complex
computation such as a route through a current field, proceeds without asking; when unsure, proceed.
Give the Expert the requested output as the finish line.
"""


def coordinator_report_path(config) -> Path:
    c = config["configurable"]
    return (host().task_workspace_projector.ensure_task_root(c["task_id"]) /
            "agents" / "coordinator" / "report.md")


# Experts that analyse the supplied data; literature and discussion work starts without Python.
DATA_EXPERT_ROLES = frozenset({"ocean_process_expert", "statistical_inference_expert"})


async def _describe_task_data(c) -> None:
    """Inspect the task's data sources once, before the first data Expert starts.

    The description (variables, dimensions, units, time ranges) is cached for the task and
    shown in every later agent's context, so Experts do not each rediscover the data. The
    Coordinator never waits for it; it sees the description once one exists.
    """
    service = getattr(host(), "expert_code_execution", None)
    if service is None:
        return
    try:
        sources = service.resolve_task_sources(workspace_id=c["workspace_id"], task_id=c["task_id"])
        if sources:
            await service.get_task_dataset_context(
                workspace_id=c["workspace_id"], task_id=c["task_id"], sources=sources)
    except Exception:  # without it, agents inspect the files themselves
        _LOGGER.warning("Could not describe the task's data sources", exc_info=True)


def services(config, role: str, run: AgentRun | None = None) -> OceanToolServices:
    h = host()
    c = config["configurable"]
    model_profile = load_model_profile("coordinator" if role == "coordinator" else "expert")
    from oceanx.model_config import profile_supports_vision
    return OceanToolServices(
        workspace_id=c["workspace_id"], task_id=c["task_id"], store=h.store,
        artifacts=h.artifact_service, provider_id=model_profile.provider,
        resource_access="routing" if role == "coordinator" else "inspection",
        skill_role=role,
        skill_capabilities=(LITERATURE_CAPABILITY, WEB_SEARCH_CAPABILITY, JINA_READER_CAPABILITY)
        if role == "literature_reproduction_expert" else (LITERATURE_CAPABILITY,),
        expert_code_execution=h.expert_code_execution,
        domain_event_emitter=h.event_bus.emit_workspace,
        agent_run_id=run.agent_run_id if run else None,
        server_run_id=run.server_run_id if run else None,
        expert_result_origin_request_id=c["request_id"],
        agent_thread_id=run.thread_id if run else c["thread_id"],
        coordinator_enabled=role == "coordinator",
        native_vision=profile_supports_vision(model_profile),
        code_time_limit_seconds=None if research_mode(config) else STANDARD_MODE_CODE_SECONDS,
        paper_selection_sink=(lambda payload, context: h.router._request_paper_selection(
            workspace_id=c["workspace_id"], task_id=c["task_id"], payload=payload, context=context))
        if role == "literature_reproduction_expert" else None,
    )


def _earlier_keys(run: AgentRun) -> list[tuple[str, list[str]]]:
    """The nodes above this one and the nodes it waits for, nearest first, each with the keys of the
    Agents that worked on it, latest attempt first."""
    if not run.node_id:
        return []
    tree = research_tree(run.task_id)
    parts = run.node_id.split(".")
    sources = [".".join(parts[:depth]) for depth in range(len(parts) - 1, 0, -1)]
    found = tree.document()["nodes"].get(run.node_id) or {}
    sources += [node for node in found.get("dependencies", ()) if node not in sources]
    groups = []
    for node in sources:
        keys = list(dict.fromkeys(attempt["agent_key"] for attempt in reversed(tree.attempts(node))
                                  if attempt.get("agent_key") not in (None, "", "coordinator", run.thread_id)))
        if keys:
            groups.append((node, keys))
    return groups


def _earlier_work(run: AgentRun) -> list[str]:
    """Folders of the nodes above this one and of the nodes it waits for, nearest first.

    Each node works in its own folder; these are mounted read-only for it.
    """
    root = host().task_workspace_projector.expert_session_root
    return [f"{node}: {', '.join(str(root(run.task_id, key)) for key in keys)}"
            for node, keys in _earlier_keys(run)]


SAVED_DATA_FILES = 12  # data files described per folder
SAVED_DATA_FILE_CHARS = 200  # characters in one file's line
SAVED_DATA_TOTAL_CHARS = 4_000  # characters of saved-data listing in one Expert's prompt
SAVED_DATA_TIMEOUT_SECONDS = 60
_NOTE_CHARS = 32  # room kept for "(+N more files not listed)" and "(+N more folders not listed)"


def _fit(head: str, items: list[str], noun: str, hidden: int = 0, sep: str = "; ") -> str:
    """The head and as many items as fit in one file's line, then how many were left out."""
    kept: list[str] = []
    for item in items:
        left = len(items) - len(kept) - 1 + hidden
        tail = f"{sep}+{left} more {noun}" if left else ""
        if kept and len(head + sep.join([*kept, item]) + tail) > SAVED_DATA_FILE_CHARS:
            break
        kept.append(item)
    left = len(items) - len(kept) + hidden
    line = head + sep.join(kept) + (f"{sep}+{left} more {noun}" if left else "")
    return line if len(line) <= SAVED_DATA_FILE_CHARS else line[: SAVED_DATA_FILE_CHARS - 1] + "…"


def _saved_file_line(entry: dict) -> str:
    """One saved data file as a line of at most SAVED_DATA_FILE_CHARS characters."""
    name = str(entry.get("path", "?"))
    if entry.get("inspection") != "ready":
        error = str(entry.get("error") or "not described")
        return _fit(f"{name}: could not be read ({error})", [], "")
    kind = entry.get("kind")
    if kind == "array":
        sizes = entry.get("dimensions") or {}
        variables = []
        for variable in entry.get("variables") or ():
            dims = ", ".join(f"{dim}={sizes[dim]}" if dim in sizes else str(dim)
                             for dim in variable.get("dims") or ())
            text = f"{variable.get('name')}({dims})"
            if variable.get("units"):
                text += f" [{variable['units']}]"
            if variable.get("long_name"):
                text += f' "{variable["long_name"]}"'
            variables.append(text)
        title = f' ("{entry["title"]}")' if entry.get("title") else ""
        hidden = max(0, int(entry.get("variable_count") or 0) - len(variables))
        return _fit(f"{name}{title}: ", variables, "variables", hidden)
    if kind == "table":
        columns = [str(column) for column in entry.get("columns") or ()]
        hidden = max(0, int(entry.get("column_count") or 0) - len(columns))
        rows = f"{int(entry['rows']):,} rows" if "rows" in entry else "rows not counted"
        return _fit(f"{name}: {rows}; columns ", columns, "columns", hidden, ", ")
    if kind == "arrays":
        arrays = [f"{item.get('name')} {item.get('dtype')} {tuple(item.get('shape') or ())}"
                  + (" (needs allow_pickle)" if item.get("needs_allow_pickle") else "")
                  for item in entry.get("arrays") or ()]
        hidden = max(0, int(entry.get("array_count") or 0) - len(arrays))
        return _fit(f"{name}: ", arrays, "arrays", hidden)
    return f"{name}: not described"


def _saved_data_block(listing: list[tuple[Path, dict]]) -> str:
    """What earlier folders saved, as prompt text of at most SAVED_DATA_TOTAL_CHARS characters.

    Each folder lists at most SAVED_DATA_FILES files, one line each, and says how many files it
    leaves out; folders that no longer fit are counted. Empty when nothing was saved.
    """
    title = "Saved data in those folders (outputs first, then the newest scratch files):\n"
    lines: list[str] = []
    used = len(title)
    not_shown = 0
    for folder, index in listing:
        files = index.get("files") or []
        if not files:
            continue
        file_lines = ["  " + _saved_file_line(entry) for entry in files[:SAVED_DATA_FILES]]
        omitted = int(index.get("omitted") or 0) + len(files) - len(file_lines)
        header = f"{folder}:"
        cost = len(header) + 1
        shown = []
        for line in file_lines:
            if used + cost + len(line) + 1 + 2 * _NOTE_CHARS > SAVED_DATA_TOTAL_CHARS:
                break
            shown.append(line)
            cost += len(line) + 1
        if not shown:
            not_shown += 1
            continue
        omitted += len(file_lines) - len(shown)
        block = [header, *shown, *([f"  (+{omitted} more files not listed)"] if omitted else [])]
        lines.extend(block)
        used += sum(len(line) + 1 for line in block)
    if not lines:
        return ""
    if not_shown:
        lines.append(f"(+{not_shown} more folders not listed)")
    return title + "\n".join(lines) + "\n"


async def _saved_data_prompt(run: AgentRun, *, own: bool) -> str:
    """What the folders this Expert continues from have saved, so it need not open them to find out.

    The files are described by the sandbox probe and cached (see describe_saved_data). Any failure
    leaves the Expert with the folder paths alone: this is a hint and never keeps an Expert from starting.
    """
    describe = getattr(getattr(host(), "expert_code_execution", None), "describe_saved_data", None)
    if describe is None:
        return ""
    try:
        keys = list(dict.fromkeys(
            ([run.thread_id] if own else []) + [key for _, keys in _earlier_keys(run) for key in keys]))
        results = await asyncio.gather(*(
            asyncio.wait_for(describe(task_id=run.task_id, agent_thread_id=key, limit=SAVED_DATA_FILES),
                             SAVED_DATA_TIMEOUT_SECONDS) for key in keys), return_exceptions=True)
        root = host().task_workspace_projector.expert_session_root
        listing = []
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                _LOGGER.warning("Could not describe the saved data of %s: %r", key, result)
            else:
                listing.append((root(run.task_id, key), result))
        return _saved_data_block(listing)
    except Exception:  # a hint only
        _LOGGER.warning("Could not describe the saved data for %s", run.node_id or run.thread_id,
                        exc_info=True)
        return ""


def _earlier_attempt(run: AgentRun) -> str:
    """Another attempt at a question continues from what the earlier ones left in its folder."""
    report = host().research.report_path(run)
    folder = report.parents[2]
    if report.is_file():
        return (f"An earlier attempt at this question left its report at {report} and its files in "
                f"{folder}. Continue from them: check, correct or extend that work rather than "
                "starting over. This is still the report for this question. Do not rewrite it; "
                "update only the parts changed by this attempt.\n")
    if any(path.is_dir() and any(path.iterdir()) for path in (folder / "scratch", folder / "outputs")):
        return (f"An earlier attempt at this question left files in {folder / 'scratch'} and "
                f"{folder / 'outputs'} but no report. Reuse them rather than starting over.\n")
    return ""


async def build(config, role: str, *, run: AgentRun | None = None, middleware=None,
                subagents=None, suffix=""):
    from oceanx.context import OceanContextBuilder

    svc = services(config, role, run)
    c = config["configurable"]
    context_builder = OceanContextBuilder(store=host().store, paths=host().paths)
    research = research_mode(config)
    composition = await (
        build_ocean_runtime(services=svc, research_mode=research) if role == "coordinator" else
        build_ocean_discussion_runtime(services=svc)
        if role == "scientific_discussion_partner" else
        build_ocean_expert_runtime(services=svc)
    )
    prompt = composition.system_prompt
    tool_registry = composition.profile.tool_registry
    task_root = host().task_workspace_projector.ensure_task_root(c["task_id"])
    work_root = (host().task_workspace_projector.expert_session_root(c["task_id"], run.thread_id)
                 if run else task_root / "agents" / "coordinator")
    work_root.mkdir(parents=True, exist_ok=True)
    from oceanx.native_skills import prepare_skill_library
    # What the project learned reaches a role only inside the regions its skills reserve:
    # the helper functions always, lessons only in research mode (see ProjectResearch.skills).
    library = prepare_skill_library(
        work_root / ".runtime" / "skills",
        role=role, capabilities=svc.skill_capabilities,
        revisions=_project().skills(research=research))
    from oceanx.native_backend import task_backend
    filesystem, working_directory = task_backend(host(), config, run=run, library=library)
    discussion = role == "scientific_discussion_partner"
    static = static_figures()  # a static run describes no plotting interface (figure_delivery.py)
    if discussion:
        prompt += "\nUse ls, glob, grep and read_file to consult supplied data and result paths. These tools are read-only."
    elif role != "coordinator":
        prompt += (f"\nWorking directory for native file tools and execute: {working_directory}. "
                   + ("" if static else
                      f"Result API reference: {working_directory.parent / '.runtime' / 'result-api.md'}. ")
                   + "This working directory is task scratch: keep only calculations needed by a later "
                   "node or retry "
                   + ("and exploratory plots " if static else "")
                   + "here, not in outputs. Scratch may be removed after the task becomes idle. "
                   "Save only final deliverables under OCEAN_OUTPUT_DIR; "
                   + ("a final figure saved there as a PNG is delivered. " if static else
                      "ScientificFigure.save('name.nc') publishes there automatically. ")
                   + "Use supplied absolute data/result paths with native file tools or execute. "
                   "Source data and other agents' evidence are read-only; your working directory is writable.")
        if not static:
            prompt += ("\n" + figure_reading_rule("the Result API reference path above")
                       + " " + DRAFT_RULE + "\n" + figure_call_skeleton())
        if not research:
            prompt += "\n" + (STATIC_STANDARD_EXPERT_POLICY if static else STANDARD_EXPERT_POLICY)
        else:
            limit = int(svc.expert_code_execution.limits.wall_time_seconds or 300)
            prompt += (f"\nEach execute or ocean_expert_run_code run is stopped after {limit} s; a larger "
                       "timeout does not extend it. Split long work. ocean_expert_run_code keeps Python "
                       "variables for this attempt, so prefer it for iterative array analysis; use execute "
                       "for reproducible scripts or shell work. Do not save full source-field copies merely "
                       "to carry state within one attempt. Save only a checkpoint another node or retry needs.")
    if (svc.native_vision and research and not static
            and role not in {"coordinator", "scientific_discussion_partner"}):
        prompt += (
            "\nA saved figure may have a sibling .preview.png. Inspect it only when the image itself "
            "is scientific evidence needed for your reasoning, such as a spatial pattern; preview "
            "inspection is not a separate visual-delivery review."
        )
    if role != "coordinator":
        prompt += "\n" + profile_system_prompt(get_agent_profile(role))
        prompt += "\nOriginal researcher question:\n" + c.get("original_question", "")
    if role in {"coordinator", "literature_reproduction_expert"}:
        mode = c.get("request_options", {}).get("literature_acquisition_mode", "ask_before_download")
        prompt += "\nLiterature acquisition mode: " + mode + ". " + {
            "ask_before_download": "Ask the researcher before downloading full text.",
            "auto_download_open_access": "Open-access full text may be downloaded; ask before restricted sources.",
            "search_only": "Search metadata only; do not download or import full text.",
        }.get(mode, "Ask the researcher before downloading full text.")
    if run:
        assigned = host().research.report_path(run)
        prompt += f"\nBackend-assigned report file: {assigned}\n"
        if not static:  # a static run cites the figure file by name instead (see the Expert policy)
            prompt += (
                f"Your Agent key is {run.thread_id}. When a saved result supports a claim, write the complete "
                f"Agent-owned binding yourself, for example [{run.thread_id}/result1] for result1.nc. "
                "The result name is the .nc path below outputs without its extension; a tree node such as "
                "B1.1 is not a result name. Put the binding immediately after the supported claim so later "
                "synthesis can preserve it unchanged.\n"
            )
        try:
            earlier = _earlier_work(run)
        except Exception:  # a hint only; never keep an Expert from starting
            _LOGGER.warning("Could not list earlier work for %s", run.node_id, exc_info=True)
            earlier = []
        if earlier:
            prompt += ("Earlier steps saved their files (scratch, outputs, reports) in these folders, "
                       "read-only for you; reuse them rather than recomputing: "
                       + "; ".join(earlier) + ".\n")
        if not discussion:
            prompt += _earlier_attempt(run)
        if context_builder.policy_for(
            workspace_id=c["workspace_id"], provider_id=svc.provider_id,
        ).decision_for("metadata") == "allow":
            prompt += await _saved_data_prompt(run, own=not discussion)
        prompt += ("Return the report as final text; the backend saves it at this path.\n" if discussion else
                   "Create report.md at this exact path as soon as you have a defensible partial answer, "
                   "and keep it current as evidence changes. Begin with a short ## Summary. Do not defer "
                   "the report until the end, repeat it, or announce its path in chat.\n")
        prompt += _call_budget_sentence()
    if role in DATA_EXPERT_ROLES:
        await _describe_task_data(c)
    context = context_builder.build(
        workspace_id=c["workspace_id"], provider_id=svc.provider_id, task_id=c["task_id"],
        dataset_context_root=task_root / ".runtime" / "analysis-context")
    prompt += ("\nA source with inspection ready lists its checked variables, dimensions, units "
               "and time ranges; reuse them rather than re-inspecting the files."
               "\nDataset and workspace context:\n"
               + json.dumps(context.payload, ensure_ascii=False))
    prompt += suffix

    filesystem_tools = (
        ["ls", "glob", "grep", "read_file"]
        if discussion
        else list(COORDINATOR_FILESYSTEM_TOOLS)
        if role == "coordinator"
        else "all"
    )
    graph = await build_deep_agent_graph(
        profile=load_model_profile("coordinator" if role == "coordinator" else "expert"),
        tools=tool_registry, system_prompt=prompt,
        cwd=Path(c["workspace_path"]), operation_id_factory=host().router._operation_id,
        subagents=subagents or [], middleware=middleware,
        skill_library=None if discussion else library,
        filesystem_backend=filesystem,
        filesystem_tools=filesystem_tools,
        research_tree=research_tree(c["task_id"])
        if role == "coordinator" and research else None)
    from oceanx.research.metering import CallMeter
    return graph.with_config(callbacks=[CallMeter(host().store, config, role, run)])


def _question(state) -> str:
    return next((message.text for message in reversed(state["messages"])
                 if isinstance(message, HumanMessage)), "")


def _attempt_stop_reason(messages) -> str:
    """The same call-count reason for missing reports and unchanged-report receipts."""
    calls = sum(isinstance(message, AIMessage) for message in messages)
    return (f"it reached its {EXPERT_MODEL_CALL_LIMIT}-call limit" if calls >= EXPERT_MODEL_CALL_LIMIT
            else f"it stopped after {calls} model calls")


def _missing_report(messages, report_path: Path) -> str:
    """The handoff when there is no report and no closing prose to save as one.

    An Expert that finished on its own keeps its closing answer. Tool-call markup a model
    prints as text, as after the limit-forced tool-free call, is never forwarded.
    """
    calls = sum(isinstance(message, AIMessage) for message in messages)
    last = messages[-1] if messages else None
    if calls < EXPERT_MODEL_CALL_LIMIT and _prose(last):
        return _prose(last)
    reason = _attempt_stop_reason(messages)
    root = report_path.parents[2]
    return (f"Result: No report — {reason} without writing {report_path}. Its saved files are in "
            f"{root / 'scratch'} and {root / 'outputs'}. To recover, delegate the same node to the "
            "same Expert role and ask it to write the report from those files.")


async def _close_kernel(run: AgentRun) -> None:
    """A kernel lives for one attempt: its memory never reaches another node or a later attempt,
    and only running Experts hold memory. Saved files stay."""
    execution = getattr(host(), "expert_code_execution", None)
    if execution is not None:
        root = host().task_workspace_projector.expert_session_root(run.task_id, run.thread_id)
        try:
            await execution.kernels.close(str(root))
        except Exception:  # cleanup must not turn a finished attempt into a failed one
            _LOGGER.warning("Could not close the kernel of %s", run.thread_id, exc_info=True)


async def expert(config, role: str):
    """Compile one native task subagent with a compact file-backed return value."""
    graph = StateGraph(ExpertState)

    async def analyze(state, config):
        question = _question(state)
        run = AgentRun.from_config(config, role, question=question)
        previous_report_revision = file_revision(host().research.report_path(run))
        author = await build(
            config,
            role,
            run=run,
            middleware=[ExpertCallBudgetMiddleware(report_path=host().research.report_path(run)),
                        ToolCallRepairMiddleware()],
        )
        # The read-only Discussion Partner runs no code, so it does not take a slot.
        slot = (
            contextlib.nullcontext()
            if role == "scientific_discussion_partner"
            else _search_expert_slots()
            if role == "literature_reproduction_expert"
            else _expert_slots()
        )
        if isinstance(slot, _Slots) and slot.locked():
            _LOGGER.info("Expert %s waits for one of %d parallel slots", run.thread_id, slot.limit)
        async with slot:
            token = INSIDE_EXPERT.set(True)  # the Coordinator's inherited meter skips these calls
            try:
                result = await author.ainvoke(state, config=config)
            finally:
                INSIDE_EXPERT.reset(token)
                if role != "scientific_discussion_partner":
                    await asyncio.shield(_close_kernel(run))
        return {
            **result,
            "question": question,
            "previous_report_revision": previous_report_revision,
        }

    async def receipt(state, config):
        run = AgentRun.from_config(config, role, question=state.get("question", ""))
        previous = state.get("previous_report_revision")
        text, path = host().research.collect_report(run, previous_revision=previous)
        closing = _prose(state["messages"][-1]) if state["messages"] else ""
        unchanged_report = False
        if not text:
            # An unchanged report still answers this question. A short follow-up's closing
            # reply belongs in the receipt, not over the scientific report or its tree Summary.
            text, path = host().research.collect_report(run)
            if closing and (not text or role == "scientific_discussion_partner"
                            or report_summary(closing)):
                text, path = host().research.collect_report(run, materialize_text=closing)
            elif text:
                unchanged_report = True
        handoff = report_summary(text) or text.strip() or _missing_report(
            state["messages"], host().research.report_path(run))
        published_results: list[tuple[str, str]] = []
        saved_figures: list[tuple[str, str]] = []  # a static run: (absolute path, title)
        figure_keys: list[str] = []
        static = static_figures()
        result_store = getattr(host(), "task_results", None)
        if result_store is not None:
            task_root = (host().task_workspace_projector.ensure_task_root(run.task_id).resolve()
                         if static else None)
            for record in result_store.list(task_id=run.task_id):
                result_key = record.content.get("result_key")
                if (
                    record.kind == "interactive_view"
                    and record.agent_run_id == run.thread_id
                    and isinstance(result_key, str)
                    and result_key.strip()
                ):
                    published_results.append((result_key.strip(), record.title))
                elif (
                    static
                    and record.agent_run_id == run.thread_id
                    and record.content.get("render_status") == "static"
                    and isinstance(record.content.get("output_path"), str)
                ):
                    saved_figures.append((str(task_root / record.content["output_path"]), record.title))
                    figure_keys.append(str(result_key))
        # Structured binding from the delegation (see research/delegation.py);
        # no node ID is parsed from free text here.
        if run.node_id and path is not None and handoff:
            try:
                attached = research_tree(run.task_id).attach_result(
                    run.node_id,
                    summary=handoff,
                    agent_key=run.thread_id,
                    report_path=str(path),
                    delegation_id=run.delegation_id,
                    attempt_id=run.attempt_id,
                    expert_role=role,
                    output_refs=tuple(dict.fromkeys(
                        [key for key, _ in published_results] + figure_keys)),
                    started_at=run.delegation_started_at,
                )
                node = next(n for n in attached["projection"]["nodes"] if n["id"] == run.node_id)
                proposals = node["result"].get("proposals") or []
                if proposals:  # stable IDs the Coordinator can adopt with from_proposal
                    handoff += "\nProposal IDs: " + ", ".join(
                        f"{run.node_id}#{i}" for i in range(1, len(proposals) + 1))
            except ValueError:
                pass  # a simple task or non-tree consultation
        receipt_text = format_expert_receipt(
            handoff,
            path,
            tuple(dict.fromkeys(published_results)),
            saved_figures=tuple(dict.fromkeys(saved_figures)) if static else None,
        )
        if unchanged_report:
            if closing:
                receipt_text += ("\n\nThis attempt left the report unchanged and ended with: "
                                 + closing)
            else:
                receipt_text += ("\n\nThis attempt left the report unchanged and gave no closing "
                                 "answer: " + _attempt_stop_reason(state["messages"]) + ".")
        return {"messages": [AIMessage(content=receipt_text)]}

    graph.add_node("author", analyze)
    graph.add_node("receipt", receipt)
    graph.add_edge(START, "author")
    graph.add_edge("author", "receipt")
    graph.add_edge("receipt", END)
    return graph.compile()


BACKGROUND_EXPERTS_RULE = (
    "Experts work in the background. A task call returns as soon as the next running Expert finishes: "
    "with that Expert's receipt, or saying that its own Expert is still working, in which case the "
    "receipt comes with a later task or await_experts result. When a receipt arrives while other Experts "
    "are still running, you decide whether to wait: continue that node's own line at once, delegating its "
    "follow-up without waiting for the others; but a new question that several outstanding results must "
    "decide together waits until they have all returned, so call await_experts with their node_ids. Call "
    "await_experts when you have nothing to delegate, and write the final answer only when no Expert is "
    "still running.\n"
)


async def _coordinator_agent(config, experts: RunningExperts | None = None):
    # Workflow mode controls research-tree exploration, not whether the
    # Coordinator has a team. Standard requests may still need one or more
    # bounded Experts for analysis, acquisition, inference, or saved results.
    specs = [{"name": profile.profile_id, "description": profile.summary,
              "runnable": await expert(config, profile.profile_id)}
             for profile in AGENT_PROFILES]
    report = coordinator_report_path(config)
    report.parent.mkdir(parents=True, exist_ok=True)
    static = static_figures()  # a static run describes no plotting interface (figure_delivery.py)
    # Listed first: the rest of a task call then runs inside the Expert's background job.
    background = BackgroundDelegationMiddleware(experts if experts is not None else RunningExperts())
    if not research_mode(config):
        return await build(config, "coordinator", subagents=specs,
                           middleware=[background, ToolCallRepairMiddleware()], suffix=(
            "\n" + STANDARD_COORDINATOR_POLICY + "\n# Standard workflow\n"
            "Do not create or update a research tree, generate candidate/frontier nodes, or expand the "
            "request into an open-ended research project. This does not disable the team. Delegate bounded "
            "standalone questions to the appropriate Experts whenever the request needs scientific data "
            "analysis, statistical inference, literature or requested dataset acquisition, or a reusable "
            "scientific result. Multiple independent questions may run in parallel. Experts work in the "
            "background: a task call returns when the next one finishes, and await_experts returns the "
            "receipts of the others. Synthesize only after every Expert has returned, directly in chat. "
            + ("Cite a figure only by a path listed under Saved figures in the native task receipt; "
               "never invent a figure path. " if static else
               "Cite only keys listed under Published results in the native "
               "task receipt; never invent result1, cite an ordinary output file as a desktop result, or embed "
               "a local preview path. ")
            + "Create a Coordinator report only when the user explicitly asks for one.\n\n"
            + _visual_delivery_policy()
        ))
    from oceanx.research.delegation import StructuredDelegationMiddleware
    tree = research_tree(config["configurable"]["task_id"])
    guidance = tree.policy.guidance  # lessons are not prompt text; see build()
    budget = research_budget_minutes()
    # The budget check comes before the binding, so a refused assignment is never bound to a tree node.
    return await build(config, "coordinator", subagents=specs,
                       middleware=[background, ResearchBudgetMiddleware(budget),
                                   StructuredDelegationMiddleware(
                           tree, original_question=config["configurable"].get("original_question", "")),
                           ToolCallRepairMiddleware()],
                       suffix=(
        (f"\n{guidance}\n" if guidance else "")
        + (f"\nResearch time budget: {budget:.0f} minutes. After {RESEARCH_BUDGET_STOP * budget:.0f} "
           "minutes no new Expert assignment starts, so answer the main question before then; each "
           "receipt shows the time used.\n" if budget else "")
        + "\n" + BACKGROUND_EXPERTS_RULE
        + f"\nBackend-assigned final report file: {report}\n"
        "Native task receipts contain Result, Evidence and limitations, Further analysis, and Report. "
        "Use those compact fields for tree decisions and read report.md only when synthesis needs more detail. "
        "Before you first choose which follow-up questions to pursue, read "
        "/skills/research-trajectory-planning/SKILL.md once. "
        + ("Only the paths listed under Saved figures in a receipt are delivered figures; copy them exactly "
           "and never invent a path. If a claim has no saved figure, refer to the Expert report in prose. "
           if static else
           "Only the server-verified keys under Published results are desktop bindings; preserve those exactly. "
           "Never invent result1, cite an ordinary output file as a desktop result, or embed a local preview "
           "path. If a claim has no published result, refer to the Expert report in prose without bracket syntax. ")
        + "When the research question is answered, write the final answer to the assigned report, begin it "
        "with a short ## Summary, and finish. First read the tree with "
        "update_research_tree(changes=[], view='full') for the Research Tree section, then with "
        "view='results': the tree view clips each Result and limit, so a correction made late in a "
        "Summary appears only in view='results'. Reconcile every returned node's latest Result and "
        "Evidence and limitations before writing: a node that corrects an earlier one replaces its value, "
        "so use the corrected value and say it was corrected; keep numbers from different definitions, "
        "thresholds, periods or regions explicitly separated; open a listed report when a Summary is "
        "insufficient or two nodes conflict. Do not synthesize from only the first reports. Word each "
        "conclusion no more strongly than its evidence: write 'consistent with' unless an analysis "
        "separated the cause from the alternatives, and call a comparison independent only if the "
        "evidence shows it is. End with the required ## Research Tree section.\n\n"
        + _visual_delivery_policy()))


async def coordinator(config):
    async def coordinate(state, config):
        # Agent Server profiles graph schemas without request configuration, so
        # task-bound paths and subagents must be assembled when this node runs.
        # This is still one Coordinator run: native ``task`` calls execute inside
        # this invocation, as background jobs of it (background_experts.py), with
        # no callback or follow-up run.
        report = coordinator_report_path(config)
        previous_report_revision = file_revision(report)
        # The desktop sends its parallel-Experts setting with each request; the newest request sizes
        # the app-wide pool. None (the benchmark) keeps the environment's value.
        _expert_slots(_requested_parallel_experts(config))
        experts = RunningExperts()
        agent = await _coordinator_agent(config, experts)
        try:
            result = await agent.ainvoke(state, config=config)
        finally:
            # None is left when the run ended normally; a failed or cancelled run stops its Experts.
            await experts.close()
        report_text = (
            report.read_text(encoding="utf-8").strip()
            if file_revision(report) is not None
            and file_revision(report) != previous_report_revision else ""
        )
        last = result.get("messages", ())[-1] if result.get("messages") else None
        answer = report_text or (last.text.strip() if isinstance(last, AIMessage) else "")
        # The root is the active research-question anchor rather than an
        # Expert assignment. Attach the Coordinator's own report Summary only
        # after native task work and final synthesis have completed.
        summary = report_summary(report_text) or report_text
        tree = research_tree(config["configurable"]["task_id"]) if research_mode(config) else None
        if tree is not None and summary and report_text:
            view = tree.read()
            roots = {
                item["id"]: item for item in view["nodes"]
                if item["id"] in view["roots"]
            }
            for node_id, item in roots.items():
                if item["status"] == "active":
                    tree.attach_result(
                        node_id,
                        summary=summary,
                        agent_key="coordinator",
                        report_path=str(report),
                    )
        if tree is not None:
            # Improvement data only: never returned to a model.
            from oceanx.research.outcomes import record_task_outcomes
            try:
                c = config["configurable"]
                record_task_outcomes(
                    tree, final_report=report_text or answer,
                    model_calls=host().store.list_model_calls(c["request_id"]),
                    code_executions=[{
                        "agent_thread_id": r.agent_thread_id, "state": r.state,
                        "started_at": r.started_at,
                        "duration_seconds": (r.result or {}).get("duration_seconds"),
                        "error": (r.result or {}).get("error")
                        or ((r.result or {}).get("stderr") or "").strip()[-200:],
                        "tool_calls": (r.result or {}).get("tool_calls"),
                    } for r in host().store.list_task_code_executions(
                        workspace_id=c["workspace_id"], task_id=c["task_id"])],
                    library=_library_record(tree, report_text or answer))
                # Keep the bounded digest current; periodic cleanup runs elsewhere.
                _project().memory.digest(tree.store.path)
            except Exception:  # noqa: BLE001 - analysis data must never fail delivery
                _LOGGER.exception("Research outcome recording failed")
        delivered = AIMessage(content=answer, additional_kwargs={"oceanx_delivered": True})
        return {**result, "research_complete": True, "final_answer": answer,
                "messages": [*result.get("messages", ()), delivered]}

    graph = StateGraph(ResearchState)
    graph.add_node("coordinate", coordinate)
    graph.add_edge(START, "coordinate")
    graph.add_edge("coordinate", END)
    return graph.compile()


async def physics(config):
    return await expert(config, "ocean_process_expert")


async def statistics(config):
    return await expert(config, "statistical_inference_expert")


async def literature(config):
    return await expert(config, "literature_reproduction_expert")


async def discussion(config):
    return await expert(config, "scientific_discussion_partner")


__all__ = ["coordinator", "discussion", "expert", "literature", "physics", "statistics"]

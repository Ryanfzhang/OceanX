"""OceanX graphs built from native synchronous DeepAgents subagents.

The Coordinator is one Agent Server run. Its ``task`` calls invoke compiled
Expert graphs directly and return compact file-backed receipts to the same run;
OceanX does not mirror child lifecycle, enqueue callbacks, or resume a second
Coordinator run.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import NotRequired

from deepagents.graph import DeepAgentState
from deepagents.middleware.filesystem import FilesystemState
from deepagents.middleware.skills import SkillsState
from deepagents.middleware.summarization import SummarizationState
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from oceanx.agent_tools import ToolRegistry
from oceanx.deep_runtime import build_deep_agent_graph
from oceanx.expert_execution import FIGURE_API_CONTRACT, STANDARD_MODE_CODE_SECONDS
from oceanx.model_config import load_model_profile
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
from oceanx.tools import OceanToolServices


_LOGGER = logging.getLogger(__name__)
EXPERT_MODEL_CALL_LIMIT = 60
EXPERT_WIND_DOWN_START = 48
EXPERT_FINAL_CALL = EXPERT_MODEL_CALL_LIMIT - 1


def _parallel_expert_limit() -> int:
    try:
        return max(1, int(os.environ.get("OCEANX_MAX_PARALLEL_EXPERTS", "2")))
    except ValueError:
        return 2


# Expert runs that may work at once across the whole app; the rest wait for a free slot.
# Each run loads data and runs code on this machine, so this bounds local CPU and memory.
MAX_PARALLEL_EXPERTS = _parallel_expert_limit()
_EXPERT_SLOTS: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None


def _expert_slots() -> asyncio.Semaphore:
    """The app-wide slot pool; the Agent Server runs every graph on one event loop."""
    global _EXPERT_SLOTS
    loop = asyncio.get_running_loop()
    if _EXPERT_SLOTS is None or _EXPERT_SLOTS[0] is not loop:
        _EXPERT_SLOTS = (loop, asyncio.Semaphore(MAX_PARALLEL_EXPERTS))
    return _EXPERT_SLOTS[1]
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

If the Expert answered the scientific question but omitted the explicitly requested visual, you may make
one and only one follow-up task call to the same Expert role, for the same node_id when the question is a
research-tree node, so it works in the same folder. Ask it only to publish the requested view from
its saved evidence and include the previous report; do not request new analysis, visual polishing or another
Expert. Never make a second visual-delivery follow-up and never create a replacement yourself. If that one
follow-up still returns no suitable Published results key, finish honestly that the interactive visual was
not delivered. When a suitable key exists, cite it next to the supported conclusion in the final answer.
A .preview.png is only the fallback owned by a registered interactive result, never a standalone result.
"""


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
            "No tools are available on this final model call. Do not begin or claim new work. "
            "Return a concise, honest final answer from the report and evidence already saved. "
            "State any incompleteness explicitly."
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


WIND_DOWN_REFUSAL = (
    "Not run: the analysis phase of this assignment is over and only file tools work now. "
    "Write or update report.md from the evidence you already have, then finish."
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


class ExpertCallBudgetMiddleware(ModelCallLimitMiddleware):
    """Own the native call count and report wind-down in one middleware instance.

    Keeping both behaviours on the same middleware prevents the wind-down from
    depending on private state owned by a separate middleware instance.  Calls
    49--59 retain only report/file tools, and any other tool they still request is
    refused without running; call 60 is a tool-free delivery call.
    """

    def __init__(self) -> None:
        super().__init__(run_limit=EXPERT_MODEL_CALL_LIMIT, exit_behavior="end")

    def wrap_model_call(self, request, handler):
        return handler(_wind_down_request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(_wind_down_request(request))

    def wrap_tool_call(self, request, handler):
        return _refused_tool_call(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return _refused_tool_call(request) or await handler(request)


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


STANDARD_EXPERT_POLICY = f"""\
# Bounded request (research mode is off)
The requested output (a figure, number, table, route or file) is the finish line. First cut the data to the
variables, region, depth and period the request needs; never load a whole field or water column when a slice
answers it. Compute it with one defensible method, publish it, write the report and stop. Do not add
sensitivity tests, extra figures or statistics, investigations of individual cells or values, or re-checks of
saved outputs unless a result is clearly wrong or the researcher asked. Do not open the .preview.png of a
figure you just saved. State a remaining limitation in one sentence instead of investigating it. Each code run stops after {STANDARD_MODE_CODE_SECONDS} s; if one times
out, read less data (a smaller region or period, or a coarser stride) instead of repeating the same read.
"""

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


def _earlier_work(run: AgentRun) -> list[str]:
    """Folders of the nodes above this one and of the nodes it waits for, nearest first.

    Each node works in its own folder; these are mounted read-only for it.
    """
    if not run.node_id:
        return []
    tree = research_tree(run.task_id)
    parts = run.node_id.split(".")
    sources = [".".join(parts[:depth]) for depth in range(len(parts) - 1, 0, -1)]
    found = tree.document()["nodes"].get(run.node_id) or {}
    sources += [node for node in found.get("dependencies", ()) if node not in sources]
    lines = []
    for node in sources:
        keys = dict.fromkeys(attempt["agent_key"] for attempt in reversed(tree.attempts(node))
                             if attempt.get("agent_key") not in (None, "", "coordinator", run.thread_id))
        folders = [str(host().task_workspace_projector.expert_session_root(run.task_id, key))
                   for key in keys]
        if folders:
            lines.append(f"{node}: {', '.join(folders)}")
    return lines


async def build(config, role: str, *, run: AgentRun | None = None, middleware=None,
                subagents=None, suffix=""):
    svc = services(config, role, run)
    c = config["configurable"]
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
    if discussion:
        prompt += "\nUse ls, glob, grep and read_file to consult supplied data and result paths. These tools are read-only."
    elif role != "coordinator":
        prompt += (f"\nWorking directory for native file tools and execute: {working_directory}. "
                   f"Result API reference: {working_directory.parent / '.runtime' / 'result-api.md'}. "
                   "This working directory is task scratch: keep reusable calculations here, "
                   "not in outputs. Scratch may be removed after the task becomes idle. "
                   "Save only final deliverables under OCEAN_OUTPUT_DIR; "
                   "ScientificFigure.save('name.nc') publishes there automatically. "
                   "Use supplied absolute data/result paths with native file tools or execute. "
                   "Source data and other agents' evidence are read-only; your working directory is writable.")
        prompt += ("\nFigure API (complete; do not read OceanX source code to learn it): "
                   + FIGURE_API_CONTRACT["constructor"] + ". Examples:\n"
                   + "\n".join(FIGURE_API_CONTRACT["examples"])
                   + "\nPalettes: ocean_teal (sequential, default), blue_red (diverging), grouped (categories).")
        if not research:
            prompt += "\n" + STANDARD_EXPERT_POLICY
        else:
            limit = int(svc.expert_code_execution.limits.wall_time_seconds or 300)
            prompt += (f"\nEach execute or ocean_expert_run_code run is stopped after {limit} s; a larger "
                       "timeout does not extend it. Split long work and save intermediate files.")
    if svc.native_vision and research and role not in {"coordinator", "scientific_discussion_partner"}:
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
        prompt += ("Return the report as final text; the backend saves it at this path.\n" if discussion else
                   "Create report.md at this exact path as soon as you have a defensible partial answer, "
                   "and keep it current as evidence changes. Begin with a short ## Summary. Do not defer "
                   "the report until the end, repeat it, or announce its path in chat.\n")
    if role in DATA_EXPERT_ROLES:
        await _describe_task_data(c)
    from oceanx.context import OceanContextBuilder
    context = OceanContextBuilder(store=host().store, paths=host().paths).build(
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


def _missing_report(messages, report_path: Path) -> str:
    """The handoff when no report was written.

    An Expert that finished on its own keeps its closing answer. After the limit-forced,
    tool-free final call the text can be raw tool-call markup, so it is never forwarded.
    """
    calls = sum(isinstance(message, AIMessage) for message in messages)
    last = messages[-1] if messages else None
    if (calls < EXPERT_MODEL_CALL_LIMIT and isinstance(last, AIMessage) and not last.tool_calls
            and last.text.strip()):
        return last.text.strip()
    reason = (f"it reached its {EXPERT_MODEL_CALL_LIMIT}-call limit" if calls >= EXPERT_MODEL_CALL_LIMIT
              else f"it stopped after {calls} model calls")
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
            middleware=[ExpertCallBudgetMiddleware()],
        )
        # The read-only Discussion Partner runs no code, so it does not take a slot.
        slot = contextlib.nullcontext() if role == "scientific_discussion_partner" else _expert_slots()
        if isinstance(slot, asyncio.Semaphore) and slot.locked():
            _LOGGER.info("Expert %s waits for one of %d parallel slots", run.thread_id,
                         MAX_PARALLEL_EXPERTS)
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
        last = state["messages"][-1]
        materialize = last.text if role == "scientific_discussion_partner" else None
        text, path = host().research.collect_report(
            run,
            materialize_text=materialize,
            previous_revision=state.get("previous_report_revision"),
        )
        handoff = report_summary(text) or text.strip() or _missing_report(
            state["messages"], host().research.report_path(run))
        published_results: list[tuple[str, str]] = []
        result_store = getattr(host(), "task_results", None)
        if result_store is not None:
            for record in result_store.list(task_id=run.task_id):
                result_key = record.content.get("result_key")
                if (
                    record.kind == "interactive_view"
                    and record.agent_run_id == run.thread_id
                    and isinstance(result_key, str)
                    and result_key.strip()
                ):
                    published_results.append((result_key.strip(), record.title))
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
                    output_refs=tuple(dict.fromkeys(key for key, _ in published_results)),
                    started_at=run.delegation_started_at,
                )
                node = next(n for n in attached["projection"]["nodes"] if n["id"] == run.node_id)
                proposals = node["result"].get("proposals") or []
                if proposals:  # stable IDs the Coordinator can adopt with from_proposal
                    handoff += "\nProposal IDs: " + ", ".join(
                        f"{run.node_id}#{i}" for i in range(1, len(proposals) + 1))
            except ValueError:
                pass  # a simple task or non-tree consultation
        return {"messages": [AIMessage(content=format_expert_receipt(
            handoff,
            path,
            tuple(dict.fromkeys(published_results)),
        ))]}

    graph.add_node("author", analyze)
    graph.add_node("receipt", receipt)
    graph.add_edge(START, "author")
    graph.add_edge("author", "receipt")
    graph.add_edge("receipt", END)
    return graph.compile()


async def _coordinator_agent(config):
    # Workflow mode controls research-tree exploration, not whether the
    # Coordinator has a team. Standard requests may still need one or more
    # bounded Experts for analysis, acquisition, inference, or saved results.
    specs = [{"name": profile.profile_id, "description": profile.summary,
              "runnable": await expert(config, profile.profile_id)}
             for profile in AGENT_PROFILES]
    report = coordinator_report_path(config)
    report.parent.mkdir(parents=True, exist_ok=True)
    if not research_mode(config):
        return await build(config, "coordinator", subagents=specs, suffix=(
            "\n" + STANDARD_COORDINATOR_POLICY + "\n# Standard workflow\n"
            "Do not create or update a research tree, generate candidate/frontier nodes, or expand the "
            "request into an open-ended research project. This does not disable the team. Delegate bounded "
            "standalone questions to the appropriate Experts whenever the request needs scientific data "
            "analysis, statistical inference, literature or requested dataset acquisition, or a reusable "
            "scientific result. Multiple independent questions may run in parallel. Synthesize returned "
            "Expert results directly in chat. Cite only keys listed under Published results in the native "
            "task receipt; never invent result1, cite an ordinary output file as a desktop result, or embed "
            "a local preview path. Create a Coordinator report "
            "only when the user explicitly asks for one.\n\n"
            + COORDINATOR_VISUAL_DELIVERY_POLICY
        ))
    from oceanx.research.delegation import StructuredDelegationMiddleware
    tree = research_tree(config["configurable"]["task_id"])
    guidance = tree.policy.guidance  # lessons are not prompt text; see build()
    return await build(config, "coordinator", subagents=specs,
                       middleware=[StructuredDelegationMiddleware(tree)], suffix=(
        (f"\n{guidance}\n" if guidance else "")
        + f"\nBackend-assigned final report file: {report}\n"
        "Native task receipts contain Result, Evidence and limitations, Further analysis, and Report. "
        "Use those compact fields for tree decisions and read report.md only when synthesis needs more detail. "
        "Before you first choose which follow-up questions to pursue, read "
        "/skills/research-trajectory-planning/SKILL.md once. "
        "Only the server-verified keys under Published results are desktop bindings; preserve those exactly. "
        "Never invent result1, cite an ordinary output file as a desktop result, or embed a local preview "
        "path. If a claim has no published result, refer to the Expert report in prose without bracket syntax. "
        "When the research question is answered, write the final answer to the assigned report, begin it "
        "with a short ## Summary, and finish. First read the tree with "
        "update_research_tree(changes=[], view='full') and end with the required ## Research Tree section.\n\n"
        + COORDINATOR_VISUAL_DELIVERY_POLICY))


async def coordinator(config):
    async def coordinate(state, config):
        # Agent Server profiles graph schemas without request configuration, so
        # task-bound paths and subagents must be assembled when this node runs.
        # This is still one Coordinator run: native ``task`` calls execute and
        # return inside this invocation, with no callback or follow-up run.
        report = coordinator_report_path(config)
        previous_report_revision = file_revision(report)
        agent = await _coordinator_agent(config)
        result = await agent.ainvoke(state, config=config)
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

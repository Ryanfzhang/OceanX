"""The single agent works on a request first; the research team takes over an open research problem."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langchain_core.tools import tool
from pydantic import Field

from oceanx.agent_contract import (
    AssistantTurnComplete,
    ConversationMessage,
    TextBlock,
    ToolExecutionCompleted,
    ToolExecutionStarted,
    UsageSnapshot,
)
from oceanx.backend.events import BackendClient, EventBus
from oceanx.backend.router import OceanRequestRouter
from oceanx.backend.store import RequestStore
from oceanx.batch import QueryCase
from oceanx.protocol.v2.models import parse_request
from oceanx.research import graphs
from oceanx.research.metering import INSIDE_EXPERT, CallMeter
from oceanx.research.routing import (
    AGENT_TAG,
    FIGURE_MINUTES,
    HANDOFF_POLICY,
    HANDOFF_TOOL,
    HELPER,
    HELPER_POLICY,
    HELPER_TOOL,
    LAST_CALL,
    LAST_CALL_HANDOFF,
    PAPER_SKILL,
    PLAIN_TEXT_RETRY,
    SINGLE_AGENT,
    SINGLE_AGENT_CALL_LIMIT,
    SINGLE_AGENT_MINUTES,
    TEAM,
    HandoffMiddleware,
    HelperMiddleware,
    PaperSkillMiddleware,
    QuickCallBudgetMiddleware,
    handoff_request,
    paper_rule,
    seen_by,
    tagged,
    team_config,
    time_budget_sentence,
    workflow_mode,
)
from oceanx.research.services import AgentRun
from oceanx.research.tool_calls import ToolCallRepairMiddleware
from oceanx.tools import OceanToolServices


def _config(mode=None, **options):
    if mode:
        options["workflow_mode"] = mode
    return {"configurable": {"workspace_id": "ws", "task_id": "task", "request_id": "request",
                             "thread_id": "thread", "request_options": options}}


def _call(name, args, call_id=None):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id or f"{name}-1",
                                              "type": "tool_call"}])


class _ProbeModel(FakeMessagesListChatModel):
    bound_tool_names: list[tuple[str, ...]] = Field(default_factory=list)
    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **_kwargs: Any):
        self.bound_tool_names.append(tuple(
            tool.name if hasattr(tool, "name") else str(tool.get("name", "")) for tool in tools))
        return self

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        self.seen_messages.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


# --- the mode -------------------------------------------------------------------------------------

def test_headless_runs_keep_the_team_and_the_desktop_mode_is_auto():
    assert workflow_mode(_config()) == "research"  # the benchmark and the CLI: the team at once
    assert workflow_mode(_config("auto")) == "auto"
    assert workflow_mode(_config("standard")) == "standard"
    assert workflow_mode(_config("something-else")) == "research"
    assert graphs.research_mode(_config()) is True
    assert graphs.research_mode(_config("auto")) is False and graphs.research_mode(_config("standard")) is False
    assert QueryCase(id="q", query="Why?").workflow_mode == "research"
    assert QueryCase(id="q", query="Plot SST", workflow_mode="auto").workflow_mode == "auto"
    request = parse_request({
        "protocol_version": 2, "request_id": "req_auto", "type": "session.submit",
        "payload": {"text": "画出海表温度", "workflow_mode": "auto"},
        "context": {"session_id": "s", "workspace_id": "w", "client_id": "c", "task_id": "task_t"},
        "expected_workspace_revision": 0})
    assert request.payload.workflow_mode == "auto"


def test_a_request_handed_over_continues_in_research_mode():
    config = _config("auto", max_parallel_experts=3)
    handed = team_config(config)
    assert graphs.research_mode(handed) is True
    assert handed["configurable"]["request_options"] == {"workflow_mode": "research", "max_parallel_experts": 3}
    assert handed["configurable"]["task_id"] == "task"
    assert config["configurable"]["request_options"]["workflow_mode"] == "auto"  # the run's own is unchanged


# --- prompts, skills and tools ------------------------------------------------------------------------

def test_the_policies_name_the_tools_the_rule_and_the_finish_line():
    handoff, helpers = " ".join(HANDOFF_POLICY.split()), " ".join(HELPER_POLICY.split())
    assert "OceanX handles four kinds of tasks. Handle these yourself:" in handoff
    assert "basic Q&A" in handoff
    assert "no given paper or method already settles" in handoff
    assert "Decide from the request text alone, before reading files or data." in handoff
    assert "The number of steps, datasets or figures does not decide the route" in handoff
    assert "ROUTE:" not in handoff
    assert f"For research questions, your first and only tool call must be {HANDOFF_TOOL}, then stop." in handoff
    assert "Do not inspect data to decide the initial route." in handoff
    # Reproduction with new data stays with the single agent and is not cut short as bounded work.
    assert "reproducing a paper or applying its method, including to different data or periods" in handoff
    # The exception comes first: placed after "the requested output is the finish line", it lost to it and
    # a paper's analysis on new data ended with one figure and the rest offered for later (2026-11-01).
    bounded = " ".join(graphs.bounded_work_policy(False).split())
    reproduction = "Reproducing, testing or applying a paper's analysis is not bounded work"
    assert bounded.index(reproduction) < bounded.index("finish line")
    assert "nothing the data allow is withheld or left as an offer for later" in bounded
    # The paper's way of drawing is part of its method, also with other data (the researcher, 2026-11-03).
    assert "each of the paper's figures redrawn as the paper draws it" in bounded
    # Reading only what the work needs holds for a paper's analysis too, and thinning a record is not a free way
    # to save time: a run of 2026-11-01 read whole fields and kept every 12th day of daily data.
    assert "For every request, read only the variables" in bounded
    # The researcher allowed reading, say, every fifth day of daily data when the answer says so (2026-11-03):
    # the full daily year that runs read to check a thinned record cost them about a quarter of an hour.
    assert "Reading every n-th time step is allowed when the timescale studied is much longer" in bounded
    assert "say in the answer which steps you read" in bounded and "compare the two on a" not in bounded
    assert HELPER_TOOL in helpers and "up to 3 helpers" in helpers
    interactive, static = graphs.bounded_work_policy(False), graphs.bounded_work_policy(True)
    assert "finish line" in interactive and "Code runs until it ends, with no time limit" in interactive
    # A run of 2026-11-02 started three batches of years with nohup and returned; each batch was stopped with its
    # command, the agent waited 7 minutes for nothing and then ran the missing years one after another. Benchmark
    # runs the same day looped over a large array on one core inside the Python tool, which cannot start
    # processes. Work over many files is split into parts, one part is measured, and the parts run in parallel.
    assert "independent parts and run them in parallel" in interactive
    assert "run one part first to check its result, its time and its memory" in interactive
    assert "as many at once as the cores and free memory allow, and wait for all of them there" in interactive
    assert "background is stopped when its command returns, and ocean_expert_run_code cannot start" in interactive
    assert ".preview.png" in interactive and "the image" in static
    from oceanx.runtime import (
        FIGURE_VERIFICATION_POLICY, OCEAN_EXPERT_WORKSTREAM_POLICY, STATIC_EXPERT_WORKSTREAM_POLICY,
    )
    for policy in (OCEAN_EXPERT_WORKSTREAM_POLICY, STATIC_EXPERT_WORKSTREAM_POLICY):
        assert FIGURE_VERIFICATION_POLICY in policy
        assert "Do not spend a separate round" not in policy
    for policy in (interactive, static):
        assert "Checking and correcting the requested output is part of the task." in policy
        assert "Do not open" not in policy and "render a preview" not in policy
    # A paper's figure is a vector PDF; its preview is drawn after the run, so the agent opens it, not makes it.
    expert = " ".join(OCEAN_EXPERT_WORKSTREAM_POLICY.split())
    assert "use matplotlib and a vector PDF even when ScientificFigure supports its plot type" in expert
    assert "its picture is beside it as `concise-name.pdf.preview.png`" in expert
    # Looking at a saved figure has one rule (FIGURE_VERIFICATION_POLICY); the figure skill does not contradict it.
    from oceanx.skills import load_ocean_skill
    assert "repair round" not in load_ocean_skill("scientific-figure-design")[0]
    assert HANDOFF_TOOL in LAST_CALL_HANDOFF and "no tools" in LAST_CALL


@pytest.mark.asyncio
@pytest.mark.parametrize("figure_delivery", ["interactive", "static"])
async def test_the_single_agent_and_its_helpers_answer_without_a_report(monkeypatch, figure_delivery):
    from oceanx.runtime import (
        OCEAN_HELPER_PROMPT, OCEAN_RESEARCH_PARTNER_SYSTEM_PROMPT, OCEAN_SINGLE_AGENT_PROMPT,
        build_ocean_single_agent_runtime)
    monkeypatch.setenv("OCEANX_FIGURE_DELIVERY", figure_delivery)
    services = OceanToolServices(workspace_id="ws", provider_id="p", store=SimpleNamespace(),
                                 skill_role=SINGLE_AGENT,
                                 skill_capabilities=("literature.read", "web.search", "jina.reader"))
    single = await build_ocean_single_agent_runtime(services=services, routing=HANDOFF_POLICY)
    helper = await build_ocean_single_agent_runtime(services=services, helper=True)
    assert "report.md" not in single.system_prompt and "report.md" not in helper.system_prompt
    assert "in your answer" in single.system_prompt and "in your reply" in helper.system_prompt
    assert single.system_prompt.startswith(OCEAN_RESEARCH_PARTNER_SYSTEM_PROMPT)
    assert single.system_prompt.index(HANDOFF_POLICY) < single.system_prompt.index(OCEAN_SINGLE_AGENT_PROMPT)
    assert single.system_prompt.count(HANDOFF_POLICY) == 1
    assert HANDOFF_POLICY not in helper.system_prompt
    assert helper.system_prompt.startswith(OCEAN_HELPER_PROMPT)
    names = {tool.name for tool in single.profile.tool_registry.as_langchain_tools(
        cwd=Path("."), operation_id_factory=lambda *args: "op")}
    assert {"web_search", "jina_reader"} <= names


@pytest.mark.asyncio
async def test_only_the_single_agent_and_its_helpers_get_a_long_command_back_as_a_job(tmp_path, monkeypatch):
    """execute waits at most ten minutes for them (command_jobs.py) and their code has no time limit; the
    team waits until a command ends, and its commands and Python stop after 300 s per run."""
    from oceanx.command_jobs import JOB_WAIT_SECONDS
    from oceanx.expert_execution import RESEARCH_CODE_SECONDS
    from tests.test_oceanx.test_saved_data_index import _backend

    async with _backend(tmp_path, monkeypatch) as (host, _task, config, seen):
        commands = []

        async def run_shell(**kwargs):
            commands.append(kwargs["seconds"])
            return SimpleNamespace(stdout="", stderr="", returncode=0, figure_notes=(), limit_trigger=None)

        monkeypatch.setattr(host.expert_code_execution, "run_shell", run_shell)
        waits, tools, kernel = {}, {}, {}
        for role in (SINGLE_AGENT, HELPER, "ocean_process_expert"):
            await graphs.build(config, role, run=AgentRun.from_config(config, role, question="B1: SST"))
            waits[role] = seen["filesystem_backend"].default.wait_seconds
            tools[role] = {tool.name for tool in seen["tools"].list_tools()}
            kernel[role] = next(tool.services.code_seconds for tool in seen["tools"].list_tools()
                                if tool.name == "ocean_expert_run_code")
            await seen["filesystem_backend"].default.aexecute("python years.py")
    assert waits == {SINGLE_AGENT: JOB_WAIT_SECONDS, HELPER: JOB_WAIT_SECONDS, "ocean_process_expert": None}
    assert commands == [None, None, RESEARCH_CODE_SECONDS]
    assert kernel == {SINGLE_AGENT: None, HELPER: None, "ocean_process_expert": RESEARCH_CODE_SECONDS}
    assert {"check_job", "stop_job"} <= tools[SINGLE_AGENT] and {"check_job", "stop_job"} <= tools[HELPER]
    assert not {"check_job", "stop_job"} & tools["ocean_process_expert"]


def test_the_single_agent_reads_the_skills_of_the_data_and_search_experts(tmp_path):
    from oceanx.native_skills import prepare_skill_library
    library = prepare_skill_library(tmp_path / "skills", role=SINGLE_AGENT,
                                    capabilities=("literature.read", "web.search", "jina.reader"))
    names = {path.name for path in (library / "skills").iterdir()}
    assert {"xarray-array-ops", "scientific-figure-design", "ocean-dataset-diagnosis",
            "ocean-analysis-design", "ocean-data-acquisition", "paper-navigator"} <= names
    assert "research-trajectory-planning" not in names  # the Coordinator's planning skill
    helper = prepare_skill_library(tmp_path / "helper", role=HELPER,
                                   capabilities=("literature.read", "web.search", "jina.reader"))
    assert {path.name for path in (helper / "skills").iterdir()} == names


def test_a_paper_skill_is_kept_only_for_a_request_whose_agent_opened_it(tmp_path):
    # The attached paper names the skill to read when the request applies its analysis; named only
    # in the paper's text note, it was not opened in a run of 2026-11-01, and read_file shows its
    # first 100 lines. Once opened, all of it ends the instructions of that request, past a summary.
    from oceanx.native_skills import prepare_skill_library
    assert paper_rule([]) == ""
    rule = paper_rule(["/cache/pdf-text/zheng.v4.txt"])
    assert "/cache/pdf-text/zheng.v4.txt" in rule
    assert f"read {PAPER_SKILL} before any other tool call" in rule
    library = prepare_skill_library(tmp_path / "skills", role=SINGLE_AGENT)
    kept = PaperSkillMiddleware(library / PAPER_SKILL.removeprefix("/"))

    def system(state, messages=None):
        request = ModelRequest(model=SimpleNamespace(), messages=messages or state, tools=[],
                               state={"messages": state},
                               system_message=SystemMessage(content="base"))
        return kept._prepare(request).system_message.text

    asked = HumanMessage(content="Apply the paper's method to my data")
    read = {"name": "read_file", "args": {"file_path": PAPER_SKILL}, "id": "r1", "type": "tool_call"}
    opened = [AIMessage(content="", tool_calls=[read]),
              ToolMessage(content="first 100 lines", tool_call_id="r1")]
    assert system([asked]) == "base"
    text = system([asked, *opened], messages=[HumanMessage(content="Summary of the earlier work")])
    assert text.startswith("base\n\n# Paper skill") and "name: paper-reproduction" not in text
    for part in ("Before computing anything, write repro_spec.md", "## Figures", "## Reporting",
                 "Quoted from /skills/ocean-physical-consistency-review/SKILL.md"):
        assert part in text
    # The next request is decided again.
    later = [asked, *opened, AIMessage(content="Done."), HumanMessage(content="What is its DOI?")]
    assert system(later) == "base"


def test_the_agents_repro_spec_comes_with_the_paper_skill_as_the_file_stands(tmp_path):
    # A run of 2026-11-03 wrote in repro_spec.md which panels and terms its data allowed, never read the
    # file again, and after a summary answered that they could not be computed.
    from oceanx.native_skills import prepare_skill_library
    from oceanx.research.routing import REPRO_SPEC, SPEC_CHARS
    library = prepare_skill_library(tmp_path / "skills", role=SINGLE_AGENT)
    spec = tmp_path / "scratch" / REPRO_SPEC
    kept = PaperSkillMiddleware(library / PAPER_SKILL.removeprefix("/"), spec=spec)
    read = {"name": "read_file", "args": {"file_path": PAPER_SKILL}, "id": "r1", "type": "tool_call"}
    state = [HumanMessage(content="Apply the paper's method to my data"),
             AIMessage(content="", tool_calls=[read]), ToolMessage(content="the skill", tool_call_id="r1")]

    def system():
        request = ModelRequest(model=SimpleNamespace(), messages=state, tools=[], state={"messages": state},
                               system_message=SystemMessage(content="base"))
        return kept._prepare(request).system_message.text

    assert f"# {REPRO_SPEC}" not in system()  # not written yet
    spec.parent.mkdir()
    spec.write_text("Fig. 4 (f)-(h): trend maps are computable\n", encoding="utf-8")
    text = system()
    assert text.index("# Paper skill") < text.index(f"# {REPRO_SPEC}")
    assert "Fig. 4 (f)-(h): trend maps are computable" in text and str(spec) in text
    spec.write_text("Fig. 4 (f)-(h): drawn\n", encoding="utf-8")  # each call shows the file as it stands
    assert "Fig. 4 (f)-(h): drawn" in system() and "trend maps are computable" not in system()
    spec.write_text("x" * (SPEC_CHARS + 50), encoding="utf-8")
    assert "x" * (SPEC_CHARS + 1) not in system() and f"[The rest is in {spec}.]" in system()


def test_the_original_of_a_figure_is_the_paper_image_the_spec_names_with_it(tmp_path):
    from oceanx.research.routing import original_for
    images = {name: tmp_path / name for name in ("page-02-figure-1.jpg", "page-04-figure-1.jpg", "page-05.jpg",
                                                 "page-05-figure-1.jpg", "page-06-figure-1.jpg")}
    # A heading for each figure, as a run of 2026-11-04 wrote it; an image drawn of a saved PDF is the figure's.
    spec = ("# Figures\n### Fig. 2 — page-04-figure-1.jpg — layer vorticity\n- dashed trends\n"
            "### Fig. 3 — page-05.jpg, page-05-figure-1.jpg — vorticity budget\n- (b) Γ filled about its mean\n")
    assert original_for("/scratch/fig3-vorticity-budget.pdf.preview.png", spec, images) == (
        images["page-05-figure-1.jpg"], "Fig. 3 (page-05-figure-1.jpg)")
    assert original_for("/outputs/Figure2_layers.png", spec, images)[0] == images["page-04-figure-1.jpg"]
    # A run of 2026-11-05 checked its figures as drafts named _fig2_check.png, with fig2.pdf in its spec.
    assert original_for("/scratch/_fig2_check.png", spec, images)[0] == images["page-04-figure-1.jpg"]
    assert original_for("/scratch/config3.png", spec, images) is None
    # A file without a number is found where the spec names it, under the figure's heading.
    named = spec + "### Fig. 4 — page-06-figure-1.jpg — schematic\n- saved as scs-regime-trends.pdf\n"
    assert original_for("scs-regime-trends.pdf.display.png", named, images) == (
        images["page-06-figure-1.jpg"], "Fig. 4 (page-06-figure-1.jpg)")
    # One line listing the figures gives each its own image; a table row may name the image first.
    listed = "Originals: Fig. 2 page-04-figure-1.jpg, Fig. 3 page-05-figure-1.jpg, Fig. 1 page-02-figure-1.jpg\n"
    assert original_for("fig3.png", listed, images)[0] == images["page-05-figure-1.jpg"]
    assert original_for("fig1.png", "| page-02-figure-1.jpg | Fig. 1 | maps |\n", images)[0] == (
        images["page-02-figure-1.jpg"])
    # Nothing when the spec names no image of the paper for the figure, and a line about another
    # figure lends it none.
    assert original_for("fig5.png", spec, images) is None
    assert original_for("sst_map.png", spec, images) is None
    assert original_for("fig2.png", "### Fig. 2 — page-09-figure-2.jpg\n", images) is None
    assert original_for("fig3.png", "Fig. 3a uses the layers of Fig. 2 (page-04-figure-1.jpg)\n", images) is None


def test_the_agents_own_figure_comes_with_the_original_its_spec_names(tmp_path):
    # A run of 2026-11-04 opened the original of Fig. 3 once, at its start, and judged its own previews
    # three times against a repro_spec.md that had dropped the original's fills.
    import base64

    from oceanx.native_skills import prepare_skill_library
    from oceanx.research.routing import ORIGINAL_NOTE, REPRO_SPEC
    library = prepare_skill_library(tmp_path / "skills", role=SINGLE_AGENT)
    text = tmp_path / "cache" / "zheng.v5.txt"
    figures = text.with_suffix(".figures")
    figures.mkdir(parents=True)
    (figures / "page-05-figure-1.jpg").write_bytes(b"original")
    spec = tmp_path / "scratch" / REPRO_SPEC
    spec.parent.mkdir()
    spec.write_text("### Fig. 3 — page-05-figure-1.jpg — vorticity budget\n", encoding="utf-8")
    kept = PaperSkillMiddleware(library / PAPER_SKILL.removeprefix("/"), spec=spec, papers=[str(text)])
    skill = {"name": "read_file", "args": {"file_path": PAPER_SKILL}, "id": "r1", "type": "tool_call"}
    opened = [HumanMessage(content="Apply the paper's method to my data"),
              AIMessage(content="", tool_calls=[skill]), ToolMessage(content="the skill", tool_call_id="r1")]
    mine = {"type": "image", "base64": "bWluZQ==", "mime_type": "image/png"}

    def read(path, earlier=opened, block=mine):
        call = {"name": "read_file", "args": {"file_path": path}, "id": "r2", "type": "tool_call"}
        result = ToolMessage(content_blocks=[block], name="read_file", tool_call_id="r2")
        request = SimpleNamespace(tool_call=call, state={
            "messages": [*earlier, AIMessage(content="", tool_calls=[call])]})
        return kept.wrap_tool_call(request, lambda _request: result).content

    seen = read(str(spec.parent / "fig3-vorticity-budget.pdf.preview.png"))
    assert [block["type"] for block in seen] == ["image", "text", "image"]
    assert seen[1]["text"] == ORIGINAL_NOTE.format(original="Fig. 3 (page-05-figure-1.jpg)", spec=REPRO_SPEC)
    assert seen[2] == {"type": "image", "base64": base64.b64encode(b"original").decode(), "mime_type": "image/jpeg"}
    # Nothing comes with the original itself, a figure the spec names no original for, a text, or an
    # image opened before the paper skill in this request.
    assert len(read(str(figures / "page-05-figure-1.jpg"))) == 1
    assert len(read("fig4.png")) == 1
    assert len(read("notes.md", block={"type": "text", "text": "notes"})) == 1
    assert len(read("fig3.png", earlier=opened[:1])) == 1


# --- the conversation each agent sees --------------------------------------------------------------

def test_each_agent_sees_the_other_ones_answers_but_not_its_tool_work():
    human = HumanMessage(content="first", id="h1")
    single = tagged([_call(HANDOFF_TOOL, {"reason": "r"}), ToolMessage(
        content="ok", tool_call_id=f"{HANDOFF_TOOL}-1", name=HANDOFF_TOOL)], SINGLE_AGENT)
    team = tagged([_call("task", {"description": "B1"}, "task-1"),
                   ToolMessage(content="receipt", tool_call_id="task-1", name="task"),
                   AIMessage(content="The team's answer.", additional_kwargs={"oceanx_delivered": True})], TEAM)
    later = HumanMessage(content="second", id="h2")
    messages = [human, *single, *team, later]
    assert seen_by(messages, SINGLE_AGENT) == [human, *single, team[-1], later]
    assert seen_by(messages, TEAM) == [human, *team, later]
    assert all(message.additional_kwargs[AGENT_TAG] == TEAM for message in team)
    assert team[-1].additional_kwargs["oceanx_delivered"] is True  # tagging keeps what was there


# --- the top-level graph ----------------------------------------------------------------------------

class _Agent:
    def __init__(self, reply, seen):
        self.reply, self.seen = reply, seen

    async def ainvoke(self, state, config=None):
        self.seen.append((list(state["messages"]), config))
        return {"messages": [*state["messages"], *self.reply]}


@pytest.fixture
def world(monkeypatch, tmp_path):
    calls = {"single": [], "team": [], "team_configs": [], "handoffs": [], "closed": []}
    replies = {"single": [AIMessage(content="图已画好。")], "team": [AIMessage(content="The team's answer.")]}

    async def single_agent(config, run):
        calls["single_built"] = (workflow_mode(config), run.thread_id)
        return _Agent(replies["single"], calls["single"])

    async def coordinator_agent(config, experts, *, handoff=""):
        calls["team_configs"].append(config)
        calls["handoffs"].append(handoff)
        return _Agent(replies["team"], calls["team"])

    async def close_kernel(run):
        calls["closed"].append(run.thread_id)

    monkeypatch.setattr(graphs, "_single_agent", single_agent)
    monkeypatch.setattr(graphs, "_coordinator_agent", coordinator_agent)
    monkeypatch.setattr(graphs, "_close_kernel", close_kernel)
    monkeypatch.setattr(graphs, "coordinator_report_path", lambda _config: tmp_path / "report.md")
    monkeypatch.setattr(graphs, "research_tree", lambda _task_id: SimpleNamespace())
    monkeypatch.setattr(graphs, "host", lambda: SimpleNamespace(task_workspace_projector=SimpleNamespace(
        expert_session_root=lambda task_id, key: tmp_path / "agents" / key)))
    return SimpleNamespace(calls=calls, replies=replies, root=tmp_path)


@pytest.mark.asyncio
async def test_a_simple_request_is_answered_by_the_single_agent_alone(world):
    config = _config("auto")
    graph = await graphs.coordinator(config)
    result = await graph.ainvoke({"messages": [HumanMessage(content="画出 8 月 15 日的海表温度")]}, config)
    assert world.calls["team"] == []
    assert result["final_answer"] == "图已画好。" and result["handoff"] == ""
    assert result["messages"][-1].additional_kwargs[AGENT_TAG] == SINGLE_AGENT
    mode, key = world.calls["single_built"]
    assert mode == "auto" and key.startswith("single-agent-")
    assert world.calls["closed"] == [key]  # its kernel lives for one request


@pytest.mark.asyncio
async def test_the_researchers_stop_also_stops_the_tasks_jobs_and_an_ended_request_leaves_them(world, monkeypatch):
    """A job still running when a request ends goes on, for a later "continue"; the stop button ends it."""
    stopped = []

    async def stop_jobs(task_id):
        stopped.append(task_id)

    monkeypatch.setattr(graphs, "_stop_jobs", stop_jobs)
    config = _config("auto")
    graph = await graphs.coordinator(config)
    await graph.ainvoke({"messages": [HumanMessage(content="画出 8 月 15 日的海表温度")]}, config)
    assert stopped == []
    started = asyncio.Event()

    class Working:
        async def ainvoke(self, state, config=None):
            started.set()
            await asyncio.Event().wait()

    async def single_agent(config, run):
        return Working()

    monkeypatch.setattr(graphs, "_single_agent", single_agent)
    graph = await graphs.coordinator(config)
    request = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="复现论文的图 3")]}, config))
    await started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert stopped == ["task"] and len(world.calls["closed"]) == 2


@pytest.mark.asyncio
async def test_an_open_research_problem_is_handed_to_the_team_in_the_same_run(world):
    world.replies["single"] = [
        _call(HANDOFF_TOOL, {"reason": "这个问题要比较几种机制，已转交研究团队。", "progress": ""}),
        ToolMessage(content="ok", tool_call_id=f"{HANDOFF_TOOL}-1", name=HANDOFF_TOOL)]
    config = _config("auto", max_parallel_experts=2)
    graph = await graphs.coordinator(config)
    question = HumanMessage(content="为什么坎佩切湾的冷涡能维持这么久？")
    result = await graph.ainvoke({"messages": [question]}, config)

    team_config_seen = world.calls["team_configs"][0]
    assert graphs.research_mode(team_config_seen)
    assert team_config_seen["configurable"]["request_options"]["max_parallel_experts"] == 2
    assert "这个问题要比较几种机制" in world.calls["handoffs"][0]
    assert str(world.root / "agents") in world.calls["handoffs"][0]  # where its files are
    team_view, invoked_with = world.calls["team"][0]
    assert [message.text for message in team_view] == [question.text]  # not the single agent's tool work
    assert graphs.research_mode(invoked_with)
    delivered = result["messages"][-1]
    assert delivered.text == "The team's answer." and delivered.additional_kwargs["oceanx_delivered"]
    assert delivered.additional_kwargs[AGENT_TAG] == TEAM
    assert result["research_complete"] is True and result["handoff"] == ""


@pytest.mark.asyncio
async def test_research_mode_goes_to_the_team_at_once_and_standard_never_hands_over(world):
    config = _config()
    graph = await graphs.coordinator(config)
    await graph.ainvoke({"messages": [HumanMessage(content="Why?")]}, config)
    assert "single_built" not in world.calls and len(world.calls["team"]) == 1

    world.replies["single"] = [_call(HANDOFF_TOOL, {"reason": "r"}),
                               ToolMessage(content="ok", tool_call_id=f"{HANDOFF_TOOL}-1", name=HANDOFF_TOOL),
                               AIMessage(content="My own answer.")]
    config = _config("standard")
    graph = await graphs.coordinator(config)
    result = await graph.ainvoke({"messages": [HumanMessage(content="Why?")]}, config)
    assert len(world.calls["team"]) == 1 and result["final_answer"] == "My own answer."


@pytest.mark.asyncio
async def test_an_exhausted_budget_hands_the_request_over(world):
    limit = SINGLE_AGENT_CALL_LIMIT
    world.replies["single"] = [AIMessage(content=f"Model call limits exceeded: run limit ({limit}/{limit})")]
    config = _config("auto")
    graph = await graphs.coordinator(config)
    await graph.ainvoke({"messages": [HumanMessage(content="Plot it")]}, config)
    assert len(world.calls["team"]) == 1
    assert f"used all {limit} model calls" in world.calls["handoffs"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "standard"])
async def test_the_single_agent_gets_the_handoff_only_in_auto_mode(monkeypatch, mode):
    captured = {}

    async def fake_build(_config, role, *, run=None, middleware=None, suffix="", routing="", **_kwargs):
        captured.update(role=role, run=run, middleware=middleware, suffix=suffix, routing=routing)
        return "graph"

    monkeypatch.setattr(graphs, "build", fake_build)
    run = AgentRun(workspace_id="ws", task_id="task", request_id="r", thread_id="single-agent-x",
                   server_run_id="s", role=SINGLE_AGENT)
    assert await graphs._single_agent(_config(mode), run) == "graph"
    kinds = [type(item) for item in captured["middleware"]]
    budget = next(item for item in captured["middleware"] if isinstance(item, QuickCallBudgetMiddleware))
    assert captured["role"] == SINGLE_AGENT and captured["run"] is run
    assert budget.minutes == SINGLE_AGENT_MINUTES and budget.figures == FIGURE_MINUTES
    assert HELPER_POLICY in captured["suffix"]
    assert HANDOFF_POLICY not in captured["suffix"]
    assert kinds[-1] is ToolCallRepairMiddleware and HelperMiddleware in kinds
    if mode == "auto":
        assert kinds[0] is HandoffMiddleware and captured["routing"] == HANDOFF_POLICY
        assert budget.last_call == LAST_CALL_HANDOFF and budget.last_tools == {HANDOFF_TOOL}
    else:
        assert HandoffMiddleware not in kinds and not captured["routing"]
        assert budget.last_call == LAST_CALL and not budget.last_tools


# --- the agent loop ---------------------------------------------------------------------------------

def test_the_single_agents_run_ends_right_after_it_hands_over():
    model = _ProbeModel(responses=[
        _call(HANDOFF_TOOL, {"reason": "已转交研究团队。", "progress": "Nothing yet."}),
        AIMessage(content="This call must not happen.")])
    agent = create_agent(model=model, tools=[], system_prompt="base", middleware=[
        HandoffMiddleware(), QuickCallBudgetMiddleware(5, last_call=LAST_CALL_HANDOFF,
                                                       last_tools=frozenset({HANDOFF_TOOL}))])
    result = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="Why?")]}))
    assert len(model.seen_messages) == 1
    assert isinstance(result["messages"][-1], ToolMessage) and result["messages"][-1].name == HANDOFF_TOOL
    assert handoff_request(result["messages"]) == {"reason": "已转交研究团队。", "progress": "Nothing yet."}


@pytest.mark.parametrize("handoff", [False, True])
def test_the_last_call_of_the_budget_may_only_answer_or_hand_over(handoff):
    runs = []

    @tool
    def execute(value: int) -> str:
        """Run one probe step."""
        runs.append(value)
        return str(value)

    model = _ProbeModel(responses=[_call("execute", {"value": 1}, "e1"), _call("execute", {"value": 2}, "e2"),
                                   AIMessage(content="Final answer.")])
    middleware = [QuickCallBudgetMiddleware(3, last_call=LAST_CALL_HANDOFF if handoff else LAST_CALL,
                                            last_tools=frozenset({HANDOFF_TOOL}) if handoff else frozenset())]
    agent = create_agent(model=model, tools=[execute], system_prompt="base",
                         middleware=[HandoffMiddleware(), *middleware] if handoff else middleware)
    result = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="Plot it")]}))
    assert result["messages"][-1].text == "Final answer." and runs == [1, 2]
    assert "execute" in model.bound_tool_names[0] and "execute" in model.bound_tool_names[1]
    # With no tool left, the model is called without binding any.
    assert model.bound_tool_names[2:] == ([(HANDOFF_TOOL,)] if handoff else [])
    last_system = next(m.text for m in model.seen_messages[2] if isinstance(m, SystemMessage))
    assert (LAST_CALL_HANDOFF if handoff else LAST_CALL) in last_system
    assert model.seen_messages[1][-1].text.endswith("[Budget: 2 model calls left, this one included; "
                                                    "the last has no tools.]")


def test_markup_on_the_tool_free_last_call_is_asked_again_for_text():
    model = _ProbeModel(responses=[AIMessage(content="<｜tool▁calls▁begin｜>"), AIMessage(content="Plain answer.")])
    agent = create_agent(model=model, tools=[], system_prompt="base",
                         middleware=[QuickCallBudgetMiddleware(1, last_call=LAST_CALL)])
    result = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="Plot it")]}))
    assert result["messages"][-1].text == "Plain answer."
    assert model.seen_messages[1][-1].text == PLAIN_TEXT_RETRY


def test_the_requests_time_brings_the_figures_forward_and_ends_it_with_an_answer():
    # A paper request of 2026-11-02 computed for 2 h 27 min without drawing a figure and was cancelled with
    # nothing delivered. Each tool result now shows the minutes used, from 45 on with the figures first; code
    # started before 120 runs to its end, and the call after it may only answer, without handing over.
    runs = []

    @tool
    def execute(value: int) -> str:
        """Run one probe step."""
        runs.append(value)
        return str(value)

    minutes = iter([0, 10, 50, 119, 125])
    model = _ProbeModel(responses=[*(_call("execute", {"value": n}, f"e{n}") for n in (1, 2, 3, 4)),
                                   AIMessage(content="Final answer.")])
    budget = QuickCallBudgetMiddleware(SINGLE_AGENT_CALL_LIMIT, last_call=LAST_CALL_HANDOFF,
                                       last_tools=frozenset({HANDOFF_TOOL}), minutes=SINGLE_AGENT_MINUTES,
                                       figures=FIGURE_MINUTES, clock=lambda: 60 * next(minutes))
    agent = create_agent(model=model, tools=[execute], system_prompt="base",
                         middleware=[HandoffMiddleware(), budget])
    result = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="Apply the paper to my data")]}))
    assert result["messages"][-1].text == "Final answer." and runs == [1, 2, 3, 4]
    assert model.seen_messages[1][-1].text.endswith("[Time: 10 of 120 minutes used.]")
    figures_first = ("; past 45, deliver each figure your saved results allow, if not done yet, before more "
                     "long computation.]")
    assert model.seen_messages[2][-1].text.endswith("[Time: 50 of 120 minutes used" + figures_first)
    assert model.seen_messages[3][-1].text.endswith("[Time: 119 of 120 minutes used" + figures_first)
    # The call after 120 minutes binds no tool, not even the handoff, and its instructions end with LAST_CALL.
    assert len(model.bound_tool_names) == 4
    last_system = next(m.text for m in model.seen_messages[4] if isinstance(m, SystemMessage))
    assert last_system.endswith(LAST_CALL)
    # The notes go with each call only; the saved conversation keeps the tool results as they were.
    assert [m.text for m in result["messages"] if isinstance(m, ToolMessage)] == ["1", "2", "3", "4"]
    for part in ("a request has 120 minutes", "After 45 minutes, before you start more long computation",
                 "under OCEAN_OUTPUT_DIR under its final name", "code still running then is not stopped"):
        assert part in time_budget_sentence()


# --- helpers ----------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_at_most_three_helpers_work_at_once_and_a_failure_comes_back_as_text():
    running, most = 0, 0

    async def run_helper(part):
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.02)
        running -= 1
        if part == "fail":
            raise RuntimeError("provider down")
        return f"done: {part}"

    assign = HelperMiddleware(run_helper).tools[0]
    assert assign.name == HELPER_TOOL
    replies = await asyncio.gather(*(assign.ainvoke({"task": part}) for part in ["a", "b", "c", "d", "fail"]))
    assert most == 3
    assert replies[:4] == ["done: a", "done: b", "done: c", "done: d"]
    assert replies[4].startswith("The helper failed (RuntimeError: provider down)")


@pytest.mark.asyncio
async def test_a_helper_works_in_its_own_folder_and_kernel_and_is_metered_by_itself(monkeypatch, tmp_path):
    built, closed = [], []

    class Helper:
        async def ainvoke(self, state):
            assert INSIDE_EXPERT.get() is True  # the single agent's meter leaves these calls alone
            return {"messages": [*state["messages"], _call("execute", {}), AIMessage(content="SST mean 28.1 °C.")]}

    async def fake_build(_config, role, *, run=None, middleware=None, **_kwargs):
        built.append((role, run, [type(item) for item in middleware]))
        return Helper()

    async def close_kernel(run):
        closed.append(run.thread_id)

    monkeypatch.setattr(graphs, "build", fake_build)
    monkeypatch.setattr(graphs, "_close_kernel", close_kernel)
    monkeypatch.setattr(graphs, "host", lambda: SimpleNamespace(task_workspace_projector=SimpleNamespace(
        expert_session_root=lambda task_id, key: tmp_path / key)))
    reply = await graphs._run_helper(_config("auto"), "Mean SST in August")
    other = await graphs._run_helper(_config("auto"), "Mean SSS in August")
    (role, run, kinds), (_role, other_run, _kinds) = built
    assert role == HELPER and run.thread_id.startswith("helper-") and run.thread_id != other_run.thread_id
    assert HandoffMiddleware not in kinds and HelperMiddleware not in kinds  # no handoff, no helpers of its own
    assert QuickCallBudgetMiddleware in kinds
    assert reply.startswith("SST mean 28.1 °C.") and str(tmp_path / run.thread_id) in reply
    assert closed == [run.thread_id, other_run.thread_id] and INSIDE_EXPERT.get() is False
    assert other.startswith("SST mean")


@pytest.mark.asyncio
async def test_the_single_agents_meter_leaves_a_helpers_calls_to_the_helpers_meter():
    recorded = []
    store = SimpleNamespace(record_model_call=lambda call: recorded.append(dict(call)))
    config = _config("auto")
    run = AgentRun(workspace_id="ws", task_id="task", request_id="request", thread_id="single-agent-x",
                   server_run_id="s", role=SINGLE_AGENT)
    single = CallMeter(store, config, SINGLE_AGENT, run, outer=True)
    helper = CallMeter(store, config, HELPER, run)
    token = INSIDE_EXPERT.set(True)
    try:
        await single.on_chat_model_start({}, [[HumanMessage(content="x")]], run_id="call-1")
        await helper.on_chat_model_start({}, [[HumanMessage(content="x")]], run_id="call-1")
    finally:
        INSIDE_EXPERT.reset(token)
    await single.on_chat_model_start({}, [[HumanMessage(content="x")]], run_id="call-2")
    assert [(call["role"], call["call_id"]) for call in recorded] == [(HELPER, "call-1"), (SINGLE_AGENT, "call-2")]


# --- the desktop backend ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_desktop_shows_the_team_only_once_it_takes_a_request_over(tmp_path, monkeypatch):
    store = RequestStore(tmp_path / "state.sqlite3")
    router = OceanRequestRouter(store=store, event_bus=EventBus())
    emitted, transcript = [], []

    async def send(event):
        emitted.append(event)

    async def record(client, request, *, role, text, **_kwargs):
        transcript.append((request.request_id, role, text))

    async def noop(*args, **kwargs):
        pass

    client = BackendClient(transport="stdio", expected_client_kind="desktop", sender=send, client_id="client",
                           session_id="session", workspace_id="ws", principal="user:local:desktop")
    monkeypatch.setattr(router, "_append_transcript_item", record)
    monkeypatch.setattr(router, "_emit_agent_stream_event", noop)
    monkeypatch.setattr(router, "_broadcast_committed_terminal", lambda client, terminal: send(terminal))

    def submit(request_id, mode):
        request = parse_request({
            "protocol_version": 2, "expected_workspace_revision": 0, "request_id": request_id,
            "type": "session.submit", "payload": {"text": "q", "workflow_mode": mode},
            "context": {"client_id": "client", "session_id": "session", "workspace_id": "ws"}})
        store.reserve(request, principal=client.principal)
        store.mark_in_progress(request_id)
        return request

    def answer(request_id):
        return AssistantTurnComplete(message=ConversationMessage(role="assistant", content=[TextBlock(text="A.")]),
                                     usage=UsageSnapshot(input_tokens=1, output_tokens=1), turn_id="turn",
                                     request_id=request_id)

    class Engine:
        def __init__(self, events):
            self.events = events

        async def submit_message(self, text, *, request_id):
            for event in self.events:
                yield event

    async def execute(request, events):
        session = SimpleNamespace(workspace_id="ws", task_id=None, runtime=SimpleNamespace(
            engine=Engine(events), provider_id="fixture", model_id="fixture"))
        router._agent_request_clients[request.request_id] = client
        await router._execute_agent_request(client=client, request=request, agent_session=session,
                                            submitted_text="q", visible_text="q")
        return emitted[-1].payload.result["team_provenance"]["workflow"]

    try:
        alone = submit("req_alone", "auto")
        assert await execute(alone, [answer("req_alone")]) == "single_agent"
        handed = submit("req_handed", "auto")
        reason = "这个问题需要研究团队比较几种机制。"
        assert await execute(handed, [
            ToolExecutionStarted(tool_name=HANDOFF_TOOL, tool_input={"reason": reason}, tool_call_id="h"),
            ToolExecutionCompleted(tool_name=HANDOFF_TOOL, output="ok", tool_call_id="h"),
            answer("req_handed")]) == "research_team"
        assert ("req_handed", "system", reason) in transcript
        assert not any(item[0] == "req_alone" and item[1] == "system" for item in transcript)
        snapshots = [event for event in emitted if event.type == "team.snapshot"]
        assert snapshots and {event.request_id for event in snapshots} == {"req_handed"}
        direct = submit("req_direct", "research")

        restarted = OceanRequestRouter(store=store, event_bus=EventBus())  # nothing kept in memory
        assert restarted._uses_team("req_handed") and restarted._uses_team("req_direct")
        assert not restarted._uses_team("req_alone")
        assert direct.payload.workflow_mode == "research"
    finally:
        store.close()

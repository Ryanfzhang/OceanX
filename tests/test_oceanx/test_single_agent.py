"""The single agent works on a request first; the research team takes over an open research problem."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
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
from oceanx.agent_tools import ToolExecutionContext
from oceanx.backend.events import BackendClient, EventBus
from oceanx.backend.router import OceanRequestRouter
from oceanx.backend.store import RequestStore
from oceanx.batch import QueryCase
from oceanx.expert_execution import STANDARD_MODE_CODE_SECONDS
from oceanx.protocol.v2.models import parse_request
from oceanx.research import graphs
from oceanx.research.metering import INSIDE_EXPERT, CallMeter
from oceanx.research.routing import (
    AGENT_TAG,
    HANDOFF_POLICY,
    HANDOFF_TOOL,
    HELPER,
    HELPER_POLICY,
    HELPER_TOOL,
    LAST_CALL,
    LAST_CALL_HANDOFF,
    PLAIN_TEXT_RETRY,
    SINGLE_AGENT,
    SINGLE_AGENT_CALL_LIMIT,
    TEAM,
    HandoffMiddleware,
    HelperMiddleware,
    QuickCallBudgetMiddleware,
    handoff_request,
    seen_by,
    tagged,
    team_config,
    workflow_mode,
)
from oceanx.research.services import AgentRun
from oceanx.research.tool_calls import ToolCallRepairMiddleware
from oceanx.tools import OceanExpertRunCodeInput, OceanExpertRunCodeTool, OceanToolServices


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
    assert HANDOFF_TOOL in handoff and "asks why" in handoff and "however many parts" in handoff
    # Three rules, the first that fits decides: a paper's reproduction stays with one agent, which holds
    # every result its figures combine, even where the paper explains a mechanism; then any part that is an
    # open research problem sends the request to the team, even beside listed data steps and figures (the
    # Mangkhut request of 2026-10-26 asked whether mixing or upwelling cooled the sea and listed five
    # downloads, a map and a section, and the agent kept it); then everything else is the agent's.
    reproduce = handoff.index("1. A request to reproduce or test the analysis of a paper is yours")
    team = handoff.index("2. A request any part of which is an open research problem goes to the research team")
    rest = handoff.index("3. Everything else is yours, however many parts it has")
    assert reproduce < team < rest and "The first of these rules that fits decides" in handoff
    assert "even where the paper explains why something happens" in handoff
    assert ("even when the request also lists the data to use or download and the maps, sections or tables to "
            "make") in handoff and "whether mixing or upwelling did it" in handoff
    assert "when unsure" not in handoff  # it sent mixed requests to the agent
    reproduction = "Reproducing or testing a paper's analysis is not bounded this way"
    assert reproduction in " ".join(graphs.bounded_work_policy(False).split())
    assert HELPER_TOOL in helpers and "up to 3 helpers" in helpers
    interactive, static = graphs.bounded_work_policy(False), graphs.bounded_work_policy(True)
    assert "finish line" in interactive and f"{STANDARD_MODE_CODE_SECONDS} s" in interactive
    assert ".preview.png" in interactive and "the image" in static
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
    single = await build_ocean_single_agent_runtime(services=services)
    helper = await build_ocean_single_agent_runtime(services=services, helper=True)
    # In auto mode the rule for handing over comes before the instructions on how to work.
    routed = (await build_ocean_single_agent_runtime(services=services, routing=HANDOFF_POLICY)).system_prompt
    assert routed.startswith(OCEAN_RESEARCH_PARTNER_SYSTEM_PROMPT)
    assert routed.index("# First: yours or the research team's") < routed.index(OCEAN_SINGLE_AGENT_PROMPT)
    assert "research team" not in single.system_prompt and "research team" not in helper.system_prompt
    assert "report.md" not in single.system_prompt and "report.md" not in helper.system_prompt
    assert "in your answer" in single.system_prompt and "in your reply" in helper.system_prompt
    assert single.system_prompt.startswith(OCEAN_RESEARCH_PARTNER_SYSTEM_PROMPT)
    assert OCEAN_SINGLE_AGENT_PROMPT in single.system_prompt
    assert helper.system_prompt.startswith(OCEAN_HELPER_PROMPT)
    names = {tool.name for tool in single.profile.tool_registry.as_langchain_tools(
        cwd=Path("."), operation_id_factory=lambda *args: "op")}
    assert {"web_search", "jina_reader"} <= names


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


def _run_code_tool(limit):
    seen = {}

    class Service:
        async def run_python(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop after capturing the call")

    code_tool = OceanExpertRunCodeTool(OceanToolServices(
        workspace_id="ws", provider_id="p", store=SimpleNamespace(), task_id="t",
        agent_thread_id="a", server_run_id="r", expert_code_execution=Service(),
        code_time_limit_seconds=limit))
    try:
        asyncio.run(code_tool.execute(OceanExpertRunCodeInput(purpose="p", code="1"),
                                      ToolExecutionContext(cwd=Path("."))))
    except RuntimeError:
        pass
    return seen


def test_code_runs_of_the_single_agent_stop_sooner_than_the_teams():
    assert _run_code_tool(STANDARD_MODE_CODE_SECONDS)["_timeout"] == STANDARD_MODE_CODE_SECONDS
    assert _run_code_tool(None)["_timeout"] is None  # research: the service default (300 s)


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
    assert HELPER_POLICY in captured["suffix"]
    assert kinds[-1] is ToolCallRepairMiddleware and HelperMiddleware in kinds
    assert HANDOFF_POLICY not in captured["suffix"]  # the rule is not left to the end of the prompt
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

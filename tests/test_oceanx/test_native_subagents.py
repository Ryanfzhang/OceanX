"""Native synchronous DeepAgents delegation regressions."""
from types import SimpleNamespace
from pathlib import Path
from typing import Any

import asyncio
import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langchain_core.tools import tool
from pydantic import Field

from oceanx.backend.router import OceanRequestRouter
from oceanx.deep_runtime import _tool_output
from oceanx.research.services import (
    AgentRun, ResearchServices, expert_agent_key, expert_result_preview,
    format_expert_receipt, parse_expert_receipt, result_bindings,
)
from oceanx.research.gateway import server_error_message
from oceanx.research.graphs import (
    COORDINATOR_FILESYSTEM_TOOLS,
    COORDINATOR_VISUAL_DELIVERY_POLICY,
    EXPERT_FINAL_CALL,
    EXPERT_MODEL_CALL_LIMIT,
    EXPERT_REPORT_CHECKPOINT_START,
    EXPERT_WIND_DOWN_START,
    MAX_PARALLEL_EXPERTS,
    MAX_PARALLEL_SEARCH_EXPERTS,
    REPORT_CHECKPOINT_REFUSAL,
    WIND_DOWN_REFUSAL,
    ExpertCallBudgetMiddleware,
    _coordinator_agent,
    _expert_call_limit,
    _expert_call_phases,
    _expert_slots,
    _missing_report,
    _parallel_expert_limit,
    _parallel_search_expert_limit,
    _requested_parallel_experts,
    _search_expert_slots,
    _wind_down_request,
)
from oceanx.research.background_experts import BackgroundDelegationMiddleware, RunningExperts
from oceanx.research.tool_calls import ToolCallRepairMiddleware
from oceanx.team.profiles import AGENT_PROFILES, get_agent_profile


def _config(question=""):
    del question
    return {"configurable": {
        "workspace_id": "ws", "task_id": "task", "request_id": "request",
        "thread_id": "coordinator", "ls_agent_type": "subagent",
    }}


def test_removed_roles_are_not_available():
    ids = {profile.profile_id for profile in AGENT_PROFILES}
    assert "data_reproducibility_expert" not in ids
    assert "visualization_communication_expert" not in ids
    with pytest.raises(ValueError):
        get_agent_profile("visualization_communication_expert")


@pytest.mark.asyncio
async def test_standard_workflow_keeps_native_experts_without_a_research_tree(
    monkeypatch, tmp_path
):
    from oceanx.research import graphs

    config = _config()
    config["configurable"]["request_options"] = {"workflow_mode": "standard"}
    captured: dict[str, Any] = {}

    async def fake_expert(_config, profile_id):
        return f"runnable:{profile_id}"

    async def fake_build(_config, role, *, subagents=None, suffix="", middleware=None, **_kwargs):
        captured.update(role=role, subagents=subagents, suffix=suffix, middleware=middleware)
        return "graph"

    monkeypatch.setattr(graphs, "expert", fake_expert)
    monkeypatch.setattr(graphs, "build", fake_build)
    monkeypatch.setattr(graphs, "coordinator_report_path", lambda _config: tmp_path / "report.md")

    experts = RunningExperts()
    assert await _coordinator_agent(config, experts) == "graph"
    background, repair = captured["middleware"]
    assert isinstance(background, BackgroundDelegationMiddleware) and background.experts is experts
    assert isinstance(repair, ToolCallRepairMiddleware)  # a stray bracket must not end a standard run either
    assert "Experts work in the background" in captured["suffix"]
    assert "Synthesize only after every Expert has returned" in captured["suffix"]
    assert captured["role"] == "coordinator"
    assert {item["name"] for item in captured["subagents"]} == {
        profile.profile_id for profile in AGENT_PROFILES
    }
    assert "# Standard workflow" in captured["suffix"]
    assert "Research mode is off" in captured["suffix"]
    assert "This does not disable the team" in captured["suffix"]
    assert "Do not create or update a research tree" in captured["suffix"]
    assert COORDINATOR_VISUAL_DELIVERY_POLICY in captured["suffix"]
    assert "one and only one follow-up task call" in captured["suffix"]
    assert "A .preview.png is only the fallback" in captured["suffix"]
    assert "execute" not in COORDINATOR_FILESYSTEM_TOOLS


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow_mode", ["standard", "research"])
@pytest.mark.parametrize("figure_delivery", ["interactive", "static"])
async def test_visual_follow_up_is_only_for_a_visual_the_user_asked_for(
    monkeypatch, tmp_path, workflow_mode, figure_delivery
):
    from oceanx.research import graphs

    config = _config()
    config["configurable"]["request_options"] = {"workflow_mode": workflow_mode}
    captured = {}

    async def fake_expert(_config, profile_id):
        return f"runnable:{profile_id}"

    async def fake_build(_config, role, *, suffix="", **_kwargs):
        captured["suffix"] = suffix
        return "graph"

    monkeypatch.setattr(graphs, "expert", fake_expert)
    monkeypatch.setattr(graphs, "build", fake_build)
    monkeypatch.setattr(graphs, "coordinator_report_path", lambda _config: tmp_path / "report.md")
    monkeypatch.setattr(graphs, "research_tree",
                        lambda _task_id: SimpleNamespace(policy=SimpleNamespace(guidance="")))
    monkeypatch.delenv(graphs.RESEARCH_BUDGET_ENV, raising=False)
    monkeypatch.setenv("OCEANX_FIGURE_DELIVERY", figure_delivery)

    assert await _coordinator_agent(config) == "graph"
    prompt = " ".join(captured["suffix"].split())
    # The qualifying visual is part of the rule itself, and "the user explicitly asked for" covers a
    # request made in a later message of a desktop conversation as well as the first one.
    assert ("omitted a visual that the user explicitly asked for, you may make one and only one "
            "follow-up task call") in prompt
    assert "A visual that you added yourself in an Expert assignment does not qualify." in prompt
    assert "Never make a second visual-delivery follow-up" in prompt
    assert "original user question" not in prompt
    # Each delivery mode names its own kind of figure, never the other's.
    static = figure_delivery == "static"
    assert ("Saved figures" in prompt) is static
    assert ("Published results" in prompt) is not static


def test_each_tree_node_has_its_own_workspace_and_another_attempt_reuses_it():
    parent = AgentRun.from_config(_config(), "ocean_process_expert", question="B1: establish anomaly")
    child = AgentRun.from_config(_config(), "ocean_process_expert", question="B1.2: test transport")
    again = AgentRun.from_config(_config(), "ocean_process_expert",
                                 question="B1.2: publish the transport map from the saved evidence")
    sibling = AgentRun.from_config(_config(), "ocean_process_expert", question="B2: test mixing")
    assert len({parent.thread_id, child.thread_id, sibling.thread_id}) == 3
    assert again.thread_id == child.thread_id
    assert parent.agent_run_id == parent.thread_id


def test_the_tree_binding_names_the_node_when_the_question_names_its_parent():
    from oceanx.research import delegation

    question = "Continue B1: test transport"
    token = delegation._CURRENT.set(delegation.resolve_delegation(
        {"node_id": "B1.2", "description": question}))
    try:
        run = AgentRun.from_config(_config(), "ocean_process_expert", question=question)
    finally:
        delegation._CURRENT.reset(token)
    assert run.node_id == "B1.2"
    assert run.thread_id == expert_agent_key("task", "ocean_process_expert", "B1.2: transport")
    assert run.thread_id != expert_agent_key("task", "ocean_process_expert", question)
    card = _child("call-1", question)
    card["node_id"] = "B1.2"
    assert _team([card]).agents[1].agent_id == run.thread_id


def test_parent_and_child_nodes_keep_reports_in_their_own_folders(tmp_path):
    def root(_task_id, agent_key):
        path = tmp_path / "agents" / agent_key
        (path / "outputs").mkdir(parents=True, exist_ok=True)
        return path

    services = ResearchServices(SimpleNamespace(
        task_workspace_projector=SimpleNamespace(expert_session_root=root),
        expert_code_execution=None,
    ))
    parent = AgentRun.from_config(
        _config(), "ocean_process_expert", question="Question (B1): establish anomaly"
    )
    first_child = AgentRun.from_config(
        _config(), "ocean_process_expert", question="Question (B1.1): test depth"
    )
    second_child = AgentRun.from_config(
        _config(), "ocean_process_expert", question="Question (B1.2): test transport"
    )
    assert len({parent.thread_id, first_child.thread_id, second_child.thread_id}) == 3
    paths = {services.report_path(run) for run in (parent, first_child, second_child)}
    assert len(paths) == 3
    assert services.report_path(parent).as_posix().endswith(
        f"/{parent.thread_id}/reports/B1/report.md")
    assert services.report_path(first_child).as_posix().endswith(
        f"/{first_child.thread_id}/reports/B1.1/report.md")


def test_agent_report_collection_does_not_judge_report_content(tmp_path):
    def root(_task_id, agent_key):
        path = tmp_path / "agents" / agent_key
        (path / "outputs").mkdir(parents=True, exist_ok=True)
        return path

    services = ResearchServices(SimpleNamespace(
        task_workspace_projector=SimpleNamespace(expert_session_root=root),
        expert_code_execution=None,
    ))
    run = AgentRun("ws", "task", "request", "ocean-process-a1b2", "server", "physics")
    text, path = services.collect_report(run, materialize_text="# Finding\nNo summary")
    assert path is not None and text == "# Finding\nNo summary"
    text, path = services.collect_report(
        run,
        materialize_text="## Summary\nThe answer is evidence-limited.\n\n## Evidence\nDetails",
    )
    assert path is not None
    assert text.startswith("## Summary")


def test_each_attempt_keeps_the_report_it_delivered(tmp_path):
    def root(_task_id, agent_key):
        return tmp_path / "agents" / agent_key

    services = ResearchServices(SimpleNamespace(
        task_workspace_projector=SimpleNamespace(expert_session_root=root),
        expert_code_execution=None,
    ))
    first = AgentRun("ws", "task", "request", "ocean-process-a1b2", "server", "physics",
                     question="Question (node B1.2): depth of the layer", node_id="B1.2", attempt_id="a1")
    second = AgentRun("ws", "task", "request", "ocean-process-a1b2", "server", "physics",
                      question="Question (node B1.2): depth of the layer", node_id="B1.2", attempt_id="a2")
    services.collect_report(first, materialize_text="## Summary\nFirst answer.")
    text, path = services.collect_report(second, materialize_text="## Summary\nRevised answer.")
    # report.md holds the latest answer; the earlier one is still on disk, outside the reports folder.
    assert path.read_text() == text == "## Summary\nRevised answer."
    history = root("task", first.thread_id) / ".runtime" / "report-history" / "B1.2"
    assert {p.name: p.read_text() for p in history.iterdir()} == {
        "a1.md": "## Summary\nFirst answer.", "a2.md": "## Summary\nRevised answer."}
    assert [p.name for p in path.parent.iterdir()] == ["report.md"]


def test_result_bindings_keep_document_order_without_duplicates():
    text = (
        "First [ocean-process-abc/result1], then [statistics-def/result2], "
        "and reuse [ocean-process-abc/result1]."
    )
    assert result_bindings(text) == (
        "ocean-process-abc/result1",
        "statistics-def/result2",
    )


def test_saved_results_do_not_gate_agent_report_delivery(tmp_path):
    def root(_task_id, agent_key):
        path = tmp_path / "agents" / agent_key
        (path / "outputs").mkdir(parents=True, exist_ok=True)
        return path

    services = ResearchServices(SimpleNamespace(
        task_workspace_projector=SimpleNamespace(expert_session_root=root),
        expert_code_execution=None,
    ))
    run = AgentRun("ws", "task", "request", "ocean-process-a1b2", "server", "physics")
    agent_root = root("task", run.thread_id)
    (agent_root / "outputs" / "result1.nc").write_bytes(b"netcdf placeholder")
    text, path = services.collect_report(
        run,
        materialize_text="## Summary\nThe report remains deliverable without a binding.",
    )
    assert path is not None
    assert text.startswith("## Summary")


def test_native_transcript_projection_preserves_text_tools_and_results():
    messages = (
        {"id": "human", "type": "human", "content": "Inspect the map."},
        {"id": "assistant-tool", "type": "ai", "content": "", "tool_calls": [
            {"id": "call-1", "name": "read_file", "args": {"file_path": "/task/map.png"}},
        ]},
        {"id": "tool", "type": "tool", "content": "Loaded map.",
         "tool_call_id": "call-1", "status": "success"},
        {"id": "answer", "type": "ai", "content": "The anomaly is shallow."},
    )
    rendered = OceanRequestRouter._renderer_agent_messages(messages)
    assert rendered[0]["blocks"] == [{"type": "text", "text": "Inspect the map."}]
    assert rendered[1]["blocks"][0]["tool_name"] == "read_file"
    assert rendered[2]["blocks"][0]["type"] == "tool_result"
    assert rendered[3]["blocks"] == [{"type": "text", "text": "The anomaly is shallow."}]


def test_native_team_projection_uses_task_events_without_scheduler_state():
    router = object.__new__(OceanRequestRouter)
    router.task_workspace_projector = None
    router._native_task_activity = {}
    router.store = SimpleNamespace(get_request=lambda _request_id: SimpleNamespace(
        state="running", created_at="2026-09-17T10:00:00Z",
        updated_at="2026-09-17T10:03:00Z",
    ))
    children = [{
        "task_id": f"call-{index}", "agent_name": "ocean_process_expert",
        "request_id": "request-many", "status": "completed",
        "description": f"B{index + 1}: Question {index}",
        "created_at": "2026-09-17T10:01:00Z",
        "last_updated_at": "2026-09-17T10:02:00Z",
    } for index in range(13)]
    payload = asyncio.run(router._native_team_snapshot_payload(
        workspace_id="workspace", parent_request_id="request-many",
        task_id="task-many", revision=1, native_tasks=children,
    ))
    assert len(payload.agents) == 14
    assert all(agent.status == "completed" for agent in payload.agents[1:])
    assert {agent.agent_run_id for agent in payload.agents[1:]} == {
        f"call-{index}" for index in range(13)
    }


def test_agent_server_serialized_command_exposes_the_native_task_receipt():
    receipt = format_expert_receipt(
        "Result: answer\nEvidence and limitations: bounded evidence\nFurther analysis: None",
        Path("/task/report.md"),
    )
    output, failed = _tool_output({
        "graph": None,
        "update": {"messages": [ToolMessage(content=receipt, tool_call_id="task-1")]},
        "resume": None,
        "goto": [],
    })
    assert output == receipt
    assert failed is False
    summary, path = parse_expert_receipt(output)
    assert summary.startswith("Result: answer")
    assert path == "/task/report.md"


def test_expert_receipt_names_only_server_verified_desktop_bindings():
    receipt = format_expert_receipt(
        "Result: answer",
        Path("/task/report.md"),
        (("ocean-process-abc/current-map", "Current map"),),
    )
    assert "[ocean-process-abc/current-map] — Current map" in receipt
    assert "only these bracket bindings open in the desktop" in receipt
    summary, path = parse_expert_receipt(receipt)
    assert "Published results" in summary
    assert path == "/task/report.md"


def test_expert_receipt_makes_missing_published_result_explicit():
    receipt = format_expert_receipt("Result: route computed", Path("/task/report.md"))

    assert "Published results (only these bracket bindings open in the desktop):\n- None" in receipt


def test_incomplete_receipt_has_no_report_path():
    summary, path = parse_expert_receipt(
        "Execution status: incomplete\nResult: unavailable\n\nReport: None"
    )
    assert summary.startswith("Execution status: incomplete")
    assert path is None


def test_expert_receipt_preview_and_server_error_are_human_readable():
    summary = (
        "Result: Warm anomalies persist after local heating weakens.\n"
        "Evidence and limitations: One year of data.\n"
        "Further analysis: Test transport."
    )
    assert expert_result_preview(summary) == "Warm anomalies persist after local heating weakens."
    assert server_error_message({"error": "RuntimeError", "message": "The Expert stopped."}) == (
        "The Expert stopped."
    )


def test_expert_model_call_limit_is_native_and_per_run():
    assert EXPERT_MODEL_CALL_LIMIT == 60
    assert EXPERT_REPORT_CHECKPOINT_START == 30
    assert EXPERT_WIND_DOWN_START == 48
    assert EXPERT_FINAL_CALL == 59
    source = Path(__file__).parents[2] / "src/oceanx/research/graphs.py"
    text = source.read_text(encoding="utf-8")
    assert "ModelCallLimitMiddleware" in text
    assert "ExpertCallBudgetMiddleware(ModelCallLimitMiddleware)" in text
    assert "super().__init__(run_limit=EXPERT_MODEL_CALL_LIMIT" in text
    assert "middleware=[ExpertCallBudgetMiddleware(" in text
    assert 'graph.add_edge("author", "receipt")' in text
    assert "finish_report" not in text
    assert "report_phase" not in text
    assert "round_budget" not in text
    assert "ExpertRoundMiddleware" not in text


def test_expert_wind_down_filters_tools_inside_one_native_run():
    tools = [SimpleNamespace(name=name) for name in (
        "read_file", "write_file", "execute", "task", "web_search",
    )]

    def request(call_count):
        return ModelRequest(
            model=SimpleNamespace(),
            messages=[],
            tools=tools,
            state={"messages": [], "run_model_call_count": call_count},
            system_message=SystemMessage(content="base"),
        )

    analysis = request(47)
    assert _wind_down_request(analysis) is analysis

    wind_down = _wind_down_request(request(48))
    assert [tool.name for tool in wind_down.tools] == ["read_file", "write_file"]
    assert "Reserved report wind-down" in wind_down.system_message.text

    final = _wind_down_request(request(59))
    assert final.tools == []
    assert "Final delivery call" in final.system_message.text


def test_report_checkpoint_blocks_more_analysis_until_the_first_report_is_saved(tmp_path):
    tools = [SimpleNamespace(name=name) for name in ("read_file", "write_file", "execute")]
    report = tmp_path / "report.md"

    def request(call_count):
        return ModelRequest(
            model=SimpleNamespace(), messages=[], tools=tools,
            state={"messages": [], "run_model_call_count": call_count},
            system_message=SystemMessage(content="base"),
        )

    middleware = ExpertCallBudgetMiddleware(report_path=report)
    before = middleware._prepare_request(request(EXPERT_REPORT_CHECKPOINT_START - 1))
    assert before.tools == tools
    checkpoint = middleware._prepare_request(request(EXPERT_REPORT_CHECKPOINT_START))
    assert [tool.name for tool in checkpoint.tools] == ["read_file", "write_file"]
    assert "Required report checkpoint" in checkpoint.system_message.text
    report.write_text("## Summary\nResult: partial\n")
    resumed = middleware._prepare_request(request(EXPERT_REPORT_CHECKPOINT_START + 1))
    assert resumed.tools == tools


def test_report_checkpoint_refuses_only_calls_made_under_it(tmp_path):
    report = tmp_path / "reports" / "B1" / "report.md"
    ran = []

    @tool
    def execute(value: int) -> str:
        """Perform one probe research operation."""
        ran.append(value)
        return "ok"

    @tool
    def write_file(value: int) -> str:
        """Save the probe report."""
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("## Summary\npartial\n")
        return "saved"

    def call(name, index):
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": {"value": index}, "id": f"{name}-{index}", "type": "tool_call"}])

    # Calls 1-30 analyse. Call 31 is the first made under the checkpoint and ignores it (a model can
    # still print a tool the filter removed), call 32 saves the report, call 33 analyses again.
    responses = [call("execute", index) for index in range(1, 32)]
    responses += [call("write_file", 32), call("execute", 33), AIMessage(content="done")]
    model = _BudgetProbeModel(responses=responses)
    graph = create_agent(model=model, tools=[execute, write_file], system_prompt="base",
                         middleware=[ExpertCallBudgetMiddleware(report_path=report)])

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="research")]}))

    answers = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}
    assert answers["execute-30"].status == "success"  # asked while every tool was still offered
    assert (answers["execute-31"].status, answers["execute-31"].text) == (
        "error", REPORT_CHECKPOINT_REFUSAL)
    assert answers["write_file-32"].status == "success"
    assert answers["execute-33"].status == "success"  # the tools are back once the report exists
    assert len(ran) == 31
    assert model.bound_tool_names[29] == ("execute", "write_file")  # call 30
    assert model.bound_tool_names[30] == ("write_file",)  # call 31: file tools only
    assert model.bound_tool_names[32] == ("execute", "write_file")  # call 33


class _BudgetProbeModel(FakeMessagesListChatModel):
    bound_tool_names: list[tuple[str, ...]] = Field(default_factory=list)
    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **_kwargs: Any):
        self.bound_tool_names.append(tuple(
            tool.name if hasattr(tool, "name") else str(tool.get("name", ""))
            for tool in tools
        ))
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen_messages.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_compiled_agent_enters_wind_down_on_calls_49_through_60():
    research_calls = 0
    report_reads = 0

    @tool
    def execute(value: int) -> str:
        """Perform one probe research operation."""
        nonlocal research_calls
        research_calls += 1
        return str(value)

    @tool
    def read_file(value: int) -> str:
        """Perform one probe report-file read."""
        nonlocal report_reads
        report_reads += 1
        return str(value)

    def call(name: str, index: int) -> AIMessage:
        return AIMessage(content="", tool_calls=[{
            "name": name,
            "args": {"value": index},
            "id": f"{name}-{index}",
            "type": "tool_call",
        }])

    responses = [call("execute", index) for index in range(48)]
    responses.extend(call("read_file", index) for index in range(49, 60))
    responses.append(AIMessage(content="Final report delivery."))
    model = _BudgetProbeModel(responses=responses)
    graph = create_agent(
        model=model,
        tools=[execute, read_file],
        system_prompt="base",
        middleware=[ExpertCallBudgetMiddleware()],
    )

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="research")]}))

    assert result["messages"][-1].text == "Final report delivery."
    assert research_calls == 48
    assert report_reads == 11
    assert len(model.seen_messages) == 60
    for call_index, messages in enumerate(model.seen_messages, start=1):
        system = next(message.text for message in messages if isinstance(message, SystemMessage))
        if call_index <= 48:
            assert "Reserved report wind-down" not in system
        elif call_index < 60:
            assert "Reserved report wind-down" in system
        else:
            assert "Final delivery call" in system
    assert all("execute" in names for names in model.bound_tool_names[:48])
    assert all("execute" not in names for names in model.bound_tool_names[48:])


def test_wind_down_refuses_analysis_tools_the_model_still_requests():
    research_calls = 0

    @tool
    def execute(value: int) -> str:
        """Perform one probe research operation."""
        nonlocal research_calls
        research_calls += 1
        return str(value)

    @tool
    def write_file(value: int) -> str:
        """Write one probe report file."""
        return str(value)

    def call(name: str, index: int) -> AIMessage:
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": {"value": index}, "id": f"{name}-{index}", "type": "tool_call"}])

    # Calls 1-48 analyse, call 49 still asks for execute, calls 50-59 write the report.
    responses = [call("execute", index) for index in range(1, 50)]
    responses.extend(call("write_file", index) for index in range(50, 60))
    responses.append(AIMessage(content="Report written."))
    graph = create_agent(model=_BudgetProbeModel(responses=responses), tools=[execute, write_file],
                         system_prompt="base", middleware=[ExpertCallBudgetMiddleware()])

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="research")]}))

    assert research_calls == 48  # the tool from call 48 still ran; the one from call 49 did not
    refused = next(message for message in result["messages"]
                   if isinstance(message, ToolMessage) and message.tool_call_id == "execute-49")
    assert (refused.status, refused.text) == ("error", WIND_DOWN_REFUSAL)


def test_expert_runs_share_an_app_wide_parallel_limit():
    running = peak = 0

    async def expert_run():
        nonlocal running, peak
        async with _expert_slots():
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    async def scenario():
        assert _expert_slots() is _expert_slots()  # one pool for every task on the loop
        await asyncio.gather(*(expert_run() for _ in range(5)))

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))  # a slot that is never freed fails, not hangs
    assert peak == MAX_PARALLEL_EXPERTS
    peak = 0
    asyncio.run(asyncio.wait_for(scenario(), timeout=10))  # a new event loop gets a fresh pool
    assert peak == MAX_PARALLEL_EXPERTS
    source = (Path(__file__).parents[2] / "src/oceanx/research/graphs.py").read_text()
    assert "async with slot:" in source  # every Expert run goes through the pool


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["failed", "cancelled"])
async def test_a_coordinator_run_that_ends_early_leaves_no_expert_working(monkeypatch, tmp_path, ending):
    from oceanx.research import graphs

    stopped = []

    async def an_expert_that_never_returns():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.append("expert")
            raise

    class Agent:
        async def ainvoke(self, _state, config=None):
            self.experts.start({"id": "call", "args": {"description": "B1.1: q", "subagent_type": "x"}},
                               an_expert_that_never_returns())
            await asyncio.sleep(0)
            if ending == "failed":
                raise RuntimeError("provider failure")
            await asyncio.Event().wait()

    async def fake_agent(_config, experts):
        agent = Agent()
        agent.experts = experts
        return agent

    monkeypatch.setattr(graphs, "_coordinator_agent", fake_agent)
    monkeypatch.setattr(graphs, "coordinator_report_path", lambda _config: tmp_path / "report.md")
    graph = await graphs.coordinator(_config())
    run = asyncio.ensure_future(graph.ainvoke({"messages": [HumanMessage(content="q")]}, _config()))
    if ending == "cancelled":
        await asyncio.sleep(0.05)
        run.cancel()
    with pytest.raises((RuntimeError, asyncio.CancelledError)):
        await asyncio.wait_for(run, timeout=10)

    assert stopped == ["expert"]


def test_the_slot_limit_can_change_while_experts_wait():
    order = []

    async def expert(name, release):
        async with _expert_slots():
            order.append(name)
            await release.wait()

    async def scenario():
        slots = _expert_slots(1)
        assert slots.limit == 1
        release = asyncio.Event()
        runs = [asyncio.ensure_future(expert(name, release)) for name in "abc"]
        await asyncio.sleep(0.01)
        assert order == ["a"] and slots.locked()  # one slot: the others wait
        _expert_slots(3)  # the desktop's setting was raised
        await asyncio.sleep(0.01)
        assert order == ["a", "b", "c"]  # the waiting Experts started without anyone finishing
        release.set()
        await asyncio.gather(*runs)
        assert slots.active == 0 and _expert_slots() is slots and slots.limit == 3  # no value keeps the limit

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))  # a slot that never frees fails, not hangs


def test_a_lower_slot_limit_applies_to_the_experts_that_start_next():
    order = []

    async def expert(name, release):
        async with _expert_slots():
            order.append(name)
            await release.wait()

    async def scenario():
        slots = _expert_slots(2)
        first = asyncio.Event()
        runs = [asyncio.ensure_future(expert(name, first)) for name in "ab"]
        await asyncio.sleep(0.01)
        _expert_slots(1)  # lowered while two are working: they finish, the next one waits for both
        later = asyncio.Event()
        runs.append(asyncio.ensure_future(expert("c", later)))
        await asyncio.sleep(0.01)
        assert order == ["a", "b"] and slots.active == 2
        first.set()
        await asyncio.sleep(0.01)
        assert order == ["a", "b", "c"] and slots.active == 1
        later.set()
        await asyncio.gather(*runs)

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


@pytest.mark.parametrize("options, expected", [
    ({}, None), ({"max_parallel_experts": 3}, 3), ({"max_parallel_experts": None}, None),
    ({"max_parallel_experts": 0}, None), ({"max_parallel_experts": "3"}, None),
    ({"max_parallel_experts": True}, None), ({"max_parallel_experts": 50}, 8),
])
def test_the_request_may_set_how_many_data_experts_work_at_once(options, expected):
    config = _config()
    config["configurable"]["request_options"] = options
    assert _requested_parallel_experts(config) == expected
    assert _requested_parallel_experts(_config()) is None  # no options at all: the environment's default


def test_search_experts_have_one_separate_slot_from_data_experts():
    async def scenario():
        assert _search_expert_slots() is _search_expert_slots()
        assert _search_expert_slots() is not _expert_slots()

    asyncio.run(scenario())
    assert MAX_PARALLEL_SEARCH_EXPERTS == 1


def test_parallel_expert_limit_setting(monkeypatch):
    monkeypatch.delenv("OCEANX_MAX_PARALLEL_EXPERTS", raising=False)
    assert _parallel_expert_limit() == 2
    for value, expected in (("3", 3), ("0", 1), ("many", 2)):
        monkeypatch.setenv("OCEANX_MAX_PARALLEL_EXPERTS", value)
        assert _parallel_expert_limit() == expected
    monkeypatch.delenv("OCEANX_MAX_PARALLEL_SEARCH_EXPERTS", raising=False)
    assert _parallel_search_expert_limit() == 1
    monkeypatch.setenv("OCEANX_MAX_PARALLEL_SEARCH_EXPERTS", "2")
    assert _parallel_search_expert_limit() == 2


def test_expert_call_limit_is_set_by_the_environment_and_never_below_ten(monkeypatch):
    monkeypatch.delenv("OCEANX_EXPERT_CALL_LIMIT", raising=False)
    assert _expert_call_limit() == 60  # the desktop's limit
    for value, expected in (("40", 40), ("3", 10), ("many", 60), ("", 60)):
        monkeypatch.setenv("OCEANX_EXPERT_CALL_LIMIT", value)
        assert _expert_call_limit() == expected


def test_report_checkpoint_and_wind_down_keep_their_place_in_the_budget():
    assert _expert_call_phases(60) == (30, 48, 59)
    assert (EXPERT_REPORT_CHECKPOINT_START, EXPERT_WIND_DOWN_START, EXPERT_FINAL_CALL) == (
        _expert_call_phases(EXPERT_MODEL_CALL_LIMIT))
    assert _expert_call_phases(40) == (20, 32, 39)
    for limit in range(10, 121):
        checkpoint, wind_down, final = _expert_call_phases(limit)
        assert 0 < checkpoint < wind_down < final == limit - 1


def test_a_lower_call_limit_moves_the_wind_down_and_the_final_call_with_it(monkeypatch):
    from oceanx.research import graphs

    checkpoint, wind_down, final = _expert_call_phases(40)
    for name, value in (("EXPERT_MODEL_CALL_LIMIT", 40), ("EXPERT_REPORT_CHECKPOINT_START", checkpoint),
                        ("EXPERT_WIND_DOWN_START", wind_down), ("EXPERT_FINAL_CALL", final)):
        monkeypatch.setattr(graphs, name, value)
    research_calls = report_reads = 0

    @tool
    def execute(value: int) -> str:
        """Perform one probe research operation."""
        nonlocal research_calls
        research_calls += 1
        return str(value)

    @tool
    def read_file(value: int) -> str:
        """Perform one probe report-file read."""
        nonlocal report_reads
        report_reads += 1
        return str(value)

    def call(name: str, index: int) -> AIMessage:
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": {"value": index}, "id": f"{name}-{index}", "type": "tool_call"}])

    # Calls 1-32 analyse, calls 33-39 are the wind-down, call 40 is the tool-free delivery call.
    responses = [call("execute", index) for index in range(32)]
    responses.extend(call("read_file", index) for index in range(33, 40))
    responses.append(AIMessage(content="Final report delivery."))
    model = _BudgetProbeModel(responses=responses)
    graph = create_agent(model=model, tools=[execute, read_file], system_prompt="base",
                         middleware=[ExpertCallBudgetMiddleware()])

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="research")]}))

    assert result["messages"][-1].text == "Final report delivery."
    assert (research_calls, report_reads, len(model.seen_messages)) == (32, 7, 40)
    for call_index, messages in enumerate(model.seen_messages, start=1):
        system = next(message.text for message in messages if isinstance(message, SystemMessage))
        if call_index <= 32:
            assert "Reserved report wind-down" not in system
        elif call_index < 40:
            assert "Reserved report wind-down" in system
        else:
            assert "Final delivery call" in system
    assert all("execute" in names for names in model.bound_tool_names[:32])
    assert all("execute" not in names for names in model.bound_tool_names[32:])


def test_missing_report_receipt_never_forwards_tool_markup(tmp_path):
    root = tmp_path / "agents" / "ocean-process-x"
    report = root / "reports" / "B1.3" / "report.md"
    question = HumanMessage(content="Question")
    # Task 1: the limit-forced, tool-free call 60 returned DeepSeek tool markup as text.
    capped = [question] + [AIMessage(content="<｜DSML｜ calls>")] * 60
    text = _missing_report(capped, report)
    assert text.startswith("Result: No report — it reached its 60-call limit")
    assert "DSML" not in text and str(root / "scratch") in text
    cut = [question, AIMessage(content="", tool_calls=[
        {"name": "execute", "args": {}, "id": "call-1", "type": "tool_call"}])]
    assert "it stopped after 1 model calls" in _missing_report(cut, report)
    # An Expert that finished on its own keeps its closing answer.
    assert _missing_report([question, AIMessage(content="Done.")], report) == "Done."


@pytest.mark.asyncio
@pytest.mark.parametrize("fails,close_fails", [(False, False), (True, False), (False, True)])
async def test_each_expert_attempt_closes_its_node_kernel(monkeypatch, tmp_path, fails, close_fails):
    from oceanx.research import graphs

    closed = []

    class Kernels:
        async def close(self, key):
            closed.append(key)
            if close_fails:  # a cleanup problem must not fail a finished attempt
                raise RuntimeError("kernel busy")

    def root(_task_id, agent_key):
        path = tmp_path / "agents" / agent_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    projector = SimpleNamespace(expert_session_root=root)
    fake_host = SimpleNamespace(
        research=ResearchServices(SimpleNamespace(task_workspace_projector=projector,
                                                  expert_code_execution=None)),
        task_workspace_projector=projector,
        expert_code_execution=SimpleNamespace(kernels=Kernels()),
    )

    class Author:
        async def ainvoke(self, state, config):
            if fails:
                raise RuntimeError("model failed")
            return {"messages": [*state["messages"], AIMessage(content="Done.")]}

    async def fake_build(*_args, **_kwargs):
        return Author()

    monkeypatch.setattr(graphs, "host", lambda: fake_host)
    monkeypatch.setattr(graphs, "build", fake_build)
    graph = await graphs.expert(_config(), "ocean_process_expert")
    state = {"messages": [HumanMessage(content="B1.2: test transport")]}
    if fails:
        with pytest.raises(RuntimeError, match="model failed"):
            await graph.ainvoke(state, _config())
    else:
        await graph.ainvoke(state, _config())
    key = expert_agent_key("task", "ocean_process_expert", "B1.2: test transport")
    # Its memory never reaches another node or a later attempt; the files stay.
    assert closed == [str(tmp_path / "agents" / key)]


def test_an_expert_is_shown_the_folders_of_the_nodes_it_continues(monkeypatch, tmp_path):
    from oceanx.research import graphs

    attempts = {
        "B1.3": [{"agent_key": "ocean-process-old"}, {"agent_key": "ocean-process-new"}],
        "B1": [{"agent_key": "statistics-b1"}, {"agent_key": "coordinator"}],
        "B2.1": [{"agent_key": "ocean-process-own"}, {"agent_key": "ocean-process-b21"}],
    }
    tree = SimpleNamespace(
        document=lambda: {"nodes": {"B1.3.1": {"dependencies": ["B2.1", "B1"]}}},
        attempts=lambda node: attempts.get(node, []))
    monkeypatch.setattr(graphs, "research_tree", lambda _task_id: tree)
    monkeypatch.setattr(graphs, "host", lambda: SimpleNamespace(task_workspace_projector=SimpleNamespace(
        expert_session_root=lambda _task_id, key: tmp_path / "agents" / key)))
    run = AgentRun("ws", "task", "request", "ocean-process-own", "server", "ocean_process_expert",
                   question="B1.3.1: test the depth", node_id="B1.3.1")
    agents = tmp_path / "agents"
    # Nearest node first, its latest attempt first; never the Coordinator or this node itself.
    assert graphs._earlier_work(run) == [
        f"B1.3: {agents / 'ocean-process-new'}, {agents / 'ocean-process-old'}",
        f"B1: {agents / 'statistics-b1'}",
        f"B2.1: {agents / 'ocean-process-b21'}",
    ]
    unbound = AgentRun("ws", "task", "request", "ocean-process-x", "server", "ocean_process_expert",
                       question="What is the trend?")
    assert graphs._earlier_work(unbound) == []


def _team(children, state="running"):
    router = object.__new__(OceanRequestRouter)
    router._native_task_activity = {}
    router.store = SimpleNamespace(get_request=lambda _: SimpleNamespace(
        state=state, created_at="2026-09-17T10:00:00Z", updated_at="2026-09-17T10:03:00Z"))
    return asyncio.run(router._native_team_snapshot_payload(
        workspace_id="ws", parent_request_id="request", task_id="task",
        revision=1, native_tasks=children))


def _child(call_id, question, status="running"):
    return {"task_id": call_id, "agent_name": "ocean_process_expert",
            "request_id": "request", "description": question, "status": status}


def test_team_card_uses_same_identity_as_expert_workspace_from_start_to_followup():
    first = _child("call-1", "B1: establish anomaly")
    expected = AgentRun.from_config(_config(), "ocean_process_expert", question=first["description"])
    started = _team([first])
    assert started.agents[1].agent_id == expected.thread_id
    assert started.agents[1].status == "working"
    first.update(status="completed", agent_key=expected.thread_id, report_path="/report.md")
    assert _team([first]).agents[1].status == "completed"
    followup = _child("call-2", "B1: publish the requested anomaly map from the saved evidence")
    snapshot = _team([first, followup])
    assert len(snapshot.agents) == 2
    assert snapshot.agents[1].agent_id == expected.thread_id
    assert snapshot.agents[1].agent_run_id == "call-2"
    assert snapshot.agents[1].status == "working"
    assert snapshot.agents[1].task_goal == followup["description"]
    assert len(snapshot.dependencies) == 1
    assert len(snapshot.todos) == 2  # assignment history, not two participants
    assert all(todo.expert_key == expected.thread_id for todo in snapshot.todos)
    followup["status"] = "failed"
    failed = _team([first, followup])
    assert failed.agents[1].status == "failed"  # not the earlier success
    child = _child("call-3", "B1.2: test transport")
    assert len(_team([first, followup, child]).agents) == 3  # a child node is its own Expert


def test_finished_parallel_assignment_does_not_hide_work_still_running_on_same_expert():
    first = _child("call-1", "B1: anomaly")
    second = _child("call-2", "B1: depth of the anomaly", "completed")
    snapshot = _team([first, second])
    assert len(snapshot.agents) == 2
    assert snapshot.agents[1].status == "working"
    assert snapshot.agents[1].agent_run_id == "call-1"
    first["status"] = "completed"
    assert _team([first, second]).agents[1].status == "completed"


def test_completed_expert_card_uses_report_result_as_its_preview():
    child = _child("call-1", "B1: anomaly", "completed")
    child.update(
        report_path="/task/agents/ocean/reports/B1/report.md",
        summary=(
            "Result: The warm anomaly persists after surface heating weakens.\n"
            "Evidence and limitations: One year of reanalysis.\n"
            "Further analysis: Test horizontal transport."
        ),
    )
    snapshot = _team([child])
    agent = snapshot.agents[1]
    assert agent.activity == "The warm anomaly persists after surface heating weakens."
    assert agent.report_title == agent.activity
    assert snapshot.todos[0].report_title == agent.activity


def test_every_delegation_of_one_node_stays_on_one_card_whatever_its_wording():
    # A retry, a report recovery and a visual follow-up of B1.3.1, as the Coordinator wrote them.
    descriptions = ("B1.3.1: test the depth of the anomaly",
                    "Recover the report from the saved files",
                    "Continue B1.3: publish the requested depth map")
    children = []
    for index, description in enumerate(descriptions, 1):
        child = _child(f"call-{index}", description, "completed" if index < 3 else "running")
        child["node_id"] = "B1.3.1"
        children.append(child)
    snapshot = _team(children)
    expected = expert_agent_key("task", "ocean_process_expert", "", "B1.3.1")
    assert [agent.agent_id for agent in snapshot.agents[1:]] == [expected]
    assert snapshot.agents[1].status == "working"
    assert len(snapshot.todos) == 3


def test_repeated_work_on_one_node_keeps_every_assignment_report_in_todos():
    first = _child("call-1", "B1.1: establish anomaly", "completed")
    first.update(
        report_path="/task/agents/ocean/reports/B1.1/report.md",
        summary="Result: B1.1 established the surface anomaly.",
        created_at="2026-09-18T10:00:00Z",
        last_updated_at="2026-09-18T10:05:00Z",
    )
    second = _child("call-2", "B1.1: publish the anomaly map", "completed")
    second.update(
        report_path="/task/agents/ocean/reports/B1.1/report.md",
        summary="Result: B1.1 published the anomaly map.",
        created_at="2026-09-18T10:06:00Z",
        last_updated_at="2026-09-18T10:11:00Z",
    )
    snapshot = _team([first, second])

    assert len(snapshot.agents) == 2  # Coordinator plus the one Expert of node B1.1.
    assert [todo.report_path for todo in snapshot.todos] == [
        "/task/agents/ocean/reports/B1.1/report.md",
        "/task/agents/ocean/reports/B1.1/report.md",
    ]
    assert [todo.report_title for todo in snapshot.todos] == [
        "B1.1 established the surface anomaly.",
        "B1.1 published the anomaly map.",
    ]
    assert [todo.updated_at for todo in snapshot.todos] == [
        "2026-09-18T10:05:00Z",
        "2026-09-18T10:11:00Z",
    ]


def test_report_prose_cannot_override_deepagents_execution_status():
    child = _child("call-1", "B1: anomaly", "completed")
    child.update(
        report_path=None,
        summary=(
            "Execution status: incomplete\n"
            "Scientific status: unavailable\n"
            "Result: The Expert could not produce a validated report.\n"
            "Evidence and limitations: Delivery ended.\n"
            "Further analysis: Retry."
        ),
    )
    agent = _team([child]).agents[1]
    assert agent.status == "completed"
    assert agent.report_path is None
    assert agent.report_title is None


@pytest.mark.parametrize("state", ["cancelled", "failed", "interrupted", "completed"])
def test_terminal_parent_cannot_leave_an_expert_card_working(state):
    snapshot = _team([_child("call-1", "B1: pending result"),
                      _child("call-2", "B2: delivered", "completed")], state=state)
    assert snapshot.agents[1].status == "incomplete"
    assert snapshot.agents[2].status == "completed"
    assert all(agent.status != "working" for agent in snapshot.agents)


def test_long_assignment_does_not_break_team_event_validation_or_change_identity():
    question = "Inspect the supplied literature. " * 400
    snapshot = _team([_child("call-1", question)])
    assert snapshot.agents[1].status == "working"
    assert snapshot.agents[1].agent_id == expert_agent_key("task", "ocean_process_expert", question)
    assert len(snapshot.agents[1].task_goal) == 8000
    assert len(snapshot.interactions[0].summary) == 512


def test_a_final_call_that_prints_tool_markup_is_asked_once_more_for_plain_text():
    from oceanx.research.graphs import PLAIN_TEXT_RETRY

    @tool
    def read_file(value: int) -> str:
        """Perform one probe report-file read."""
        return str(value)

    responses = [AIMessage(content="", tool_calls=[{
        "name": "read_file", "args": {"value": index}, "id": f"read-{index}", "type": "tool_call"}])
        for index in range(59)]
    # Task 1: the tool-free call 60 printed DeepSeek tool markup instead of the report.
    responses += [AIMessage(content='<｜DSML｜function_calls><｜DSML｜invoke name="write_file">'),
                  AIMessage(content="## Summary\nResult: the anomaly persists.")]
    model = _BudgetProbeModel(responses=responses)
    graph = create_agent(model=model, tools=[read_file], system_prompt="base",
                         middleware=[ExpertCallBudgetMiddleware()])

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="research")]}))

    assert result["messages"][-1].text == "## Summary\nResult: the anomaly persists."
    assert len(model.seen_messages) == 61  # the second request belongs to call 60
    final, retry = model.seen_messages[-2:]
    system = next(message.text for message in final if isinstance(message, SystemMessage))
    assert "write the complete report as this reply" in system
    assert retry[-1].text == PLAIN_TEXT_RETRY


@pytest.mark.asyncio
@pytest.mark.parametrize("closing,saved", [
    ("## Summary\nResult: transport is weak.", "## Summary\nResult: transport is weak."),
    ('Transport is weak.<｜DSML｜function_calls>', "Transport is weak."),
    ("<｜DSML｜function_calls>", None),
])
async def test_an_expert_without_report_md_delivers_its_closing_reply(monkeypatch, tmp_path, closing, saved):
    from oceanx.research import graphs

    def root(_task_id, agent_key):
        path = tmp_path / "agents" / agent_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    projector = SimpleNamespace(expert_session_root=root)
    fake_host = SimpleNamespace(
        research=ResearchServices(SimpleNamespace(task_workspace_projector=projector,
                                                  expert_code_execution=None)),
        task_workspace_projector=projector, expert_code_execution=None)

    class Author:
        async def ainvoke(self, state, config):
            return {"messages": [*state["messages"], AIMessage(content=closing)]}

    async def fake_build(*_args, **_kwargs):
        return Author()

    monkeypatch.setattr(graphs, "host", lambda: fake_host)
    monkeypatch.setattr(graphs, "build", fake_build)
    graph = await graphs.expert(_config(), "ocean_process_expert")
    result = await graph.ainvoke({"messages": [HumanMessage(content="B1.2: test transport")]}, _config())

    key = expert_agent_key("task", "ocean_process_expert", "B1.2: test transport")
    report = tmp_path / "agents" / key / "reports" / "B1.2" / "report.md"
    summary, path = parse_expert_receipt(result["messages"][-1].text)
    if saved is None:  # markup alone is never a report and never forwarded
        assert not report.exists() and path is None
        assert summary.startswith("Result: No report") and "DSML" not in summary
    else:
        assert report.read_text() == saved and path == str(report)


@pytest.mark.asyncio
@pytest.mark.parametrize("initial,role,closing,updated,expected,calls", [
    ("report", "ocean_process_expert", "The figure is saved.", False, "report", 1),
    ("report", "ocean_process_expert", "", False, "report", 1),
    ("report", "ocean_process_expert", "<｜DSML｜function_calls>", False, "report", 60),
    ("empty", "ocean_process_expert", "The figure is saved.", False, "closing", 1),
    ("missing", "ocean_process_expert", "The figure is saved.", False, "closing", 1),
    ("report", "scientific_discussion_partner", "The discussion is complete.", False, "closing", 1),
    ("report", "ocean_process_expert", "## Summary\nResult: revised finding.", False, "closing", 1),
    ("report", "ocean_process_expert", "The figure is saved.", True, "updated", 1),
])
async def test_expert_receipt_preserves_an_unchanged_report(
    monkeypatch, tmp_path, initial, role, closing, updated, expected, calls,
):
    from oceanx.research import graphs, services

    question = "B1.2: test transport"
    key = expert_agent_key("task", role, question, node_id="B1.2")
    root = tmp_path / "agents" / key
    report = root / "reports" / "B1.2" / "report.md"
    report.parent.mkdir(parents=True)
    original = ("## Summary\nResult: transport is weak.\n\n"
                "## Evidence and limitations\nThe full scientific evidence remains here.\n")
    revised = "## Summary\nResult: transport is stronger after the new analysis.\n"
    if initial != "missing":
        report.write_text(original if initial == "report" else " \n", encoding="utf-8")
    original_revision = services.file_revision(report)

    projector = SimpleNamespace(expert_session_root=lambda _task, _agent: root)
    fake_host = SimpleNamespace(
        research=ResearchServices(SimpleNamespace(task_workspace_projector=projector,
                                                  expert_code_execution=None)),
        task_workspace_projector=projector, expert_code_execution=None)
    monkeypatch.setattr(services, "current_delegation", lambda: SimpleNamespace(
        node_id="B1.2", delegation_id="delegation", attempt_id="attempt", started_at=None))
    attached = []

    def attach_result(node_id, **kwargs):
        attached.append((node_id, kwargs))
        return {"projection": {"nodes": [{"id": node_id, "result": {}}]}}

    class Author:
        async def ainvoke(self, state, config):
            if updated:
                report.write_text(revised, encoding="utf-8")
            return {"messages": [*state["messages"],
                                 *[AIMessage(content="") for _ in range(calls - 1)],
                                 AIMessage(content=closing)]}

    async def fake_build(*_args, **_kwargs):
        return Author()

    monkeypatch.setattr(graphs, "host", lambda: fake_host)
    monkeypatch.setattr(graphs, "build", fake_build)
    monkeypatch.setattr(graphs, "research_tree", lambda _task: SimpleNamespace(
        attach_result=attach_result))
    graph = await graphs.expert(_config(), role)
    result = await graph.ainvoke({"messages": [HumanMessage(content=question)]}, _config())

    saved = {"report": original, "closing": closing, "updated": revised}[expected]
    assert report.read_text(encoding="utf-8") == saved
    if expected == "report":
        assert services.file_revision(report) == original_revision
    receipt = result["messages"][-1].text
    summary, path = parse_expert_receipt(receipt)
    expected_summary = services.report_summary(saved) or saved.strip()
    assert summary.startswith(expected_summary) and path == str(report)
    assert len(attached) == 1
    assert attached[0][0] == "B1.2"
    assert attached[0][1]["summary"] == expected_summary
    assert attached[0][1]["report_path"] == str(report)
    if expected == "report":
        prose = graphs._prose(AIMessage(content=closing))
        if prose:
            assert receipt.endswith("This attempt left the report unchanged and ended with: " + prose)
        else:
            reason = "it reached its 60-call limit" if calls == 60 else "it stopped after 1 model calls"
            assert receipt.endswith(
                "This attempt left the report unchanged and gave no closing answer: " + reason + ".")
    else:
        assert "This attempt left the report unchanged" not in receipt
    assert "DSML" not in receipt
    version = root / ".runtime" / "report-history" / "B1.2" / "attempt.md"
    assert version.read_text(encoding="utf-8") == saved


@pytest.mark.asyncio
@pytest.mark.parametrize("options, expected", [
    ({"max_parallel_experts": 4}, 4),      # the desktop's setting, sent with the request
    ({}, MAX_PARALLEL_EXPERTS),            # none sent (the benchmark): the environment's value stays
])
async def test_a_coordinator_run_sizes_the_data_expert_pool_from_its_request(
    monkeypatch, tmp_path, options, expected,
):
    from oceanx.research import graphs

    seen = {}

    class Agent:
        async def ainvoke(self, state, config=None):
            seen["data"] = _expert_slots().limit
            seen["search"] = _search_expert_slots().limit
            return {"messages": [*state["messages"], AIMessage(content="answer")]}

    async def fake_agent(_config, _experts):
        return Agent()

    monkeypatch.setattr(graphs, "_coordinator_agent", fake_agent)
    monkeypatch.setattr(graphs, "coordinator_report_path", lambda _config: tmp_path / "report.md")
    config = _config()
    config["configurable"]["request_options"] = {"workflow_mode": "standard", **options}
    _expert_slots(MAX_PARALLEL_EXPERTS)  # whatever an earlier request left in the app-wide pool
    graph = await graphs.coordinator(config)

    await graph.ainvoke({"messages": [HumanMessage(content="q")]}, config)

    assert seen == {"data": expected, "search": MAX_PARALLEL_SEARCH_EXPERTS}  # Search keeps its own pool


def test_another_attempt_at_a_question_is_told_to_continue_its_earlier_work(monkeypatch, tmp_path):
    from oceanx.research import graphs

    folder = tmp_path / "agents" / "ocean-process-x"
    report = folder / "reports" / "B1.2" / "report.md"
    monkeypatch.setattr(graphs, "host", lambda: SimpleNamespace(
        research=SimpleNamespace(report_path=lambda _run: report)))
    run = AgentRun("ws", "task", "request", "ocean-process-x", "server", "ocean_process_expert",
                   question="B1.2: test transport", node_id="B1.2")
    for name in ("scratch", "outputs"):
        (folder / name).mkdir(parents=True)
    assert graphs._earlier_attempt(run) == ""  # a first attempt starts with empty folders
    (folder / "scratch" / "monthly.nc").write_bytes(b"")
    assert "left files in" in graphs._earlier_attempt(run) and "no report" in graphs._earlier_attempt(run)
    report.parent.mkdir(parents=True)
    report.write_text("## Summary\nPartial.")
    assert f"left its report at {report}" in graphs._earlier_attempt(run)
    assert "still the report for this question" in graphs._earlier_attempt(run)
    assert "Do not rewrite it" in graphs._earlier_attempt(run)


def test_research_budget_stamps_receipts_and_stops_new_assignments():
    from langgraph.types import Command

    from oceanx.research.graphs import BUDGET_REFUSAL, ResearchBudgetMiddleware

    now = [0.0]
    budget = ResearchBudgetMiddleware(100, clock=lambda: now[0])

    def request(name="task", call_id="call-1"):
        return SimpleNamespace(tool_call={"name": name, "id": call_id, "args": {}})

    receipt = ToolMessage(content="Result: done.\nReport: /r.md", tool_call_id="call-1", name="task")
    stamped = budget.wrap_tool_call(request(), lambda _request: receipt)
    assert stamped.text.endswith(
        "Research status: 0 min elapsed of a 100-minute budget; 1 Expert assignments so far.")
    assert parse_expert_receipt(stamped.text) == ("Result: done.", "/r.md")
    # A native task returns a Command; its receipt is stamped the same way.
    now[0] = 30 * 60
    command = budget.wrap_tool_call(request(call_id="call-2"),
                                    lambda _request: Command(update={"messages": [receipt], "files": {}}))
    assert command.update["messages"][0].text.endswith("30 min elapsed of a 100-minute budget; "
                                                       "2 Expert assignments so far.")
    assert command.update["files"] == {}
    other = ToolMessage(content="tree", tool_call_id="call-3", name="update_research_tree")
    now[0] = 75 * 60
    assert budget.wrap_tool_call(request("update_research_tree", "call-3"), lambda _request: other) is other
    refused = budget.wrap_tool_call(request(call_id="call-4"),
                                    lambda _request: pytest.fail("no new assignment after 75%"))
    assert (refused.status, refused.text) == ("error", BUDGET_REFUSAL)
    # Waiting for Experts that are already working is never refused, and its result shows the time
    # used too: receipts can now reach the Coordinator through it.
    waited = ToolMessage(content="Receipt of B1.2 (x):\nResult: done.", tool_call_id="call-5",
                         name="await_experts")
    stamped_wait = budget.wrap_tool_call(request("await_experts", "call-5"), lambda _request: waited)
    assert stamped_wait.text.endswith("75 min elapsed of a 100-minute budget; 2 Expert assignments so far. "
                                      "Start no new assignment; write the final report.")
    # Without a budget the receipt shows the time used and nothing is refused.
    unlimited = ResearchBudgetMiddleware(None, clock=lambda: 10 ** 6)
    assert unlimited.wrap_tool_call(request(), lambda _request: receipt).text.endswith(
        "min elapsed; 1 Expert assignments so far.")


@pytest.mark.asyncio
async def test_research_coordinator_checks_the_budget_before_binding_a_node(monkeypatch, tmp_path):
    from oceanx.research import graphs
    from oceanx.research.delegation import StructuredDelegationMiddleware

    captured: dict[str, Any] = {}

    async def fake_expert(_config, profile_id):
        return f"runnable:{profile_id}"

    async def fake_build(_config, role, *, subagents=None, suffix="", middleware=None, **_kwargs):
        captured.update(middleware=middleware, suffix=suffix)
        return "graph"

    monkeypatch.setattr(graphs, "expert", fake_expert)
    monkeypatch.setattr(graphs, "build", fake_build)
    monkeypatch.setattr(graphs, "coordinator_report_path", lambda _config: tmp_path / "report.md")
    monkeypatch.setattr(graphs, "research_tree",
                        lambda _task_id: SimpleNamespace(policy=SimpleNamespace(guidance="")))
    monkeypatch.setenv(graphs.RESEARCH_BUDGET_ENV, "180")
    config = _config()
    config["configurable"]["original_question"] = "Assess mixed-layer-depth sensitivity."
    assert await _coordinator_agent(config) == "graph"
    background, budget, binding, repair = captured["middleware"]
    # First, so the budget check, the tree binding and the native tool all run inside the Expert's job.
    assert isinstance(background, BackgroundDelegationMiddleware)
    assert isinstance(budget, graphs.ResearchBudgetMiddleware) and budget.budget == 180
    assert isinstance(binding, StructuredDelegationMiddleware)
    assert isinstance(repair, ToolCallRepairMiddleware)  # last, so it sees the model's reply first
    assert binding.original_question == config["configurable"]["original_question"]
    assert "Research time budget: 180 minutes. After 135 minutes" in captured["suffix"]
    suffix = captured["suffix"]
    # The Owner's rule: results arrive one by one, and the Coordinator decides whether to wait.
    assert "A task call returns as soon as the next running Expert finishes" in suffix
    assert "continue that node's own line at once" in suffix
    assert "a new question that several outstanding results must decide together waits" in suffix
    assert "call await_experts with their node_ids" in suffix
    assert "write the final answer only when no Expert is still running" in suffix
    assert "view='full'" in suffix and "view='results'" in suffix  # the tree for its section, the results to reconcile
    assert "clips each Result" in suffix and "a correction made late in a Summary" in suffix
    assert "a node that corrects an earlier one replaces its value" in suffix
    assert "Do not synthesize from only the first reports" in suffix
    assert "no more strongly than its evidence" in suffix  # the wording rule scored down in Q08
    assert "call a comparison independent only if the evidence shows it is" in suffix
    monkeypatch.delenv(graphs.RESEARCH_BUDGET_ENV)
    await _coordinator_agent(_config())
    assert captured["middleware"][1].budget is None
    assert "Research time budget" not in captured["suffix"]

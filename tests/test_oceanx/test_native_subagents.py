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
    EXPERT_WIND_DOWN_START,
    ExpertCallBudgetMiddleware,
    _coordinator_agent,
    _wind_down_request,
)
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

    async def fake_build(_config, role, *, subagents=None, suffix="", **_kwargs):
        captured.update(role=role, subagents=subagents, suffix=suffix)
        return "graph"

    monkeypatch.setattr(graphs, "expert", fake_expert)
    monkeypatch.setattr(graphs, "build", fake_build)
    monkeypatch.setattr(graphs, "coordinator_report_path", lambda _config: tmp_path / "report.md")

    assert await _coordinator_agent(config) == "graph"
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


def test_same_root_branch_reuses_workspace_and_independent_roots_do_not():
    first = AgentRun.from_config(_config(), "ocean_process_expert", question="B1: establish anomaly")
    child = AgentRun.from_config(_config(), "ocean_process_expert", question="B1.2: test transport")
    sibling = AgentRun.from_config(_config(), "ocean_process_expert", question="B2: test mixing")
    assert first.thread_id == child.thread_id
    assert first.thread_id != sibling.thread_id
    assert first.agent_run_id == first.thread_id


def test_same_expert_keeps_distinct_parent_and_child_reports(tmp_path):
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
    assert parent.thread_id == first_child.thread_id == second_child.thread_id
    paths = {services.report_path(run) for run in (parent, first_child, second_child)}
    assert len(paths) == 3
    assert services.report_path(parent).as_posix().endswith("/reports/B1/report.md")
    assert services.report_path(first_child).as_posix().endswith("/reports/B1.1/report.md")


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
    assert EXPERT_WIND_DOWN_START == 48
    assert EXPERT_FINAL_CALL == 59
    source = Path(__file__).parents[2] / "src/oceanx/research/graphs.py"
    text = source.read_text(encoding="utf-8")
    assert "ModelCallLimitMiddleware" in text
    assert "ExpertCallBudgetMiddleware(ModelCallLimitMiddleware)" in text
    assert "super().__init__(run_limit=EXPERT_MODEL_CALL_LIMIT" in text
    assert "middleware=[ExpertCallBudgetMiddleware()]" in text
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
    followup = _child("call-2", "B1.2: test transport")
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
    other = _child("call-3", "B2: test mixing")
    assert len(_team([first, followup, other]).agents) == 3


def test_finished_parallel_assignment_does_not_hide_work_still_running_on_same_expert():
    first = _child("call-1", "B1: anomaly")
    second = _child("call-2", "B1.1: depth", "completed")
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


def test_reused_expert_keeps_every_assignment_report_in_todos():
    first = _child("call-1", "B1.1: establish anomaly", "completed")
    first.update(
        report_path="/task/agents/ocean/reports/B1.1/report.md",
        summary="Result: B1.1 established the surface anomaly.",
        created_at="2026-09-18T10:00:00Z",
        last_updated_at="2026-09-18T10:05:00Z",
    )
    second = _child("call-2", "B1.2: test transport", "completed")
    second.update(
        report_path="/task/agents/ocean/reports/B1.2/report.md",
        summary="Result: B1.2 found no resolved transport signal.",
        created_at="2026-09-18T10:06:00Z",
        last_updated_at="2026-09-18T10:11:00Z",
    )
    snapshot = _team([first, second])

    assert len(snapshot.agents) == 2  # Coordinator plus one reused Ocean Expert.
    assert [todo.report_path for todo in snapshot.todos] == [
        "/task/agents/ocean/reports/B1.1/report.md",
        "/task/agents/ocean/reports/B1.2/report.md",
    ]
    assert [todo.report_title for todo in snapshot.todos] == [
        "B1.1 established the surface anomaly.",
        "B1.2 found no resolved transport signal.",
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

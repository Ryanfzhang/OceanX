from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from oceanx.agent_contract import (
    AssistantTurnComplete,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from oceanx.agent_tools import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from oceanx.deep_runtime import DeepAgentEngine, _configure_native_harness
from oceanx.model_config import OceanModelProfile
from tests.test_oceanx.graph_fixture import build_deep_agent_engine


class _BoundFakeModel(FakeMessagesListChatModel):
    bound_tool_names: list[tuple[str, ...]] = Field(default_factory=list)
    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **_kwargs: Any):
        self.bound_tool_names.append(
            tuple(
                tool.name if hasattr(tool, "name") else str(tool.get("name", ""))
                for tool in tools
            )
        )
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


class _IncrementInput(BaseModel):
    value: int


class _DisconnectAfterToolModel(_BoundFakeModel):
    disconnected: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(m, ToolMessage) for m in messages) and not self.disconnected:
            self.disconnected = True
            raise RuntimeError("peer closed connection without sending complete message body")
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _IncrementTool(BaseTool):
    name = "ocean_increment"
    description = "Increment one test value."
    input_model = _IncrementInput

    def __init__(self) -> None:
        self.contexts: list[ToolExecutionContext] = []

    async def execute(
        self, arguments: _IncrementInput, context: ToolExecutionContext
    ) -> ToolResult:
        self.contexts.append(context)
        return ToolResult(output=str(arguments.value + 1))


class _NestedToolEventGraph:
    """Minimal v2 event stream with a child agent running inside one tool."""

    async def aget_state(self, _config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {"messages": ()}})()

    async def astream_events(
        self,
        _inputs: dict[str, Any],
        *,
        config: dict[str, Any],
        version: str,
    ):
        del config
        assert version == "v2"
        coordinator_tool_call = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ocean_assign",
                    "args": {"expert": "data"},
                    "id": "call-assign",
                    "type": "tool_call",
                }
            ],
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
            },
        )
        expert_private_answer = AIMessage(
            content="Expert private answer that must not become Coordinator prose.",
            usage_metadata={
                "input_tokens": 900_000,
                "output_tokens": 90_000,
                "total_tokens": 990_000,
            },
        )
        coordinator_final = AIMessage(
            content="Coordinator final answer.",
            usage_metadata={
                "input_tokens": 200,
                "output_tokens": 20,
                "total_tokens": 220,
            },
        )
        events = (
            {
                "event": "on_chat_model_start",
                "run_id": "coordinator-model-1",
                "parent_ids": ["root-graph"],
                "data": {},
            },
            {
                "event": "on_chat_model_end",
                "run_id": "coordinator-model-1",
                "parent_ids": ["root-graph"],
                "data": {"output": coordinator_tool_call},
            },
            {
                "event": "on_tool_start",
                "name": "ocean_assign",
                "run_id": "assign-run",
                "parent_ids": ["root-graph"],
                "data": {"input": {"expert": "data"}},
            },
            {
                "event": "on_chat_model_start",
                "run_id": "expert-model",
                "parent_ids": ["root-graph", "assign-run"],
                "data": {},
            },
            {
                "event": "on_chat_model_end",
                "run_id": "expert-model",
                "parent_ids": ["root-graph", "assign-run"],
                "data": {"output": expert_private_answer},
            },
            {
                "event": "on_tool_start",
                "name": "expert_private_tool",
                "run_id": "expert-tool-run",
                "parent_ids": ["root-graph", "assign-run", "expert-model"],
                "data": {"input": {"path": "private"}},
            },
            {
                "event": "on_tool_end",
                "name": "expert_private_tool",
                "run_id": "expert-tool-run",
                "parent_ids": ["root-graph", "assign-run", "expert-model"],
                "data": {"output": "private output"},
            },
            {
                "event": "on_tool_end",
                "name": "ocean_assign",
                "run_id": "assign-run",
                "parent_ids": ["root-graph"],
                "data": {"output": "durable native Expert report receipt"},
            },
            {
                "event": "on_chat_model_start",
                "run_id": "coordinator-model-2",
                "parent_ids": ["root-graph"],
                "data": {},
            },
            {
                "event": "on_chat_model_end",
                "run_id": "coordinator-model-2",
                "parent_ids": ["root-graph"],
                "data": {"output": coordinator_final},
            },
        )
        for event in events:
            yield event


@pytest.mark.asyncio
async def test_nested_agent_events_inside_a_tool_do_not_leak_into_parent_stream() -> None:
    operation = lambda request_id, turn_id, call_id: f"{request_id}:{turn_id}:{call_id}"
    engine = DeepAgentEngine(
        graph=_NestedToolEventGraph(),
        thread_id="coordinator-thread",
        operation_id_factory=operation,
    )

    events = [
        event
        async for event in engine.submit_message("coordinate", request_id="req-nested")
    ]

    assistant_turns = [
        event for event in events if isinstance(event, AssistantTurnComplete)
    ]
    assert len(assistant_turns) == 2
    assert [event.message.text for event in assistant_turns if event.message.text] == [
        "Coordinator final answer."
    ]
    assert sum(event.usage.input_tokens for event in assistant_turns) == 300
    assert [
        event.tool_name for event in events if isinstance(event, ToolExecutionStarted)
    ] == ["ocean_assign"]
    assert [
        event.tool_name for event in events if isinstance(event, ToolExecutionCompleted)
    ] == ["ocean_assign"]


@pytest.mark.asyncio
async def test_parallel_native_task_events_keep_their_own_assignment_when_start_order_changes():
    class Graph:
        async def aget_state(self, _config):
            return type("Snapshot", (), {"values": {}})()

        async def astream_events(self, *_args, **_kwargs):
            calls = [{"id": f"call-{branch}", "name": "task", "type": "tool_call",
                      "args": {"subagent_type": "ocean_process_expert", "description": f"{branch}: study"}}
                     for branch in ("B1", "B2")]
            yield {"event": "on_chat_model_end", "run_id": "model", "data": {
                "output": AIMessage(content="", tool_calls=calls)}}
            # Native tools may start in a different order than the model's list.
            for call in reversed(calls):
                yield {"event": "on_tool_start", "name": "task", "run_id": call["id"] + "-run",
                       "data": {"input": call["args"]}}
            for call in calls:
                yield {"event": "on_tool_end", "name": "task", "run_id": call["id"] + "-run",
                       "data": {"output": call["args"]["description"]}}
            yield {"event": "on_chat_model_end", "run_id": "final", "data": {
                "output": AIMessage(content="Final synthesis.")}}

    engine = DeepAgentEngine(graph=Graph(), thread_id="coordinator",
                             operation_id_factory=lambda *_args: "operation")
    events = [e async for e in engine.submit_message("study", request_id="req")]
    starts = [e for e in events if isinstance(e, ToolExecutionStarted)]
    ends = [e for e in events if isinstance(e, ToolExecutionCompleted)]
    assert [e.tool_call_id for e in starts] == ["call-B2", "call-B1"]
    assert [e.tool_input["description"] for e in starts] == ["B2: study", "B1: study"]
    assert [(e.tool_call_id, e.output) for e in ends] == [("call-B1", "B1: study"), ("call-B2", "B2: study")]


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["normal", "disconnect", "empty", "length", "refusal"])
async def test_deep_agent_returns_one_final_answer_with_fixture_tool_allowlist(
    tmp_path: Path, delivery: str, monkeypatch,
) -> None:
    from oceanx.provider_retry import provider_retry_middleware
    retry = provider_retry_middleware()
    retry.initial_delay = 0
    retry.jitter = False
    disconnect = delivery == "disconnect"
    model = (_DisconnectAfterToolModel if disconnect else _BoundFakeModel)(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ocean_increment",
                        "args": {"value": 1},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="The bounded result is 2."),
        ]
    )
    if delivery == "empty":
        model.responses.insert(1, AIMessage(content="", response_metadata={"finish_reason": "stop"}))
    elif delivery in {"length", "refusal"}:
        model.responses[1] = AIMessage(content="", response_metadata={"finish_reason": delivery})
    extra_calls = 48 if delivery == "normal" else 0
    for i in range(extra_calls):
        model.responses.insert(-1, AIMessage(content="", tool_calls=[{
            "name": "ocean_increment", "args": {"value": i},
            "id": f"extra-{i}", "type": "tool_call",
        }], usage_metadata={"input_tokens": 100_000, "output_tokens": 10, "total_tokens": 100_010}))
    # Fake model provider identity is its llm type.
    _configure_native_harness(type(model).__name__.lower())
    backend = StateBackend()
    registry = ToolRegistry()
    increment = _IncrementTool()
    registry.register(increment)
    operation = lambda request_id, turn_id, call_id: f"{request_id}:{turn_id}:{call_id}"
    graph = create_deep_agent(
        model=model,
        tools=registry.as_langchain_tools(cwd=tmp_path, operation_id_factory=operation),
        system_prompt="Ocean test",
        middleware=[
            retry,
            FilesystemMiddleware(backend=backend, tools=["read_file"]),
        ],
        subagents=[],
        backend=backend,
        checkpointer=MemorySaver(),
        name="ocean-test",
    )
    engine = DeepAgentEngine(
        graph=graph,
        thread_id="expert-thread",
        operation_id_factory=operation,
    )

    from oceanx.backend.router import _coordinator_events
    events = [event async for event in _coordinator_events(engine, "run", "req-1")]
    assert len(increment.contexts) == 1 + extra_calls
    snapshot = await graph.aget_state(engine._config("req-1"))
    assert sum(isinstance(m, HumanMessage) and m.content == "run"
               for m in snapshot.values["messages"]) == 1
    assert sum(isinstance(m, HumanMessage) for m in snapshot.values["messages"]) == 1

    assert any(isinstance(event, ToolExecutionStarted) for event in events)
    assert any(isinstance(event, ToolExecutionCompleted) for event in events)
    if delivery in {"length", "refusal", "empty"}:
        from oceanx.agent_contract import ErrorEvent
        assert isinstance(events[-1], ErrorEvent)
        assert events[-1].code == ("empty_model_response" if delivery == "empty" else "model_output_error")
        assert events[-1].retryable is (delivery == "empty")
        assert not events[-1].retries_exhausted
        return
    final = [event for event in events if isinstance(event, AssistantTurnComplete)][-1]
    assert final.message.text == "The bounded result is 2."
    if disconnect:
        assert model.disconnected
        assert final.turn_id == "req-1:turn:3"
    assert increment.contexts[0].tool_call_id == "call-1"
    assert increment.contexts[0].operation_id == "req-1:langgraph:call-1"
    assert model.bound_tool_names
    assert set(model.bound_tool_names[0]) == {"ocean_increment", "read_file"}


@pytest.mark.asyncio
async def test_sqlite_checkpoint_resumes_the_same_expert_after_runtime_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backend restart reuses graph state instead of replaying tool envelopes."""

    import oceanx.deep_runtime as runtime_module

    profile = OceanModelProfile(
        name="fixture",
        label="Fixture",
        provider="openai",
        model="fixture-model",
        base_url=None,
        credential_slot="fixture",
        api_key="fixture-key",
    )
    _configure_native_harness("_boundfakemodel")
    registry = ToolRegistry()
    operation = lambda request_id, turn_id, call_id: f"{request_id}:{turn_id}:{call_id}"

    first_model = _BoundFakeModel(responses=[AIMessage(content="First persisted answer.")])
    monkeypatch.setattr(runtime_module, "create_chat_model", lambda _profile: first_model)
    first, close_first = await build_deep_agent_engine(
        profile=profile,
        tools=registry,
        system_prompt="Ocean persistence test",
        cwd=tmp_path,
        thread_id="expert:persistent",
        max_turns=4,
        operation_id_factory=operation,
    )
    first_events = [
        event async for event in first.submit_message("first request", request_id="req-1")
    ]
    assert [
        event.message.text
        for event in first_events
        if isinstance(event, AssistantTurnComplete)
    ][-1] == "First persisted answer."
    await close_first()

    second_model = _BoundFakeModel(responses=[AIMessage(content="Second persisted answer.")])
    monkeypatch.setattr(runtime_module, "create_chat_model", lambda _profile: second_model)
    second, close_second = await build_deep_agent_engine(
        profile=profile,
        tools=registry,
        system_prompt="Ocean persistence test",
        cwd=tmp_path,
        thread_id="expert:persistent",
        max_turns=4,
        operation_id_factory=operation,
    )
    try:
        second_events = [
            event async for event in second.submit_message("second request", request_id="req-2")
        ]
        assert [
            event.message.text
            for event in second_events
            if isinstance(event, AssistantTurnComplete)
        ][-1] == "Second persisted answer."
        observed = second_model.seen_messages[-1]
        assert any(
            isinstance(message, AIMessage) and message.content == "First persisted answer."
            for message in observed
        )
        assert any(
            isinstance(message, HumanMessage) and message.content == "second request"
            for message in observed
        )
    finally:
        await close_second()

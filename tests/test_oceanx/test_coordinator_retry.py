import ast
import asyncio
import inspect
import textwrap
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from oceanx.agent_contract import ErrorEvent
from oceanx.backend.router import OceanRequestRouter, _coordinator_events
from oceanx.research.gateway import ServerGraphStream


@pytest.mark.asyncio
async def test_coordinator_does_not_enable_token_budget_wind_down(monkeypatch, tmp_path):
    from oceanx import agent
    from oceanx.research import gateway
    from oceanx.research.gateway import ServerGraphStream
    monkeypatch.setattr(agent, "load_model_profile", lambda *args: SimpleNamespace(provider="fixture", model="fixture"))
    monkeypatch.setattr(gateway, "agent_server_client", lambda: object())
    runtime = await agent.build_default_ocean_agent_runtime(
        SimpleNamespace(task_id="task", workspace_id="ws"), tmp_path,
        lambda *args: "operation",
    )
    assert isinstance(runtime.engine.graph, ServerGraphStream)
    assert runtime.engine.graph.handles_context


def test_coordinator_request_does_not_install_a_model_time_budget():
    # Structural regression: a request must not use the Expert wall-time field
    # or register a model-call timer capable of cancelling slow healthy calls.
    tree = ast.parse(textwrap.dedent(inspect.getsource(OceanRequestRouter._execute_agent_request)))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "max_wall_seconds" not in attributes
    assert "set_model_call_state_hook" not in attributes
    assert "CancelledError" in attributes


def test_production_runtime_does_not_install_quota_or_code_placeholder_projection():
    from oceanx import agent, deep_runtime

    source = inspect.getsource(agent.build_default_ocean_agent_runtime)
    assert "max_input_tokens=" not in source
    assert "max_output_tokens=" not in source
    assert not hasattr(deep_runtime, "TokenBudgetWindDownMiddleware")


class BrokenEngine:
    def __init__(self, retryable):
        self.retryable = retryable
        self.submissions = 0
        self.resumes = 0

    async def submit_message(self, text, *, request_id):
        self.submissions += 1
        yield ErrorEvent(message='connection lost', code='network_failure', retryable=self.retryable)

    async def resume_message(self, *, request_id):
        self.resumes += 1
        yield ErrorEvent(message='connection lost', code='network_failure', retryable=self.retryable)


@pytest.mark.asyncio
@pytest.mark.parametrize('retryable', [True, False])
async def test_gateway_does_not_replay_graph_on_provider_failure(retryable):
    engine = BrokenEngine(retryable)
    events = [e async for e in _coordinator_events(engine, 'question', 'req')]
    assert engine.submissions == 1
    assert engine.resumes == 0
    assert len(events) == 1
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].retryable is retryable


@pytest.mark.asyncio
async def test_server_stream_cancellation_uses_native_cancel_on_disconnect():
    class Threads:
        async def create(self, **_kwargs):
            return None

    class Runs:
        def __init__(self):
            self.joined = asyncio.Event()
            self.join_options = None

        async def create(self, *_args, **_kwargs):
            return {"run_id": "run-native"}

        def join_stream(self, thread_id, run_id, **options):
            self.join_options = (thread_id, run_id, options)

            async def events():
                self.joined.set()
                await asyncio.Event().wait()
                yield  # pragma: no cover - keeps this an async generator

            return events()

    runs = Runs()
    stream = ServerGraphStream(
        client=SimpleNamespace(threads=Threads(), runs=runs),
        binding={"workspace_id": "ws", "workspace_path": "/workspace", "task_id": "task"},
    )

    async def consume():
        return [event async for event in stream.astream_events(
            {"messages": [HumanMessage(content="question")]},
            {"configurable": {"request_id": "req"}},
        )]

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(runs.joined.wait(), timeout=1)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(consumer, timeout=1)

    assert runs.join_options == (
        stream.thread_id,
        "run-native",
        {"cancel_on_disconnect": True},
    )

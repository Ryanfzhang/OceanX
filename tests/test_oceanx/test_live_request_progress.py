"""Running tasks keep delivering tool progress after their submitting page closes."""
import pytest

from oceanx.agent_contract import ToolExecutionStarted, ToolExecutionCompleted
from oceanx.backend.auth import principal_for_client_kind
from oceanx.backend.events import BackendClient, EventBus
from oceanx.backend.router import OceanRequestRouter
from oceanx.protocol.v2.models import parse_request


@pytest.mark.asyncio
async def test_tool_only_progress_reaches_reconnected_workspace_not_other_workspaces():
    bus = EventBus()
    received, other = [], []

    def client(workspace, messages):
        return BackendClient(transport="websocket", expected_client_kind="desktop", sender=messages.append,
                             client_id="client", session_id="session", workspace_id=workspace,
                             principal=principal_for_client_kind("desktop"))

    original = client("ws", [])
    await bus.register(original)
    await bus.unregister(original)
    await bus.register(client("ws", received))
    await bus.register(client("another-ws", other))
    request = parse_request({"protocol_version": 2, "request_id": "req_progress", "type": "session.submit",
                             "payload": {"text": "Reproduce"}, "expected_workspace_revision": 0, "context": {
                                 "session_id": "session", "client_id": "client", "workspace_id": "ws", "task_id": "task_progress"}})
    router = object.__new__(OceanRequestRouter)
    router.event_bus = bus
    for event in (
        ToolExecutionStarted(tool_name="read_file", tool_input={"file_path": "/skills/paper-reproduction/SKILL.md"},
                             tool_call_id="call", turn_id="turn", request_id="req"),
        ToolExecutionCompleted(tool_name="read_file", output="Read", is_error=False,
                               tool_call_id="call", turn_id="turn", request_id="req"),
    ):
        await router._emit_agent_stream_event(original, request, event)
    assert [event.type for event in received] == ["tool.call.started", "tool.call.completed"]
    assert received[0].payload.input["file_path"].endswith("paper-reproduction/SKILL.md")
    assert not other

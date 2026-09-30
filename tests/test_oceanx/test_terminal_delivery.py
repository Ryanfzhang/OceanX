"""Large audit histories must not prevent final answers reaching the desktop."""

import json
from copy import deepcopy

import pytest

from oceanx.backend.events import BackendClient, EventBus
from oceanx.backend.host import PROTOCOL_PREFIX, JsonlStdioAdapter
from oceanx.backend.router import OceanRequestRouter
from oceanx.backend.store import RequestStore
from oceanx.protocol.v2.models import RequestCompletedEvent, parse_event, parse_request

DESKTOP_FRAME_BYTES = 1024 * 1024


def _completed():
    return RequestCompletedEvent.model_validate({
        "protocol_version": 2, "event_id": "evt_large_result", "sequence": 0,
        "request_id": "req_large_result", "task_id": "task_large_result",
        "timestamp": "2026-09-12T00:00:00Z", "type": "request.completed",
        "payload": {"workspace_revision": 3, "result": {
            "assistant_text": (
                "分析结论 🌊\n\n[[result:task_large_result/result_figure@v1|可视化]]\n\n"
                "**Supplementary Materials:**\n\n- [analysis.ipynb](analysis.ipynb)"
            ),
            "usage": {"input_tokens": 123, "output_tokens": 45},
            "team_provenance": {
                "architecture": "coordinator_owned_expert_runtime",
                "activation_count": 20,
                "actual_usage": {"input_tokens": 4000000, "output_tokens": 20000},
                "budget_limits": {"max_input_tokens": 5000000},
                "work_plan": {"notes": "Long planning history" * 10000},
                "work": [{"result": "专家报告" * 20000} for _ in range(5)],
                "code_executions": [
                    {"execution_id": f"exec_{i}", "result": {"stdout": "数据🌊" * 3000}}
                    for i in range(60)
                ],
            },
        }},
    })


@pytest.mark.asyncio
async def test_large_terminal_stdio_live_and_durable_replay(tmp_path):
    store = RequestStore(tmp_path / "state.sqlite3")
    bus = EventBus()
    frames = []
    adapter = JsonlStdioAdapter(
        router=OceanRequestRouter(store=store, event_bus=bus),
        event_bus=bus, write_frame=frames.append,
    )
    event = _completed()
    original = event.model_dump(mode="json")
    assert len(event.model_dump_json().encode("utf-8")) > DESKTOP_FRAME_BYTES
    try:
        request = parse_request({
            "protocol_version": 2, "request_id": event.request_id, "type": "session.submit",
            "payload": {"text": "Analyze the dataset"},
            "context": {"session_id": "session_fixture", "workspace_id": "ws_fixture",
                        "client_id": "client_fixture", "task_id": event.task_id},
            "expected_workspace_revision": 0, "expected_task_revision": 0,
        })
        store.reserve(request, principal="user:local:desktop")
        store.commit_terminal(request.request_id, event)
        await bus.emit_local(adapter.client, event)
        # Existing DBs retain the old, large event; reconnect still delivers it.
        replay = store.reserve(request, principal="user:local:desktop")
        assert not replay.created
        await bus.emit_local(adapter.client, replay.record.terminal_event)
        assert len(frames) == 2
        for sequence, frame in enumerate(frames, 1):
            encoded = frame.removeprefix(PROTOCOL_PREFIX).rstrip("\n")
            assert len(encoded.encode("utf-8")) < DESKTOP_FRAME_BYTES
            delivered = parse_event(json.loads(encoded))
            assert delivered.sequence == sequence
            assert delivered.request_id == event.request_id
            assert delivered.payload.workspace_revision == 3
            result = delivered.payload.result
            assert result["assistant_text"] == event.payload.result["assistant_text"]
            assert result["usage"] == event.payload.result["usage"]
            summary = result["team_provenance"]
            assert summary["actual_usage"] == event.payload.result["team_provenance"]["actual_usage"]
            assert summary["work_count"] == 5
            assert summary["code_execution_count"] == 60
            assert set(summary["details_omitted"]) == {"work", "work_plan", "code_executions"}
            assert not any(key in summary for key in summary["details_omitted"])
        assert event.model_dump(mode="json") == original
        assert store.get_request(request.request_id).terminal_event.model_dump(mode="json") == original
    finally:
        await adapter.close()
        store.close()


@pytest.mark.asyncio
async def test_status_wrapper_compacts_old_terminal_for_websocket():
    inner = _completed().model_dump(mode="json")
    wrapper = _completed().model_copy(update={
        "payload": _completed().payload.model_copy(update={"result": {
            "state": "completed", "request_id": "req_large_result", "terminal_event": inner,
        }}),
    })
    original = deepcopy(wrapper.model_dump(mode="json"))
    sent = []
    client = BackendClient(transport="websocket", expected_client_kind="desktop", sender=sent.append)
    await EventBus().emit_local(client, wrapper)
    assert len(sent[0].model_dump_json().encode("utf-8")) < DESKTOP_FRAME_BYTES
    result = sent[0].payload.result
    assert result["state"] == "completed"
    assert result["terminal_event"]["payload"]["result"]["assistant_text"] == inner["payload"]["result"]["assistant_text"]
    assert wrapper.model_dump(mode="json") == original


@pytest.mark.asyncio
async def test_delivery_preserves_other_results_and_is_idempotent():
    bus = EventBus()
    sent = []
    client = BackendClient(transport="stdio", expected_client_kind="desktop", sender=sent.append)
    await bus.emit_local(client, _completed())
    await bus.emit_local(client, sent[0])
    assert sent[0].payload == sent[1].payload
    ordinary = _completed().model_copy(update={
        "payload": _completed().payload.model_copy(update={"result": {
            "task_results": [{"result_id": "result_figure", "view": {"kind": "time_series"}}],
            "team_snapshots": [{"agents": [{"agent_id": "expert_1", "status": "completed"}]}],
            "messages": [{"blocks": [{"type": "text", "text": "Full transcript"}]}],
        }}),
    })
    await bus.emit_local(client, ordinary)
    assert sent[-1].payload == ordinary.payload

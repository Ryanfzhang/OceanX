"""End-to-end proof of the native synchronous DeepAgents task path."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from langgraph_sdk import get_client
from oceanx.research.services import parse_expert_receipt


async def _wait_for_server(process, url, headers, logpath):
    async with httpx.AsyncClient() as http, asyncio.timeout(60):
        while True:
            assert process.poll() is None, logpath.read_text()[-16000:]
            try:
                if (await http.get(url + "/ok", headers=headers)).is_success:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["text", "code", "long_report", "missing_report", "coordinator_missing_report"]
)
async def test_native_task_returns_receipt_to_the_same_coordinator_run(tmp_path, mode):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = str(uuid4())
    logpath = tmp_path / "server.log"
    with logpath.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("agent_server_fixture.py")),
             "--state", str(tmp_path / "state"), "--port", str(port)],
            stdout=log, stderr=log,
            env={**os.environ, "OCEAN_SERVER_TOKEN": token,
                 "OCEAN_DESKTOP_TOKEN": token + "-desktop", "OCEAN_FIXTURE_MODE": mode,
                 "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"},
        )
        try:
            url = f"http://127.0.0.1:{port}"
            headers = {"authorization": "Bearer " + token}
            await _wait_for_server(process, url, headers, logpath)
            client = get_client(url=url, headers=headers, api_key=None)
            thread = await client.threads.create()
            binding = {
                "workspace_id": "ws_fixture",
                "workspace_path": str(tmp_path / "state/workspace"),
                "task_id": "task_fixture",
                "request_id": "req_fixture_research",
                "original_question": "Campeche mechanisms?",
            }
            run = await client.runs.create(
                thread["thread_id"], "coordinator",
                input={"messages": [{"role": "user", "content": "Campeche mechanisms?"}]},
                config={"configurable": binding},
            )
            async with asyncio.timeout(120):
                while True:
                    finished = await client.runs.get(thread["thread_id"], run["run_id"])
                    if finished["status"] not in {"pending", "running"}:
                        break
                    await asyncio.sleep(0.2)
            state = await client.threads.get_state(thread["thread_id"])
            values = state.get("values", {})
            assert "async_tasks" not in values
            assert "reviewer_state" not in values
            assert not list((tmp_path / "state").rglob("review.md"))

            if mode == "coordinator_missing_report":
                assert finished["status"] == "success", logpath.read_text()[-24000:]
                assert values.get("research_complete") is True
                assert values.get("final_answer") == (
                    "I'm now waiting on the Ocean Process Expert. No further action."
                )
                reports = list((tmp_path / "state").rglob("report.md"))
                assert reports and all(path.parent.name != "coordinator" for path in reports)
                return

            if mode == "missing_report":
                # The Expert ended without saving report.md, so its closing reply was saved as one.
                assert finished["status"] == "success", logpath.read_text()[-24000:]
                task_receipts = [
                    parse_expert_receipt(message["content"])
                    for message in values["messages"]
                    if message.get("type") == "tool"
                    and isinstance(message.get("content"), str)
                    and "Research status:" in message["content"]
                ]
                assert len(task_receipts) == 1
                # The receipt summary also carries the server-verified Published results list.
                assert task_receipts[0][0].startswith("Done without saving.\n\nPublished results")
                assert Path(task_receipts[0][1]).read_text() == "Done without saving."
                # The Expert's report and the Coordinator's final report.
                assert len(list((tmp_path / "state").rglob("report.md"))) == 2
                return

            assert finished["status"] == "success", logpath.read_text()[-24000:]
            assert values["research_complete"] is True
            assert "Formation and persistence" in values["final_answer"]
            receipts = []
            for message in values["messages"]:
                if message.get("type") != "tool" or not isinstance(message.get("content"), str):
                    continue
                summary, report_path = parse_expert_receipt(message["content"])
                if report_path:
                    receipts.append((summary, report_path))
            assert len(receipts) == 1, values["messages"]
            summary, report_path = receipts[0]
            assert summary.startswith("Result: Formation and persistence")
            assert "Evidence and limitations:" in summary
            assert "Further analysis:" in summary
            assert Path(report_path).is_file()
            reports = list((tmp_path / "state").rglob("report.md"))
            assert len(reports) == 2
            if mode == "long_report":
                assert "海洋证据与局限。" * 1500 in Path(report_path).read_text()
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["gateway", "gateway_followup"])
async def test_desktop_gateway_projects_native_task_without_owning_it(tmp_path, mode):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = str(uuid4())
    logpath = tmp_path / "server.log"
    with logpath.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("agent_server_fixture.py")),
             "--state", str(tmp_path / "state"), "--port", str(port)],
            stdout=log, stderr=log,
            env={**os.environ, "OCEAN_SERVER_TOKEN": token,
                 "OCEAN_DESKTOP_TOKEN": token + "-desktop", "OCEAN_FIXTURE_MODE": mode,
                 "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"},
        )
        try:
            url = f"http://127.0.0.1:{port}"
            headers = {"authorization": "Bearer " + token}
            await _wait_for_server(process, url, headers, logpath)
            from websockets.asyncio.client import connect
            async with connect(url.replace("http:", "ws:") + "/ocean/protocol",
                               additional_headers={**headers,
                                                   "x-ocean-desktop-token": token + "-desktop"}) as ws:
                context = {}

                async def send(kind, payload, request_id):
                    frame = {"protocol_version": 2, "request_id": request_id,
                             "type": kind, "payload": payload}
                    if context:
                        frame.update(context=context, expected_workspace_revision=1)
                    await ws.send(json.dumps(frame))

                async def terminal(request_id):
                    seen = []
                    async with asyncio.timeout(120):
                        while True:
                            event = json.loads(await ws.recv())
                            seen.append(event)
                            assert event["type"] not in {"system.error", "request.failed"}, json.dumps(event)
                            if event.get("request_id") == request_id and event["type"] in {
                                "system.ready", "request.completed"
                            }:
                                return event, seen

                await send("system.handshake", {"client_kind": "desktop", "client_version": "test",
                                                  "supported_protocol_versions": [2]}, "req_hello")
                hello, _ = await terminal("req_hello")
                context.update(client_id=hello["payload"]["client_id"],
                               session_id=hello["payload"]["session_id"], workspace_id="ws_fixture")
                await send("workspace.open", {"path": str(tmp_path / "state/workspace")}, "req_open")
                await terminal("req_open")
                context["task_id"] = "task_fixture"
                await send("session.submit", {"text": "Campeche mechanisms?",
                                               "literature_acquisition_mode": "search_only"}, "req_research")
                final, events = await terminal("req_research")
                assert "Formation and persistence" in json.dumps(final)
                snapshots = [e for e in events if e["type"] == "team.snapshot"]
                running_experts = [
                    a for e in snapshots for a in e["payload"]["agents"]
                    if a["agent_id"] != "coordinator" and a["status"] == "working"
                ]
                experts = [a for e in snapshots for a in e["payload"]["agents"]
                           if a["agent_id"] != "coordinator"]
                assert running_experts, json.dumps(snapshots, ensure_ascii=False)
                assert experts and experts[-1]["status"] == "completed"
                assert experts[-1]["report_path"], json.dumps(
                    [e for e in events if e["type"].startswith("tool.")], ensure_ascii=False
                )
                assert "result_summary" not in experts[-1]
                for index, event in enumerate(events):
                    if (event["type"] == "tool.call.started"
                            and event["payload"]["tool_name"] == "task"):
                        next_snapshot = next(e for e in events[index + 1:] if e["type"] == "team.snapshot")
                        assert any(a["agent_run_id"] == event["payload"]["tool_call_id"]
                                   and a["status"] == "working" for a in next_snapshot["payload"]["agents"])
                # B1, its follow-up B1.1 and B2 (same role) each have their own
                # Expert, folder and card; each card starts and completes once.
                if mode == "gateway_followup":
                    assert len({a["agent_id"] for a in experts}) == 3
                    b1_key = experts[0]["agent_id"]
                    b1 = [a for a in experts if a["agent_id"] == b1_key]
                    states = [a["status"] for i, a in enumerate(b1)
                              if i == 0 or a["status"] != b1[i - 1]["status"]]
                    assert states == ["working", "completed"]
                    assert len({a["agent_run_id"] for a in b1}) == 1
                    assert len(snapshots[-1]["payload"]["agents"]) == 4
                    assert len(snapshots[-1]["payload"]["todos"]) == 3
                    assignments = [todo["question"] for todo in snapshots[-1]["payload"]["todos"]]
                    assert all(text.startswith("Question (") for text in assignments)
                    assert all("Parent question:" in text and "Parent answer:" in text
                               and "Parent report:" in text for text in assignments)
                    child = next(text for text in assignments if "Question (B1.1):" in text)
                    assert "Parent question: B1:" in child
                    assert "Parent answer: Result: Formation and persistence" in child
                    assert "Parent report: None" not in child
                    independent = next(text for text in assignments if "Question (B2):" in text)
                    assert "Parent question: None" in independent
                    assert "Parent answer: None" in independent
                    assert "Parent report: None" in independent
                    for event in snapshots:
                        ids = [a["agent_id"] for a in event["payload"]["agents"]]
                        assert len(ids) == len(set(ids))
                selected = experts[-1]
                await send("task.agent_transcript.get", {
                    "task_id": "task_fixture", "parent_request_id": "req_research",
                    "agent_id": selected["agent_id"], "agent_run_id": selected["agent_run_id"],
                }, "req_agent_detail")
                detail, _ = await terminal("req_agent_detail")
                assert detail["payload"]["result"]["agent_id"] == selected["agent_id"]
                assert detail["payload"]["result"]["messages"][0]["blocks"][0]["text"] == selected["task_goal"]
                await send("task.open", {"task_id": "task_fixture"}, "req_reopen")
                reopened, _ = await terminal("req_reopen")
                assert reopened["payload"]["result"]["team_snapshot"]["agents"] == snapshots[-1]["payload"]["agents"]
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)


@pytest.mark.asyncio
async def test_desktop_cancel_stops_native_agent_server_run_promptly(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = str(uuid4())
    logpath = tmp_path / "server.log"
    with logpath.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("agent_server_fixture.py")),
             "--state", str(tmp_path / "state"), "--port", str(port)],
            stdout=log, stderr=log,
            env={**os.environ, "OCEAN_SERVER_TOKEN": token,
                 "OCEAN_DESKTOP_TOKEN": token + "-desktop", "OCEAN_FIXTURE_MODE": "cancel",
                 "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"},
        )
        try:
            url = f"http://127.0.0.1:{port}"
            headers = {"authorization": "Bearer " + token}
            await _wait_for_server(process, url, headers, logpath)
            from websockets.asyncio.client import connect
            async with connect(
                url.replace("http:", "ws:") + "/ocean/protocol",
                additional_headers={**headers, "x-ocean-desktop-token": token + "-desktop"},
            ) as ws:
                context = {}

                async def send(kind, payload, request_id):
                    frame = {"protocol_version": 2, "request_id": request_id,
                             "type": kind, "payload": payload}
                    if context:
                        frame.update(context=context, expected_workspace_revision=1)
                    await ws.send(json.dumps(frame))

                async def wait_for(request_id, event_types):
                    while True:
                        event = json.loads(await ws.recv())
                        assert event["type"] not in {"system.error", "request.failed"}, event
                        if event.get("request_id") == request_id and event["type"] in event_types:
                            return event

                await send("system.handshake", {
                    "client_kind": "desktop", "client_version": "test",
                    "supported_protocol_versions": [2],
                }, "req_hello")
                hello = await wait_for("req_hello", {"system.ready"})
                context.update(client_id=hello["payload"]["client_id"],
                               session_id=hello["payload"]["session_id"], workspace_id="ws_fixture")
                await send("workspace.open", {"path": str(tmp_path / "state/workspace")}, "req_open")
                await wait_for("req_open", {"request.completed"})
                context["task_id"] = "task_fixture"
                await send("session.submit", {
                    "text": "Campeche mechanisms?",
                    "literature_acquisition_mode": "search_only",
                }, "req_research")
                await wait_for("req_research", {"request.accepted"})

                started = time.monotonic()
                await send("request.cancel", {
                    "target_request_id": "req_research",
                    "reason": "Cancelled by integration test",
                }, "req_cancel")
                terminals = {}
                snapshots = []
                async with asyncio.timeout(5):
                    while terminals.keys() != {"req_research", "req_cancel"}:
                        event = json.loads(await ws.recv())
                        assert event["type"] not in {"system.error", "request.failed"}, event
                        if event["type"] == "team.snapshot":
                            snapshots.append(event["payload"])
                        if event.get("request_id") == "req_research" and event["type"] == "request.cancelled":
                            terminals["req_research"] = event
                        if event.get("request_id") == "req_cancel" and event["type"] == "request.completed":
                            terminals["req_cancel"] = event
                assert time.monotonic() - started < 5
                assert terminals["req_cancel"]["payload"]["result"]["target_state"] == "cancelled"
                assert snapshots[-1]["status"] == "incomplete"
                assert all(agent["status"] != "working" for agent in snapshots[-1]["agents"])
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)

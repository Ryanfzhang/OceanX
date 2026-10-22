"""A browser connection reaches native task execution and immutable report delivery."""
import json
from uuid import uuid4

from starlette.testclient import TestClient

from oceanx.web.server import ProtocolBackend, WebSettings, create_app


class FixtureBackend(ProtocolBackend):
    server_module = "tests.test_oceanx.web_agent_server_fixture"


def test_web_native_task_reconnect_and_report_grant(tmp_path, monkeypatch):
    workspace = tmp_path / "project"; workspace.mkdir()
    frontend = tmp_path / "frontend"; frontend.mkdir()
    (frontend / "index.html").write_text('<div id="root"></div>')
    sources = tmp_path / "sources"; sources.mkdir()
    (sources / "data.csv").write_text("x,y\n1,2\n")
    monkeypatch.setenv("OCEAN_FIXTURE_MODE", "code")
    monkeypatch.setattr("oceanx.web.server.provider_status", lambda: {"configured": True})
    app = create_app(WebSettings(workspace, frontend, (sources,)), backend_factory=FixtureBackend)
    origin = "http://127.0.0.1:8765"
    with TestClient(app, base_url=origin) as client:
        ready = client.get("/api/config").json()["backend"]["readyEvent"]["payload"]
        context = {"client_id": ready["client_id"], "session_id": ready["session_id"], "workspace_id": "ws_desktop"}
        revision = 0
        task_revision = 0

        def frame(kind, payload):
            return {"protocol_version": 2, "request_id": "req_" + uuid4().hex,
                    "type": kind, "payload": payload, "context": dict(context),
                    "expected_workspace_revision": revision,
                    "expected_task_revision": task_revision}

        def terminal(ws, request):
            nonlocal revision, task_revision
            ws.send_json(request)
            while True:
                event = ws.receive_json()["payload"]
                body = event.get("payload", {})
                if isinstance(body.get("workspace_revision"), int):
                    revision = max(revision, body["workspace_revision"])
                if event.get("request_id") != request["request_id"]:
                    continue
                assert event["type"] not in {"request.failed", "system.error"}, json.dumps(event)
                if event["type"] == "request.completed":
                    result = body.get("result", {})
                    if isinstance(result.get("task"), dict):
                        task_revision = result["task"].get("task_revision", task_revision)
                    return result

        with client.websocket_connect("ws://127.0.0.1:8765/api/protocol", headers={"Origin": origin}) as ws:
            terminal(ws, frame("session.open", {"requested_workspace_id": "ws_desktop"}))
            opened = terminal(ws, frame("workspace.open", {"path": "web-project"}))
            assert str(workspace) not in json.dumps(opened)
            created = terminal(ws, frame("task.create", {"title": "Web native integration"}))
            task = created["task"]; context["task_id"] = task["task_id"]
            terminal(ws, frame("source.import", {"local_path": str(sources / "data.csv"), "title": "data.csv"}))
            opened = terminal(ws, frame("task.open", {"task_id": context["task_id"]}))
            task_revision = opened["task"]["task_revision"]
            request = frame("session.submit", {"text": "Compare formation and persistence.", "workflow_mode": "research", "literature_acquisition_mode": "search_only"})
            ws.send_json(request)
            while True:
                event = ws.receive_json()["payload"]
                if event["type"] == "request.accepted" and event.get("request_id") == request["request_id"]:
                    break
        # Closing a browser tab must not own or cancel the native run.
        assert app.state.backend.process.returncode is None
        with client.websocket_connect("ws://127.0.0.1:8765/api/protocol", headers={"Origin": origin}) as ws:
            import time
            deadline = time.monotonic() + 90
            while True:
                snapshot = terminal(ws, frame("task.open", {"task_id": context["task_id"]}))
                task_revision = snapshot["task"]["task_revision"]
                if not snapshot["task"].get("active_request_id"):
                    break
                assert time.monotonic() < deadline
                time.sleep(.3)
            outputs = terminal(ws, frame("task.output.list", {"task_id": context["task_id"], "limit": 500}))
            figures = [r for r in outputs["task_results"] if r["kind"] == "interactive_view"]
            assert figures, outputs
            figure = figures[-1]
            declared = next(f for f in figure["files"] if f["path"].endswith(".png"))
            granted = terminal(ws, frame("task_result.resource.grant", {
                "result_ref": figure["result_ref"], "file_name": declared["path"], "purpose": "result_file"}))
            assert "resource_uri" not in granted
            response = client.get("/api/resources/" + granted["resource_token"])
            assert response.status_code == 200
            assert response.content.startswith(b"\x89PNG")
            agents = snapshot["team_snapshots"][-1]["agents"]
            expert = next(a for a in agents if a.get("report_path") and a["authority"] != "coordinator")
            report = terminal(ws, frame("task.report.read", {
                "task_id": context["task_id"], "report_path": expert["report_path"]}))
            assert "Formation and persistence" in report["text"]

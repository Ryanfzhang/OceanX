"""The desktop's view of a project's lessons and tools: look, update now, mark right or wrong.
Also the real code-execution service: which helper functions each run called."""
import asyncio
import sys
import threading
from pathlib import Path

import pytest

from oceanx.backend.events import BackendClient
from oceanx.backend.host import OceanBackendHost
from oceanx.sandbox import get_sandbox_execution_capabilities


class _Recorder:
    def __init__(self) -> None:
        self.events = []

    async def send(self, event) -> None:
        self.events.append(event)

    def result(self, request_id: str) -> dict:
        [event] = [e for e in self.events if e.type == "request.completed" and e.request_id == request_id]
        return event.payload.result

    def failure(self, request_id: str):
        [event] = [e for e in self.events if e.type == "request.failed" and e.request_id == request_id]
        return event.payload

    def ended(self, request_id: str) -> bool:
        return any(e.request_id == request_id and e.type in ("request.completed", "request.failed")
                   for e in self.events)

    async def wait(self, request_id: str) -> None:
        """An update runs off the request loop: its reply comes after the request was taken."""
        for _ in range(500):
            if self.ended(request_id):
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"{request_id} did not end")


async def _open_project(host: OceanBackendHost, tmp_path: Path, workspace_id: str):
    """A desktop client with one open project."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    recorder = _Recorder()
    client = BackendClient(transport="stdio", expected_client_kind="desktop", sender=recorder.send)
    await host.event_bus.register(client)
    await host.router.handle_payload(client, {
        "protocol_version": 2, "request_id": "req_handshake", "type": "system.handshake",
        "payload": {"client_kind": "desktop", "client_version": "test", "supported_protocol_versions": [2]}})
    context = {"client_id": str(client.client_id), "session_id": str(client.session_id),
               "workspace_id": workspace_id}
    await host.router.handle_payload(client, {
        "protocol_version": 2, "request_id": "req_open", "type": "workspace.open",
        "payload": {"path": str(workspace)}, "context": context, "expected_workspace_revision": 0})
    return client, recorder, context


@pytest.mark.asyncio
async def test_library_requests_show_update_and_mark(tmp_path: Path, monkeypatch):
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_library")

        async def send(request_id: str, kind: str, payload: dict) -> None:
            await host.router.handle_payload(client, {
                "protocol_version": 2, "request_id": request_id, "type": f"research.library.{kind}",
                "payload": payload, "context": context})

        await send("req_get", "get", {})
        library = recorder.result("req_get")["library"]
        assert [skill["name"] for skill in library["skills"]] == [
            "claim-grounded-writing", "hypothesis-experiment-design", "ocean-analysis-design",
            "ocean-dataset-diagnosis", "ocean-physical-consistency-review", "research-trajectory-planning"]
        assert all(skill["lessons"] == [] and skill["limit"] >= 3 for skill in library["skills"])
        assert len(library["tools"]) == 8 and all(tool["shown"] for tool in library["tools"])
        assert library["version"] is None and library["changes"] == [] and library["tool_changes"] == []

        # Marking a tool wrong takes it off the list its skill shows; the reply is the new library.
        await send("req_mark", "mark", {"kind": "tool", "id": "small_sample", "verdict": "wrong"})
        marked = {tool["name"]: tool for tool in recorder.result("req_mark")["library"]["tools"]}
        assert (marked["small_sample"]["status"], marked["small_sample"]["human"],
                marked["small_sample"]["shown"]) == ("unlisted", "wrong", False)
        assert recorder.result("req_mark")["library"]["version"].startswith("tools@")
        assert recorder.result("req_mark")["library"]["tool_changes"][0]["by"] == "desktop user"

        await send("req_unknown", "mark", {"kind": "lesson", "id": "L404", "verdict": "right"})
        failed = recorder.failure("req_unknown")
        assert (failed.error.code, failed.error.message) == ("invalid_request", "Unknown lesson.")

        # "Update now" without a review needs no model: records and call counts only.
        await send("req_update", "update", {"review": False})
        await recorder.wait("req_update")
        updated = recorder.result("req_update")
        assert updated["update"]["consolidation"]["digested"] == 0
        assert updated["update"]["tool_usage"] == {"tasks_counted": 0, "removed": []}
        assert "lessons" not in updated["update"] and len(updated["library"]["tools"]) == 8

        # An experiment arm runs with a frozen library: the upkeep after a task changes nothing.
        monkeypatch.setenv("OCEANX_LIBRARY_FROZEN", "1")
        assert host.router._maintain_library("ws_library") is None
        monkeypatch.delenv("OCEANX_LIBRARY_FROZEN")
        # Regular upkeep keeps the counts current even when the meta-agent has no model.
        monkeypatch.setattr("oceanx.research.llm.default_llm", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("no meta model configured")))
        assert set(host.router._maintain_library("ws_library")) == {"consolidation", "tool_usage"}
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_update_now_does_not_hold_up_the_window(tmp_path: Path, monkeypatch):
    """A review reads every newly finished task's answer and takes minutes. The connection
    answers one request at a time, so the update runs beside it and replies when it is done."""
    from oceanx.research.review import ProjectResearch
    started, release, calls = threading.Event(), threading.Event(), []

    def slow_update(self, stores, **options):  # the meta-agent at work
        calls.append(options["llm"] is not None)
        started.set()
        assert release.wait(20)
        return {"consolidation": {"digested": 0}, "tool_usage": {"tasks_counted": 0, "removed": []}}

    monkeypatch.setattr(ProjectResearch, "update", slow_update)
    monkeypatch.setattr("oceanx.research.llm.default_llm", lambda *a, **k: lambda prompt: "{}")
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_busy")

        async def send(request_id: str, kind: str, payload: dict) -> None:
            await host.router.handle_payload(client, {
                "protocol_version": 2, "request_id": request_id, "type": f"research.library.{kind}",
                "payload": payload, "context": context})

        await send("req_update", "update", {"review": True})  # returns at once
        assert await asyncio.to_thread(started.wait, 20) and not recorder.ended("req_update")
        # Meanwhile the window is answered: the library can be read, a task created.
        await send("req_get", "get", {})
        assert len(recorder.result("req_get")["library"]["tools"]) == 8
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_task", "type": "task.create",
            "payload": {"title": "meanwhile"}, "context": context})
        assert recorder.result("req_task")["task"]["title"] == "meanwhile"
        # The running update will write the library back, so a mark now would be lost: refused.
        await send("req_mark", "mark", {"kind": "tool", "id": "small_sample", "verdict": "wrong"})
        failed = recorder.failure("req_mark")
        assert failed.error.code == "invalid_request" and "being updated" in failed.error.message
        # The upkeep after a research request leaves the work to the update that is running,
        # and a second "Update now" waits its turn.
        assert await asyncio.to_thread(host.router._maintain_library, "ws_busy") is None
        await send("req_again", "update", {"review": False})
        await asyncio.sleep(0.05)
        assert calls == [True] and not recorder.ended("req_again")

        release.set()
        await recorder.wait("req_update")
        await recorder.wait("req_again")
        assert recorder.result("req_update")["update"]["consolidation"] == {"digested": 0}
        assert len(recorder.result("req_update")["library"]["tools"]) == 8 and calls == [True, False]
        # With no update running the mark is made.
        await send("req_mark_again", "mark", {"kind": "tool", "id": "small_sample", "verdict": "wrong"})
        marked = {tool["name"]: tool for tool in recorder.result("req_mark_again")["library"]["tools"]}
        assert marked["small_sample"]["human"] == "wrong"

        # A model failure ends the request with an error the dialog shows, as before.
        monkeypatch.setattr(ProjectResearch, "update", lambda self, stores, **options: (_ for _ in ()).throw(
            RuntimeError("provider refused")))
        await send("req_broken", "update", {"review": True})
        await recorder.wait("req_broken")
        broken = recorder.failure("req_broken")
        assert (broken.error.code, broken.error.details["reason"]) == ("model_error", "provider refused")
        assert not host.router._library_updates and not host.router._library_lock.locked()
    finally:
        release.set()
        await host.close()


@pytest.mark.asyncio
async def test_closing_the_backend_does_not_wait_for_an_update(tmp_path: Path, monkeypatch):
    from oceanx.research.review import ProjectResearch
    started, release = threading.Event(), threading.Event()

    def slow_update(self, stores, **options):
        started.set()
        release.wait(20)
        return {}

    monkeypatch.setattr(ProjectResearch, "update", slow_update)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_close")
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_update", "type": "research.library.update",
            "payload": {"review": False}, "context": context})
        assert await asyncio.to_thread(started.wait, 20)
        await asyncio.wait_for(host.router.shutdown_active_analysis(), timeout=5)
        assert not host.router._library_updates and not recorder.ended("req_update")
        # Request recovery ends what was left in progress, as it does for a research request.
        assert "req_update" in {event.request_id for event in host.router.interrupt_active_requests()}
    finally:
        release.set()
        await host.close()


SCRIPT = """cat > probe.py <<'PY'
import oceanx_array_ops as ao
for _ in range(3):
    ao.rate_per_day(2.0, input_unit='per_second')
PY
python probe.py"""


@pytest.mark.asyncio
async def test_every_code_run_records_the_helper_functions_it_called(tmp_path: Path, monkeypatch):
    capabilities = get_sandbox_execution_capabilities()
    if not capabilities.available:
        pytest.skip(capabilities.reason or "sandbox backend is unavailable")
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_tools")
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_task", "type": "task.create",
            "payload": {"title": "tools"}, "context": context})
        task_id = recorder.result("req_task")["task"]["task_id"]
        run = {"workspace_id": "ws_tools", "task_id": task_id, "agent_thread_id": "physics", "server_run_id": "run"}
        service = host.expert_code_execution
        # The kernel path: ``ao`` is there without an import.
        kernel = await service.run_python(**run, purpose="kernel", code=(
            "import numpy as np, xarray as xr\n"
            "field = xr.DataArray(np.ones((2, 3)), dims=('lat', 'lon'))\n"
            "weights = xr.DataArray(np.ones(2), dims=('lat',))\n"
            "print(float(ao.weighted_mean(field, weights, dims=('lat', 'lon'))))\n"
            "print(ao.rate_per_day(1.0, input_unit='per_day'))\n"))
        assert kernel.state == "succeeded", kernel.as_payload()
        assert kernel.tool_calls == {"rate_per_day": 1, "weighted_mean": 1}
        # The script path: a script the Expert runs itself imports the same module.
        shell = await service.run_shell(**run, command=SCRIPT)
        assert shell.state == "succeeded", shell.as_payload()
        assert shell.tool_calls == {"rate_per_day": 3}
        # What the Coordinator reads when the task ends, to record the task's tool use.
        records = host.store.list_task_code_executions(workspace_id="ws_tools", task_id=task_id)
        assert [(record.result or {}).get("tool_calls") for record in records] == [
            {"rate_per_day": 1, "weighted_mean": 1}, {"rate_per_day": 3}]
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_a_research_task_records_the_library_it_ran_with(tmp_path: Path, monkeypatch):
    pytest.importorskip("deepagents")
    from oceanx.research import graphs
    from oceanx.research.memory import build_digest
    from oceanx.research.outcomes import record_task_outcomes
    monkeypatch.delenv("OCEANX_RESEARCH_POLICY", raising=False)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        await _open_project(host, tmp_path, "ws_record")
        task = host.store.create_research_task(workspace_id="ws_record", title="Library record")
        monkeypatch.setattr(graphs, "host", lambda: host)
        project = graphs._project()
        # Nothing learned: the tree is bound to the policy alone.
        plain = graphs.research_tree(task.task_id)
        assert plain.policy_version == project.policy().version and plain.policy_version.startswith("policy/v2-nested@")
        project.lessons._save([{
            "id": "L001", "skill": "research-trajectory-planning", "role": "coordinator",
            "text": "Test rivals first.", "applies_when": "Two drivers remain.", "status": "active", "human": None,
            "evidence": {"supporting": [], "counter": []}, "added_at": "2026-10-01T00:00:00+00:00"}])
        project.mark("tool", "small_sample", "wrong")
        tree = graphs.research_tree(task.task_id)
        assert tree.policy_version == f"{project.policy().version}+{project.version()}"
        assert "+lessons@" in tree.policy_version and "+tools@" in tree.policy_version
        # The task ends: an Expert's report named the lesson, the final report did not.
        report = tmp_path / "report.md"
        report.write_text("Result: the rival was tested first, following L001.")
        tree.update([{"action": "add", "target": "ROOT", "question": "Why warm?"},
                     {"action": "add", "target": "B1", "question": "Budget?", "status": "selected"}])
        tree.attach_result("B1.1", summary="Result: Flux.\nEvidence and limitations: One year.\nFurther analysis: None",
                           agent_key="physics", report_path=str(report), attempt_id="a")
        record = graphs._library_record(tree, "## Summary\nFlux explains it.")
        mounted = [tool["name"] for tool in project.tools.mounted()]
        assert record == {"lessons_shown": ["L001"], "lessons_cited": ["L001"], "tools_mounted": mounted}
        assert len(mounted) == 7 and "small_sample" not in mounted
        record_task_outcomes(tree, final_report="## Summary\nFlux explains it.", model_calls=[],
                             code_executions=[{"agent_thread_id": "physics", "state": "succeeded",
                                               "tool_calls": {"weighted_mean": 2}}], library=record)
        digest = build_digest(tree.store.path)
        assert (digest["lessons_shown"], digest["lessons_cited"]) == (["L001"], ["L001"])
        assert (digest["tools_mounted"], digest["tool_calls"]) == (mounted, {"weighted_mean": 2})
        assert digest["policy_versions"][-1] == tree.policy_version
    finally:
        await host.close()

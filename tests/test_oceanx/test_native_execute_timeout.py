"""An agent's commands and code run until they end: no time limit stops them (2026-11-02)."""
import asyncio
import sys
from types import SimpleNamespace

import pytest

from oceanx.native_backend import ResearchSandbox


def test_a_failed_command_keeps_its_output_unchanged(tmp_path):
    async def record_command(command):
        del command
        return SimpleNamespace(stdout="partial\n", stderr="", returncode=1, state="failed",
                               duration_seconds=3.0, figure_notes=())

    sandbox = ResearchSandbox(service=SimpleNamespace(), work_root=tmp_path, read_roots=lambda: (),
                              record_command=record_command)
    response = asyncio.run(sandbox.aexecute("false", timeout=60))
    assert response.output == "partial\n" and response.exit_code == 1


@pytest.mark.asyncio
async def test_no_time_limit_stops_an_agents_command_or_code(tmp_path, monkeypatch):
    """At 120 s a run of 2026-11-01 read every tenth day of a daily record. The single agent's, an Expert's
    and the Coordinator's commands, also when they ask for a timeout, and an agent's Python run until they
    end; the researcher's stop ends them sooner."""

    from oceanx import expert_execution, native_backend
    from oceanx.backend.host import OceanBackendHost
    from oceanx.native_backend import task_backend
    from tests.test_oceanx.test_research_library_router import _open_project

    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    limits = []

    async def stopped(*_args, policy, **_kwargs):
        limits.append(policy.limits.wall_time_seconds)
        raise RuntimeError("stopped before running")

    monkeypatch.setattr(expert_execution, "run_sandboxed_command", stopped)
    monkeypatch.setattr(native_backend, "run_sandboxed_command", stopped)  # the Coordinator's own commands
    for part in ("skills", "references"):
        (tmp_path / "library" / part).mkdir(parents=True)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        monkeypatch.setattr(host.expert_code_execution.kernels, "execute", stopped)  # an agent's Python
        client, recorder, context = await _open_project(host, tmp_path, "ws_limits")
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_task", "type": "task.create",
            "payload": {"title": "limits"}, "context": context})
        task_id = recorder.result("req_task")["task"]["task_id"]
        agent = SimpleNamespace(thread_id="single-agent-x", server_run_id="run")
        for mode, run in (("standard", agent), ("research", agent), ("research", None)):  # None: the Coordinator
            config = {"configurable": {"workspace_id": "ws_limits", "task_id": task_id, "request_id": "r",
                                       "request_options": {"workflow_mode": mode}}}
            backend, _ = task_backend(host, config, run=run, library=tmp_path / "library")
            for asked in (None, 60):
                with pytest.raises(RuntimeError, match="stopped before running"):
                    await backend.aexecute("python long.py", timeout=asked)
        with pytest.raises(RuntimeError, match="stopped before running"):
            await host.expert_code_execution.run_python(
                workspace_id="ws_limits", task_id=task_id, agent_thread_id="single-agent-x",
                server_run_id="run", purpose="Read every day", code="print(1)")
    finally:
        await host.close()
    assert limits == [0] * 7  # 0: no wall-time limit

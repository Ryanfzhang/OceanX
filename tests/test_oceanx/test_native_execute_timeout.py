"""An agent's commands and code run until they end: no time limit stops them (2026-11-02), unless a
benchmark's research time budget is nearly used, when an agent's code stops so that the run ends with a
report."""
import asyncio
import json
import sys
import time
from types import SimpleNamespace

import pytest

from oceanx.expert_execution import BUDGET_STOP_NOTE, ExpertCodeExecutionResult
from oceanx.native_backend import ResearchSandbox
from oceanx.research.budget import RESEARCH_BUDGET_ENV


def test_a_failed_command_keeps_its_output_unchanged(tmp_path):
    async def record_command(command):
        del command
        return SimpleNamespace(stdout="partial\n", stderr="", returncode=1, state="failed",
                               duration_seconds=3.0, figure_notes=(), limit_trigger=None)

    sandbox = ResearchSandbox(service=SimpleNamespace(budget_note=lambda trigger: None), work_root=tmp_path,
                              read_roots=lambda: (), record_command=record_command)
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
    monkeypatch.delenv(RESEARCH_BUDGET_ENV, raising=False)
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


@pytest.mark.asyncio
async def test_a_research_budget_stops_an_agents_code_in_time_for_the_report(tmp_path, monkeypatch):
    """A benchmark run sets a research time budget. With code unlimited, an Expert that began a long
    computation late would hold the run until it was cut off without a report, so an agent's code stops
    at 85% of the budget and the agent is told to report. The file helpers that read reports keep no
    limit."""
    from oceanx.backend.host import OceanBackendHost
    from oceanx.tools import OceanExpertRunCodeInput, OceanExpertRunCodeTool, OceanToolServices

    monkeypatch.setenv(RESEARCH_BUDGET_ENV, "180")
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        service = host.expert_code_execution
        assert 0 < service.run_limits().wall_time_seconds <= 0.85 * 180 * 60
        service.code_deadline = time.monotonic() - 1  # 85% of the budget has passed
        assert service.run_limits().wall_time_seconds == 1.0  # a run that starts now stops at once
        assert service.limits.wall_time_seconds == 0  # the file helpers' commands
        assert service.budget_note("wall_time") == BUDGET_STOP_NOTE and service.budget_note(None) is None

        async def record_command(command):
            del command
            return SimpleNamespace(stdout="2011 done\n", stderr="", returncode=None, figure_notes=(),
                                   limit_trigger="wall_time")

        sandbox = ResearchSandbox(service=service, work_root=tmp_path / "agent", read_roots=lambda: (),
                                  record_command=record_command)
        assert (await sandbox.aexecute("python every_day.py")).output == f"2011 done\n\n[{BUDGET_STOP_NOTE}]\n"

        async def run_python(**_kwargs):
            return ExpertCodeExecutionResult(
                execution_id="e", state="timed_out", returncode=None, stdout="2011 done\n", stderr="",
                duration_seconds=1.0, output_files=(), outputs=(), output_bytes=0, limit_trigger="wall_time",
                code_path="analysis.py", work_root=str(tmp_path / "agent"), result_bundle_path="result.json",
                result_fingerprint="f", attempt_number=1, attempt_limit=1)

        tool = OceanExpertRunCodeTool(OceanToolServices(
            workspace_id="ws", provider_id="p", store=SimpleNamespace(), task_id="t", agent_thread_id="a",
            server_run_id="r",
            expert_code_execution=SimpleNamespace(run_python=run_python, budget_note=service.budget_note)))
        result = await tool.execute(OceanExpertRunCodeInput(purpose="Read every day", code="read()"), None)
        assert json.loads(result.output)["stopped"] == BUDGET_STOP_NOTE
    finally:
        await host.close()

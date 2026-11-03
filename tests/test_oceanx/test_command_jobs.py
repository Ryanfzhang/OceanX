"""A command of the single agent or a helper still running after ten minutes goes on as a job (command_jobs.py).

On 2026-11-03 a command that ran for an hour by accident held the single agent past its request's time rules,
which act between model calls. The team's commands still wait until they end."""
import asyncio
import os
import sys
import time
from types import SimpleNamespace

import pytest

from oceanx.command_jobs import JOB_OUTPUT_CHARS, CommandJob, CommandJobs
from oceanx.native_backend import ResearchSandbox
from oceanx.tools import (
    OceanCheckJobInput,
    OceanCheckJobTool,
    OceanStopJobInput,
    OceanStopJobTool,
    OceanToolServices,
)


def _result(stdout="", returncode=0, figure_notes=()):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode, figure_notes=figure_notes,
                           limit_trigger=None)


def _service():
    return SimpleNamespace(jobs=CommandJobs(), budget_note=lambda trigger: None)


def _tools(service, task_id="task-1"):
    services = OceanToolServices(workspace_id="ws", provider_id="p", store=SimpleNamespace(), task_id=task_id,
                                 expert_code_execution=service)
    return OceanCheckJobTool(services), OceanStopJobTool(services)


def _sandbox(service, tmp_path, record_command, *, task_id="task-1", wait_seconds=0.05):
    return ResearchSandbox(service=service, work_root=tmp_path, read_roots=lambda: (),
                           record_command=record_command, task_id=task_id, wait_seconds=wait_seconds)


@pytest.mark.asyncio
async def test_a_command_that_ends_within_the_wait_is_answered_as_before(tmp_path):
    async def record_command(command, on_output=None):
        on_output("stdout", b"mean 28.1\n")
        return _result("mean 28.1\n", figure_notes=("fig.pdf: its text is stored as outlines",))

    service = _service()
    response = await _sandbox(service, tmp_path, record_command, wait_seconds=5).aexecute("python mean.py")
    assert response.exit_code == 0
    assert response.output == "mean 28.1\n\n[Figure check] fig.pdf: its text is stored as outlines\n"
    assert service.jobs.jobs == {}


@pytest.mark.asyncio
async def test_the_teams_commands_wait_until_they_end(tmp_path):
    async def record_command(command):  # the team's execute passes no output callback
        await asyncio.sleep(0.2)
        return _result("all years done\n", returncode=1)

    service = _service()
    sandbox = ResearchSandbox(service=service, work_root=tmp_path, read_roots=lambda: (),
                              record_command=record_command)
    response = await sandbox.aexecute("python all_years.py")
    assert response.output == "all years done\n" and response.exit_code == 1
    assert service.jobs.jobs == {}


@pytest.mark.asyncio
async def test_a_long_command_goes_on_as_a_job_that_check_job_follows_to_its_end(tmp_path):
    second_year, release = asyncio.Event(), asyncio.Event()

    async def record_command(command, on_output=None):
        on_output("stdout", b"2011 done\n")
        await second_year.wait()
        on_output("stdout", b"2012 done\n")
        await release.wait()
        return _result("2011 done\n2012 done\n", figure_notes=("fig3.pdf: its text is stored as outlines",))

    service = _service()
    response = await _sandbox(service, tmp_path, record_command).aexecute("python years.py")
    (job,) = service.jobs.jobs.values()
    assert response.exit_code is None and response.output.startswith("2011 done\n")
    assert f"goes on as job {job.job_id}" in response.output and "Do not start it again" in response.output
    check, _stop = _tools(service)

    looked = await check.execute(OceanCheckJobInput(job_id=job.job_id, wait_minutes=0), None)
    assert looked.output == f"\n[Job {job.job_id} is still running after 0 minutes.]"  # 2011 was shown already
    second_year.set()
    await asyncio.sleep(0.01)
    looked = await check.execute(OceanCheckJobInput(job_id=job.job_id, wait_minutes=0), None)
    assert looked.output.startswith("2012 done\n") and "still running" in looked.output
    listed = await check.execute(OceanCheckJobInput(), None)
    assert f"- {job.job_id}, running for 0 minutes: python years.py" in listed.output

    release.set()
    ended = await check.execute(OceanCheckJobInput(job_id=job.job_id, wait_minutes=1), None)
    assert "2012" not in ended.output and "[Figure check] fig3.pdf" in ended.output
    assert ended.output.endswith(
        f"[Job {job.job_id}: the command succeeded with exit code 0 after 0 minutes.]")
    assert "no job has ended unchecked" in (await check.execute(OceanCheckJobInput(), None)).output
    gone = await check.execute(OceanCheckJobInput(job_id=job.job_id), None)
    assert gone.is_error and "has no job" in gone.output  # an end is shown once


def test_a_job_keeps_whole_characters_and_the_last_output_its_agent_has_not_seen():
    job = CommandJob(task_id="task-1", command="python years.py")
    text = "温度".encode()
    job.add_output("stdout", text[:4])  # a character split between two pieces
    job.add_output("stdout", text[4:])
    assert job.take_output() == "温度"
    job.add_output("stderr", b"x" * (JOB_OUTPUT_CHARS + 10))
    shown = job.take_output()
    assert shown == "[10 earlier characters left out]\n" + "x" * JOB_OUTPUT_CHARS
    assert job.take_output() == ""


@pytest.mark.asyncio
async def test_stop_job_and_the_researchers_stop_end_jobs_of_their_own_task_only(tmp_path, monkeypatch):
    from oceanx.research import graphs

    stopped = []

    def record(name):
        async def record_command(command, on_output=None):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopped.append(name)
                raise
        return record_command

    service = _service()
    for task_id, name in (("task-1", "a"), ("task-1", "b"), ("task-2", "c")):
        sandbox = _sandbox(service, tmp_path / name, record(name), task_id=task_id)
        assert "goes on as job" in (await sandbox.aexecute(f"python {name}.py")).output
    ids = {job.command: job.job_id for job in service.jobs.jobs.values()}
    check, stop = _tools(service)

    ended = await stop.execute(OceanStopJobInput(job_id=ids["python a.py"]), None)
    assert ended.output.endswith(f"[Job {ids['python a.py']} was stopped after 0 minutes.]") and stopped == ["a"]
    other = await stop.execute(OceanStopJobInput(job_id=ids["python c.py"]), None)
    assert other.is_error and stopped == ["a"]  # another task's job

    monkeypatch.setattr(graphs, "host", lambda: SimpleNamespace(expert_code_execution=service))
    await graphs._stop_jobs("task-1")
    assert stopped == ["a", "b"]
    assert (await check.execute(OceanCheckJobInput(job_id=ids["python b.py"]), None)).output.endswith(
        f"[Job {ids['python b.py']} was stopped after 0 minutes.]")
    await service.jobs.stop_all()  # what the backend does when it closes
    assert stopped == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_a_stop_during_the_wait_stops_the_command(tmp_path):
    stopped = asyncio.Event()

    async def record_command(command, on_output=None):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.set()
            raise

    service = _service()
    call = asyncio.create_task(_sandbox(service, tmp_path, record_command, wait_seconds=60).aexecute("python x.py"))
    await asyncio.sleep(0.05)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert stopped.is_set() and service.jobs.jobs == {}


@pytest.mark.asyncio
async def test_a_real_command_is_handed_back_with_its_output_and_stop_job_ends_its_process(tmp_path, monkeypatch):
    """Through the real service and sandbox: Python's prints reach the agent while the command runs, the
    run's record stays open while it goes on, and a stop ends the process and records the run cancelled."""
    from oceanx.backend.host import OceanBackendHost
    from oceanx.native_backend import task_backend
    from oceanx.sandbox import get_sandbox_execution_capabilities
    from tests.test_oceanx.test_research_library_router import _open_project

    capabilities = get_sandbox_execution_capabilities()
    if not capabilities.available:
        pytest.skip(capabilities.reason or "sandbox backend is unavailable")
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    for part in ("skills", "references"):
        (tmp_path / "library" / part).mkdir(parents=True)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_jobs")
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_task", "type": "task.create",
            "payload": {"title": "jobs"}, "context": context})
        task_id = recorder.result("req_task")["task"]["task_id"]
        config = {"configurable": {"workspace_id": "ws_jobs", "task_id": task_id, "request_id": "r"}}
        agent = SimpleNamespace(thread_id="single-agent-x", server_run_id="run")
        backend, scratch = task_backend(host, config, run=agent, library=tmp_path / "library", wait_seconds=3)
        response = await backend.aexecute(
            "python -c \"import os, time; open('pid', 'w').write(str(os.getpid())); print('2011 done'); "
            "time.sleep(120)\"")
        assert response.exit_code is None and response.output.startswith("2011 done\n"), response.output
        (job,) = host.expert_code_execution.jobs.jobs.values()
        (record,) = host.store.list_task_code_executions(workspace_id="ws_jobs", task_id=task_id)
        assert record.state == "running"
        pid = int((scratch / "pid").read_text())

        _check, stop = _tools(host.expert_code_execution, task_id)
        ended = await stop.execute(OceanStopJobInput(job_id=job.job_id), None)
        assert ended.output.endswith("was stopped after 0 minutes.]")
        (record,) = host.store.list_task_code_executions(workspace_id="ws_jobs", task_id=task_id)
        assert record.state == "cancelled"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("the job's process outlived stop_job")
    finally:
        await host.close()

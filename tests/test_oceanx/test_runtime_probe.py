"""A capability observation cannot become an Expert admission gate."""

import asyncio
import hashlib
import json
import subprocess
import threading
from types import SimpleNamespace

import pytest

from oceanx.expert_execution import (
    ExpertCodeExecutionService,
    ExpertMountedSource,
    ExpertRuntimeUnavailableError,
)
from oceanx.sandbox import execution
from oceanx.sandbox.runtime_probe import SCIENTIFIC_MODULES, RuntimeCapabilityProbe


def test_identity_inspection_imports_no_science_and_caches_only_success(tmp_path, monkeypatch):
    executable = tmp_path / "python"
    attempts = []

    def run(command, **kwargs):
        attempts.append(command)
        assert "importlib.import_module" not in command[2]
        assert "checked_modules" not in command[2]
        if len(attempts) == 1:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return SimpleNamespace(stdout=json.dumps({
            "prefix": str(tmp_path), "version": "3.11", "requirements": [],
            "site_packages": [], "paths": [],
        }))

    monkeypatch.setattr(execution.subprocess, "run", run)
    with pytest.raises(execution.SandboxUnavailableError, match="timed out"):
        execution._inspect_python_runtime(executable)
    assert execution._inspect_python_runtime(executable).version == "3.11"
    execution._inspect_python_runtime(executable)
    assert len(attempts) == 2


def test_background_probe_does_not_wait_for_interpreter(monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    probe = RuntimeCapabilityProbe()

    def slow_probe():
        entered.set()
        release.wait(5)
        finished.set()

    monkeypatch.setattr(probe, "_run", slow_probe)
    try:
        facts = probe.snapshot()
        assert facts["state"] == "unknown"
        assert facts["modules"] == {}
        assert entered.wait(1)
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(1)


def test_timeout_preserves_confirmed_modules_and_retries_unknowns(tmp_path, monkeypatch):
    from oceanx.sandbox import runtime_probe
    probe = RuntimeCapabilityProbe()
    monkeypatch.setattr(runtime_probe, "current_python_runtime", lambda: SimpleNamespace(
        executable=tmp_path / "python", prefix=tmp_path, version="3.11", environment_name="fixture",
    ))
    calls = []

    def run(command, **kwargs):
        modules = json.loads(command[-1])
        calls.append(modules)
        if len(calls) == 1:
            output = json.dumps({"module": "numpy", "status": "available"}) + "\n"
            output += json.dumps({"module": "cartopy", "status": "unavailable",
                                  "error": "ModuleNotFoundError: cartopy"}) + "\n"
            raise subprocess.TimeoutExpired(command, 60, output=output.encode())
        return SimpleNamespace(returncode=0, stdout="\n".join(
            json.dumps({"module": name, "status": "available"}) for name in modules
        ), stderr="")

    monkeypatch.setattr(runtime_probe.subprocess, "run", run)
    probe._run()
    facts = probe.snapshot()
    assert facts["state"] == "incomplete"
    assert set(facts["modules"]) == {"numpy", "cartopy"}
    assert len(calls) == 1  # Reading diagnostics never loops/retries automatically.
    probe._run()
    assert "numpy" not in calls[1] and "cartopy" not in calls[1]
    assert probe.snapshot()["state"] == "complete"
    assert len(probe.snapshot()["modules"]) == len(SCIENTIFIC_MODULES)


def test_code_runtime_retries_failure_without_restarting_backend(tmp_path, monkeypatch):
    service = object.__new__(ExpertCodeExecutionService)
    service._runtime = None
    service._runtime_error = None
    calls = []

    def inspect():
        calls.append(1)
        if len(calls) == 1:
            raise execution.SandboxUnavailableError("inspection timed out")
        return SimpleNamespace(executable=tmp_path / "python", prefix=tmp_path,
                               environment_name="fixture", version="3.11", read_roots=(),
                               package_roots=(), requirements=())

    monkeypatch.setattr("oceanx.expert_execution.current_python_runtime", inspect)
    with pytest.raises(ExpertRuntimeUnavailableError, match="timed out"):
        service.require_runtime()
    assert service.require_runtime().version == "3.11"
    assert service.runtime_unavailable_reason is None
    service.require_runtime()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_context_ignores_old_failure_cache_and_does_not_require_python(tmp_path):
    service = object.__new__(ExpertCodeExecutionService)
    service._task_dataset_contexts = {}
    service._analysis_context_locks = {}
    service.task_workspaces = SimpleNamespace(ensure_task_root=lambda _: tmp_path)

    def forbidden():
        pytest.fail("Metadata handoff must not launch Python")

    service.require_runtime = forbidden
    source = ExpertMountedSource(
        ref=SimpleNamespace(key="dataset:v1"), handle="source_1", title="GLORYS",
        kind="dataset", paths=(),
        manifest={"path": "/data/glorys.nc", "variables": ["temperature"]},
    )
    cache_root = tmp_path / ".runtime" / "analysis-context"
    cache_root.mkdir(parents=True)
    cache_path = cache_root / (hashlib.sha256(b"dataset:v1").hexdigest()[:32] + ".json")
    cache_path.write_text(json.dumps({"sources": [{"inspection": "unavailable", "error": "timeout"}]}))
    context = await service.get_task_dataset_context(
        workspace_id="ws", task_id="task", sources=(source,), inspect_files=False,
    )
    assert context["sources"][0]["path"] == "/data/glorys.nc"
    assert context["sources"][0]["inspection"] == "not_run"
    assert service._task_dataset_contexts == {}
    # A concurrent metadata probe must not make another Expert wait on its lock.
    lock = service._analysis_context_locks["task:dataset:v1"]
    async with lock:
        context = await asyncio.wait_for(service.get_task_dataset_context(
            workspace_id="ws", task_id="task", sources=(source,), inspect_files=False,
        ), timeout=0.5)
        assert context["sources"][0]["path"] == "/data/glorys.nc"


def test_doctor_reports_unknown_not_missing(monkeypatch):
    from oceanx import doctor
    monkeypatch.setattr(doctor, "runtime_capabilities", lambda: {
        "state": "unknown", "interpreter": None, "modules": {}, "note": "probe pending",
    })
    report = doctor.ocean_doctor()
    assert report["extras"]["cartopy"]["available"] is None
    assert report["extras"]["cartopy"]["status"] == "unknown"
    assert report["unavailable_reasons"]["maps"] is None


def test_runtime_probe_errors_are_advisory_and_retryable(monkeypatch):
    from oceanx.sandbox import runtime_probe
    probe = RuntimeCapabilityProbe()

    def unavailable():
        raise execution.SandboxUnavailableError("interpreter inspection timed out")

    monkeypatch.setattr(runtime_probe, "current_python_runtime", unavailable)
    probe._run()
    assert probe.snapshot()["state"] == "incomplete"
    assert probe.snapshot()["modules"] == {}
    assert probe.snapshot()["interpreter"] is None


@pytest.mark.parametrize("sources", [
    [{"inspection": "unavailable", "error": "timeout"}],
    [{"inspection": "not_run"}],
    [{}],
    [{"inspection": "ready", "members": [{"inspection": "unavailable", "error": "timeout"}]}],
    [],
])
def test_unconfirmed_metadata_is_not_cached(sources):
    assert not ExpertCodeExecutionService._context_is_confirmed(sources)

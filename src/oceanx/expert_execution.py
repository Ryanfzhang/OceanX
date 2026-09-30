"""Task-scoped code execution owned directly by an OceanX Expert."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from oceanx.artifacts.models import ArtifactRef
from oceanx.backend.store import CodeExecutionRecord, RequestStore
from oceanx.datasets import resolve_dataset_source
from oceanx.execution_manifest import (
    execution_result_fingerprint,
    write_execution_result_manifest,
)
from oceanx.sandbox import (
    ResourceLimits,
    SandboxExecutionPolicy,
    SandboxUnavailableError,
    current_python_runtime,
    run_sandboxed_command,
)
from oceanx.sandbox.execution import POSIX_SHELL, shell_runtime_roots
from oceanx.sandbox.runtime_probe import runtime_capabilities
from oceanx.storage import OceanPaths, StoragePolicyError
from oceanx.task_workspace import TaskWorkspaceProjector

FIGURE_IMPORT = "from oceanx.scientific_view import ScientificFigure"

# Per-run wall-time cap for bounded (standard-mode) requests; research keeps the default 300 s.
STANDARD_MODE_CODE_SECONDS = 120


FIGURE_API_CONTRACT = {
    "contract_version": "oceanx-scientific-figure-python/v4",
    "constructor": (
        "ScientificFigure(*, plot_kind, title, subtitle='', caption='', columns=1, "
        "spatial_context=None, source_handle=None, conclusions=())"
    ),
    "rule": (
        "The Expert supplies the computed arrays and complete scientific visual structure. "
        "Create panels with explicit axes, then add line, scatter, field2d, categories, band, "
        "vector, contour, annotation or reference layers. Figure.save('name.nc') is the explicit "
        "user-facing result boundary. Ordinary NetCDF files are data files and are not displayed. "
        "For spatial fields, preserve the scientific validity mask: land and cells outside the "
        "analysis domain are missing, not plotted values; every spatial field must pass "
        "field2d(..., valid_mask=...). "
        "Omit style arguments to use the Workbench defaults; specify them only when the scientific "
        "figure needs a deliberate override."
    ),
    "examples": [
        (
            "fig = ScientificFigure(plot_kind='time_series', title='Regional temperature'); "
            "panel = fig.panel(x=time, y=bay, x_label='Time', y_label='Temperature', "
            "y_units='degC'); panel.line(label='Bay'); "
            "panel.line(x=time, y=gulf, label='Gulf'); fig.save('comparison.nc')"
        ),
        (
            "fig = ScientificFigure(plot_kind='spatial_map', title='Temperature anomaly'); "
            "panel = fig.panel(x=longitude, y=latitude, x_label='Longitude', y_label='Latitude'); "
            "panel.field2d(anomaly, valid_mask=wet_cells, variable='temperature_anomaly', units='degC', "
            "palette='blue_red', color_domain=[-3, 3], colorbar_label='Temperature anomaly (degC)'); "
            "fig.save('anomaly.nc')"
        ),
        (
            "fig = ScientificFigure(plot_kind='scatter', title='Paired observations'); "
            "panel = fig.panel(x=observed, y=modelled, x_label='Observed', y_label='Modelled'); "
            "panel.scatter(opacity=0.2, radius=1.0); "
            "panel.line(x=limits, y=limits, label='1:1'); fig.save('paired.nc')"
        ),
    ],
}

_RESULT_RUNNER = '''"""Framework entry point for one OceanX analysis program."""

from __future__ import annotations

import sys
from pathlib import Path

from oceanx.scientific_view import ScientificFigure


def main() -> None:
    script = Path(sys.argv[1]).resolve()
    sys.argv = [str(script)]
    namespace = {
        "__name__": "__main__",
        "__file__": str(script),
        "__package__": None,
        "ScientificFigure": ScientificFigure,
    }
    source = script.read_text(encoding="utf-8")
    exec(compile(source, str(script), "exec"), namespace, namespace)


if __name__ == "__main__":
    main()
'''


class ExpertCodeExecutionError(RuntimeError):
    """An Expert code request violates its task or input boundary."""


class ExpertRuntimeUnavailableError(ExpertCodeExecutionError):
    """The backend cannot safely execute Expert-authored Python in this process."""


def _result_support_source(name: str) -> Path:
    source = Path(__file__).resolve().with_name(name)
    if not source.is_file():
        raise ExpertRuntimeUnavailableError(f"The result runtime support file is missing: {name}")
    return source


def _analysis_probe_source() -> Path:
    source = Path(__file__).resolve().with_name("analysis_probe.py")
    if not source.is_file():
        raise ExpertRuntimeUnavailableError("The AnalysisContext probe is missing")
    return source


def _install_result_runtime(code_root: Path) -> None:
    """Install the small public result API and private deterministic renderer."""
    package_root = code_root / "oceanx"
    package_root.mkdir(parents=True, exist_ok=True)
    for support_name in ("scientific_view.py", "figure_preview.py", "figure_reproduction.py", "palettes.py"):
        shutil.copy2(_result_support_source(support_name), package_root / support_name)
    shutil.copy2(Path(__file__).resolve().parent / "resources" / "skills" / "core" /
                 "xarray-array-ops" / "scripts" / "oceanx_array_ops.py", code_root / "oceanx_array_ops.py")
    (package_root / "__init__.py").write_text(
        '"""OceanX sandbox runtime support."""\n\n'
        "from .scientific_view import ScientificFigure, ScientificPanel\n\n"
        '__all__ = ["ScientificFigure", "ScientificPanel"]\n',
        encoding="utf-8",
    )
    (code_root / "_oceanmind_runner.py").write_text(
        _RESULT_RUNNER,
        encoding="utf-8",
    )


@dataclass(frozen=True)
class ExpertCodeExecutionResult:
    execution_id: str
    state: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    output_files: tuple[str, ...]
    outputs: tuple[dict[str, object], ...]
    output_bytes: int
    limit_trigger: str | None
    code_path: str
    work_root: str
    result_bundle_path: str
    result_fingerprint: str
    attempt_number: int
    attempt_limit: int
    discovered_results: tuple[dict[str, object], ...] = ()
    reused_existing_execution: bool = False
    invalid_candidate_results: tuple[str, ...] = ()
    changed_output_files: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "state": self.state,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "logs": {
                stream: str(
                    Path(self.work_root)
                    / ".runtime"
                    / "executions"
                    / self.execution_id
                    / "logs"
                    / f"{stream}.txt"
                )
                for stream in ("stdout", "stderr")
            },
            "duration_seconds": self.duration_seconds,
            "output_files": list(self.output_files),
            "outputs": [dict(item) for item in self.outputs],
            "output_bytes": self.output_bytes,
            "limit_trigger": self.limit_trigger,
            "code_path": self.code_path,
            "work_root": self.work_root,
            "result_bundle_path": self.result_bundle_path,
            "result_fingerprint": self.result_fingerprint,
            "attempt_number": self.attempt_number,
            "attempt_limit": self.attempt_limit,
            "discovered_results": [dict(item) for item in self.discovered_results],
            "reused_existing_execution": self.reused_existing_execution,
            "invalid_candidate_results": list(self.invalid_candidate_results),
        }


@dataclass(frozen=True)
class ExpertMountedSource:
    """One backend-resolved Task Source mounted into an Expert sandbox."""

    handle: str
    kind: str
    ref: ArtifactRef
    title: str
    paths: tuple[Path, ...]
    manifest: dict[str, object]


@dataclass(frozen=True)
class ExpertPythonRuntime:
    """Interpreter selection pinned for the lifetime of one backend process."""

    executable: Path
    prefix: Path
    environment_name: str
    version: str
    read_roots: tuple[Path, ...]
    package_roots: tuple[Path, ...]
    requirements: tuple[str, ...]


class ExpertCodeExecutionService:
    """Run one Expert-authored Python program in its bounded workspace."""

    def __init__(
        self,
        *,
        store: RequestStore,
        paths: OceanPaths,
        task_workspaces: TaskWorkspaceProjector,
        limits: ResourceLimits | None = None,
    ) -> None:
        self.store = store
        self.paths = paths
        self.task_workspaces = task_workspaces
        self.limits = limits or ResourceLimits(
            wall_time_seconds=300,
            cpu_time_seconds=0,
            memory_bytes=0,
            disk_bytes=0,
            process_count=0,
            open_files=0,
            stdout_bytes=0,
            stderr_bytes=0,
            output_file_count=0,
            output_total_bytes=0,
        )
        self._runtime: ExpertPythonRuntime | None = None
        from oceanx.kernels import KernelPool
        self.kernels = KernelPool()
        self._runtime_error: str | None = None
        runtime_capabilities()
        self._analysis_context_locks: dict[str, asyncio.Lock] = {}
        self._task_dataset_contexts: dict[
            tuple[str, tuple[tuple[str, str], ...]], dict[str, object]
        ] = {}

    @property
    def runtime_unavailable_reason(self) -> str | None:
        """Return the last code-time inspection error, not a startup verdict."""

        return self._runtime_error

    def task_results_root(self, task_id: str) -> Path:
        return self.task_workspaces.ensure_task_root(task_id).resolve() / "agents"

    def shared_result_directories(
        self, *, workspace_id: str, task_id: str, agent_thread_id: str | None = None,
    ) -> list[Path]:
        """Expose task-local Expert files; the filesystem itself is the result index."""
        task = self.store.get_research_task(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise ExpertCodeExecutionError("Task evidence is unavailable")
        root = self.task_workspaces.ensure_task_root(task_id) / "agents"
        if not root.is_dir():
            return []
        own = (self.task_workspaces.expert_session_root(task_id, agent_thread_id).resolve()
               if agent_thread_id else None)
        return [path.resolve() for path in sorted(root.iterdir())
                if path.is_dir() and not path.is_symlink() and path.resolve() != own]

    def require_runtime(self) -> ExpertPythonRuntime:
        """Resolve the interpreter only for actual code/metadata execution.

        Cache success, never failure. Dependency imports belong to the user's
        script; unrelated absent packages cannot disable this interpreter.
        """

        if self._runtime is None:
            try:
                selected = current_python_runtime()
                self._runtime = ExpertPythonRuntime(
                    executable=selected.executable, prefix=selected.prefix,
                    environment_name=selected.environment_name, version=selected.version,
                    read_roots=selected.read_roots, package_roots=selected.package_roots,
                    requirements=selected.requirements,
                )
                self._runtime_error = None
            except (OSError, RuntimeError, SandboxUnavailableError) as exc:
                self._runtime_error = str(exc)
                raise ExpertRuntimeUnavailableError(str(exc)) from exc
        return self._runtime

    @staticmethod
    def _bounded_evidence_text(value: object, *, limit: int = 6_000) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        half = max(1, (limit - 64) // 2)
        return (
            text[:half]
            + "\n... [middle omitted; read the log path for full text] ...\n"
            + text[-half:]
        )

    def _execution_manifest_entry(
        self,
        record: CodeExecutionRecord,
        *,
        task_root: Path,
        read_only_roots: list[Path],
        include_private_logs: bool,
        include_log_excerpts: bool = True,
        formal_outputs_only: bool = False,
    ) -> dict[str, object] | None:
        """Project one execution into an Expert-readable result contract."""

        if record.result is None or record.state == "running":
            return None
        if formal_outputs_only or record.state != "succeeded":
            return None
        persisted_work_root = record.result.get("work_root")
        if not isinstance(persisted_work_root, str) or not persisted_work_root:
            return None
        prior_work_root = Path(persisted_work_root).resolve()
        try:
            prior_work_root.relative_to(task_root)
        except ValueError:
            return None
        prior_output_root = (prior_work_root / "outputs").resolve()
        output_names = record.result.get("output_files", ())
        if not isinstance(output_names, list):
            output_names = []
        outputs: list[dict[str, str]] = []
        for output_name in output_names:
            if not isinstance(output_name, str):
                continue
            candidate = (prior_output_root / output_name).resolve()
            try:
                candidate.relative_to(prior_output_root)
            except ValueError:
                continue
            if candidate.is_file() and not candidate.is_symlink():
                outputs.append({"name": output_name, "path": str(candidate)})
        if outputs:
            read_only_roots.append(prior_output_root)

        bundle_path: str | None = None
        persisted_bundle = record.result.get("result_bundle_path")
        if isinstance(persisted_bundle, str) and persisted_bundle:
            candidate = Path(persisted_bundle).resolve()
            try:
                candidate.relative_to(prior_work_root)
            except ValueError:
                candidate = Path()
            if candidate.is_file() and not candidate.is_symlink():
                bundle_path = str(candidate)
                read_only_roots.append(candidate.parent)

        entry: dict[str, object] = {
            "execution_id": record.execution_id,
            "execution_state": record.state,
            "origin_agent_thread_id": record.agent_thread_id,
            "origin_server_run_id": record.server_run_id,
            "purpose": record.request.get("purpose"),
            "outputs": outputs,
            "result_bundle_path": bundle_path,
            "result_fingerprint": record.result.get("result_fingerprint"),
        }
        if include_private_logs:
            prior_logs_root = (
                prior_work_root / ".runtime" / "executions" / record.execution_id / "logs"
            ).resolve()
            logs: dict[str, str] = {}
            for name in ("stdout.txt", "stderr.txt"):
                candidate = prior_logs_root / name
                if candidate.is_file() and not candidate.is_symlink():
                    logs[name.removesuffix(".txt")] = str(candidate)
            if logs:
                read_only_roots.append(prior_logs_root)
            entry["logs"] = logs
            if include_log_excerpts:
                entry.update(
                    {
                        "stdout_excerpt": self._bounded_evidence_text(
                            record.result.get("stdout", ""), limit=1_500
                        ),
                        "stderr_excerpt": self._bounded_evidence_text(
                            record.result.get("stderr", ""), limit=1_500
                        ),
                    }
                )
        return entry


    async def get_task_dataset_context(
        self,
        *,
        workspace_id: str,
        task_id: str,
        sources: tuple[ExpertMountedSource, ...] | None = None,
        inspect_files: bool = True,
    ) -> dict[str, object]:
        """Return the persistent DatasetContext for this task and source set.

        The first query builds metadata once per immutable Task Source. Parallel
        Experts, later queries, and additional code calls reuse the same in-memory
        object. After a backend restart the task-owned JSON restores it without
        re-running the scientific probe.
        """

        mounted = sources if sources is not None else self.resolve_task_sources(
            workspace_id=workspace_id, task_id=task_id)
        context_key = (
            task_id,
            tuple(sorted((source.ref.key, source.handle) for source in mounted)),
        )
        existing = self._task_dataset_contexts.get(context_key)
        if existing is not None:
            return existing
        task_root = self.task_workspaces.ensure_task_root(task_id).resolve()
        context_root = task_root / ".runtime" / "analysis-context"
        context_root.mkdir(parents=True, exist_ok=True)
        source_contexts: list[dict[str, object]] = []
        for source in mounted:
            cache_key = hashlib.sha256(source.ref.key.encode("utf-8")).hexdigest()[:32]
            cache_path = context_root / f"{cache_key}.json"
            lock_key = f"{task_id}:{source.ref.key}"
            lock = self._analysis_context_locks.setdefault(lock_key, asyncio.Lock())
            if not inspect_files and lock.locked():
                source_contexts.append({**source.manifest, "inspection": "not_run"})
                continue
            async with lock:
                if cache_path.is_file() and not cache_path.is_symlink():
                    try:
                        cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        cached = None
                    if isinstance(cached, dict) and self._context_is_confirmed(cached.get("sources")):
                        source_contexts.extend(
                            {
                                **item,
                                "handle": source.handle,
                                "title": source.title,
                            }
                            for item in cached.get("sources", ())
                            if isinstance(item, dict)
                        )
                        continue

                if not inspect_files:
                    source_contexts.append({
                        **source.manifest, "handle": source.handle, "title": source.title,
                        "inspection": "not_run",
                        "note": "Registered metadata only; inspect additional details when needed.",
                    })
                    continue

                probe_root = context_root / f"probe-{cache_key}"
                temporary_root = probe_root / "temporary"
                probe_root.mkdir(exist_ok=True)
                temporary_root.mkdir(exist_ok=True)
                probe_script = probe_root / "analysis_probe.py"
                shutil.copy2(_analysis_probe_source(), probe_script)
                probe_input = probe_root / "input.json"
                probe_output = probe_root / "output.json"
                probe_input.write_text(
                    json.dumps({"sources": [source.manifest]}, ensure_ascii=False),
                    encoding="utf-8",
                )
                try:
                    runtime = await asyncio.to_thread(self.require_runtime)
                    result = await run_sandboxed_command(
                        (
                            str(runtime.executable),
                            str(probe_script),
                            str(probe_input),
                            str(probe_output),
                        ),
                        policy=SandboxExecutionPolicy(
                            read_only_roots=source.paths,
                            runtime_read_roots=runtime.read_roots,
                            writable_roots=(probe_root,),
                            output_root=probe_root,
                            temporary_root=temporary_root,
                            limits=ResourceLimits(
                                wall_time_seconds=min(120.0, self.limits.wall_time_seconds),
                                cpu_time_seconds=min(90, self.limits.cpu_time_seconds),
                                memory_bytes=self.limits.memory_bytes,
                                disk_bytes=min(67_108_864, self.limits.disk_bytes),
                                stdout_bytes=65_536,
                                stderr_bytes=65_536,
                                output_file_count=16,
                                output_total_bytes=16_777_216,
                            ),
                            allow_child_processes=False,
                        ),
                        cwd=probe_root,
                        environment={
                            "CONDA_DEFAULT_ENV": runtime.environment_name,
                            "CONDA_PREFIX": str(runtime.prefix),
                            "PYTHONNOUSERSITE": "1",
                        },
                    )
                    if probe_output.is_file():
                        payload = json.loads(probe_output.read_text(encoding="utf-8"))
                    else:
                        stderr = result.stderr.decode("utf-8", errors="replace")[-2_000:]
                        payload = {
                            "schema_version": "ocean-analysis-context/v1",
                            "sources": [
                                {
                                    "handle": source.handle,
                                    "kind": source.kind,
                                    "title": source.title,
                                    "path": source.manifest.get("path"),
                                    "format": source.manifest.get("format"),
                                    "inspection": "unavailable",
                                    "error": stderr or f"probe exited with {result.returncode}",
                                }
                            ],
                        }
                except (OSError, RuntimeError, SandboxUnavailableError, ValueError) as exc:
                    payload = {
                        "schema_version": "ocean-analysis-context/v1",
                        "sources": [
                            {
                                "handle": source.handle,
                                "kind": source.kind,
                                "title": source.title,
                                "path": source.manifest.get("path"),
                                "format": source.manifest.get("format"),
                                "inspection": "unavailable",
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        ],
                    }
                if self._context_is_confirmed(payload.get("sources", [])):
                    cache_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                source_contexts.extend(
                    {**item, "handle": source.handle, "title": source.title}
                    for item in payload.get("sources", ())
                    if isinstance(item, dict)
                )
        context_material = "\0".join(
            (task_id, *(f"{ref_key}\0{handle}" for ref_key, handle in context_key[1]))
        )
        context: dict[str, object] = {
            "schema_version": "ocean-analysis-context/v1",
            "context_id": "datasetctx_"
            + hashlib.sha256(context_material.encode("utf-8")).hexdigest()[:24],
            "scope": "task",
            "task_id": task_id,
            "sources": source_contexts,
            "instruction": (
                "Use registered paths and confirmed metadata. An inspection marked not_run "
                "or unavailable is not evidence that data or Python are unusable. Inspect "
                "missing details only when needed; reuse confirmed dimensions, variables and units."
            ),
        }
        if self._context_is_confirmed(source_contexts):
            self._task_dataset_contexts[context_key] = context
        return context

    @classmethod
    def _context_is_confirmed(cls, sources: object) -> bool:
        return isinstance(sources, list) and bool(sources) and all(
            isinstance(source, dict)
            and source.get("inspection") in {"ready", "not_a_dataset"}
            and not source.get("error")
            and ("members" not in source or cls._context_is_confirmed(source["members"]))
            for source in sources
        )

    async def run_python(
        self,
        *,
        workspace_id: str,
        task_id: str,
        agent_thread_id: str,
        server_run_id: str,
        origin_request_id: str | None = None,
        purpose: str,
        code: str,
        _shell_command: str | None = None,
        _timeout: int | None = None,
    ) -> ExpertCodeExecutionResult:
        if not code.strip():
            raise ExpertCodeExecutionError("Expert code cannot be empty")
        task = self.store.get_research_task(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise ExpertCodeExecutionError("Expert code task is unavailable")
        runtime = await asyncio.to_thread(self.require_runtime)
        runtime_capabilities(retry=True)
        prior_records = self.store.list_agent_code_executions(
            workspace_id=workspace_id, task_id=task_id, agent_thread_id=agent_thread_id)
        attempt_number, attempt_limit = len(prior_records) + 1, 0
        sources = self.resolve_task_sources(workspace_id=workspace_id, task_id=task_id)

        work_root = self.task_workspaces.expert_session_root(task_id, agent_thread_id)
        execution_id = f"codeexec_{uuid4().hex}"
        runtime_root = work_root / ".runtime"
        executions_root = runtime_root / "executions"
        executions_root.mkdir(exist_ok=True)
        # Reusable intermediate files live in managed scratch across code calls.
        # Only explicitly published results belong under outputs/.
        working_root = work_root / "scratch"
        execution_root = executions_root / execution_id
        code_root = execution_root / "code"
        output_root = work_root / "outputs"
        temporary_root = execution_root / "temporary"
        logs_root = execution_root / "logs"
        result_manifest = execution_root / "result-events.jsonl"
        for directory in (
            execution_root,
            code_root,
            output_root,
            working_root,
            temporary_root,
            logs_root,
        ):
            directory.mkdir(exist_ok=True)

        _install_result_runtime(code_root)

        editable_code = work_root / "analysis.py"
        editable_code.write_text(code, encoding="utf-8")
        code_path = code_root / "analysis.py"
        shutil.copy2(editable_code, code_path)
        notebook_path = code_root / "analysis.ipynb"
        notebook_path.write_text(
            json.dumps(
                {
                    "cells": [
                        {
                            "cell_type": "markdown",
                            "metadata": {},
                            "source": [
                                "# OceanX Expert analysis\n",
                                f"Purpose: {purpose}\n",
                                (
                                    "Inputs are pinned in inputs.json; reusable intermediate data "
                                    "belongs in OCEAN_WORK_DIR and formal deliverables in "
                                    "OCEAN_OUTPUT_DIR.\n"
                                ),
                            ],
                        },
                        {
                            "cell_type": "code",
                            "execution_count": None,
                            "metadata": {},
                            "outputs": [],
                            "source": [FIGURE_IMPORT + "\n"],
                        },
                        {
                            "cell_type": "code",
                            "execution_count": None,
                            "metadata": {},
                            "outputs": [],
                            "source": code.splitlines(keepends=True),
                        },
                    ],
                    "metadata": {
                        "kernelspec": {
                            "display_name": f"OceanX ({runtime.environment_name})",
                            "language": "python",
                            "name": "python3",
                        },
                        "language_info": {"name": "python", "version": runtime.version},
                    },
                    "nbformat": 4,
                    "nbformat_minor": 5,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        requirements_path = code_root / "requirements.txt"
        requirements_path.write_text(
            "\n".join(runtime.requirements) + "\n",
            encoding="utf-8",
        )

        inputs: list[dict[str, object]] = []
        read_only_roots: list[Path] = []
        for source in sources:
            inputs.append(source.manifest)
            read_only_roots.extend(source.paths)
        task_root = self.task_workspaces.ensure_task_root(task_id).resolve()
        job_executions = prior_records
        prior_executions: list[dict[str, object]] = []
        recent_execution_ids = {prior.execution_id for prior in job_executions[-3:]}
        for prior in job_executions:
            entry = self._execution_manifest_entry(
                prior,
                task_root=task_root,
                read_only_roots=read_only_roots,
                include_private_logs=True,
                include_log_excerpts=prior.execution_id in recent_execution_ids,
            )
            if entry is not None:
                prior_executions.append(entry)

        shared_directories = self.shared_result_directories(
            workspace_id=workspace_id, task_id=task_id, agent_thread_id=agent_thread_id,
        )
        read_only_roots.extend(shared_directories)
        # Private execution provenance, not an Expert onboarding document.
        manifest_payload = {"inputs": inputs}
        input_manifest = execution_root / "inputs.json"
        input_manifest.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Human-visible stable contract for the whole workstream.  Every
        # execution receives an immutable copy, while continuations can inspect
        # one predictable file without rediscovering sandbox layout.
        (work_root / "inputs.json").write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        started_at = datetime.now(UTC).isoformat()
        self.store.start_code_execution(
            execution_id=execution_id,
            workspace_id=workspace_id,
            task_id=task_id,
            agent_thread_id=agent_thread_id,
            server_run_id=server_run_id,
            request={
                "purpose": purpose,
                "source_handles": [source.handle for source in sources],
                # Freeze source identities at execution time; later follow-ups
                # do not revoke provenance of existing products.
                "source_bindings": [
                    {"handle": source.handle, "ref": source.ref.model_dump(mode="json")}
                    for source in sources
                ],
                "code_path": str(editable_code),
                "origin_request_id": origin_request_id,
                "attempt_number": attempt_number,
                "attempt_limit": attempt_limit,
            },
            started_at=started_at,
        )

        try:
            return await self._run_started_python(
                execution_id=execution_id,
                runtime=runtime,
                read_only_roots=tuple(read_only_roots),
                input_manifest=input_manifest,
                execution_root=execution_root,
                code_root=code_root,
                code_path=code_path,
                editable_code=editable_code,
                notebook_path=notebook_path,
                output_root=output_root,
                working_root=working_root,
                temporary_root=temporary_root,
                logs_root=logs_root,
                result_manifest=result_manifest,
                work_root=work_root,
                origin_request_id=origin_request_id,
                started_at=started_at,
                attempt_number=attempt_number,
                attempt_limit=attempt_limit,
                shell_command=_shell_command,
                timeout=_timeout,
            )
        except BaseException as exc:
            terminal_state = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            record = self.store.get_code_execution(execution_id)
            if record is not None and record.state == "running":
                self.store.finish_code_execution(
                    execution_id=execution_id,
                    state=terminal_state,
                    result={"error": str(exc) or type(exc).__name__},
                    ended_at=datetime.now(UTC).isoformat(),
                )
            raise

    async def run_shell(self, *, workspace_id, task_id, agent_thread_id, server_run_id,
                        command, timeout=None, origin_request_id=None):
        """Native execute uses the same evidence/save path as persistent Python."""
        code = ("import subprocess\n"
                f"_command_result = subprocess.run([{POSIX_SHELL!r}, '-c', {command!r}], check=False)\n"
                "raise SystemExit(_command_result.returncode)\n")
        return await self.run_python(workspace_id=workspace_id, task_id=task_id,
            agent_thread_id=agent_thread_id, server_run_id=server_run_id,
            origin_request_id=origin_request_id, purpose="Shell command", code=code,
            _shell_command=command, _timeout=timeout)

    async def _run_started_python(
        self,
        *,
        execution_id: str,
        runtime: ExpertPythonRuntime,
        read_only_roots: tuple[Path, ...],
        input_manifest: Path,
        execution_root: Path,
        code_root: Path,
        code_path: Path,
        editable_code: Path,
        notebook_path: Path,
        output_root: Path,
        working_root: Path,
        temporary_root: Path,
        logs_root: Path,
        result_manifest: Path,
        work_root: Path,
        origin_request_id: str | None,
        started_at: str,
        attempt_number: int,
        attempt_limit: int,
        shell_command: str | None = None,
        timeout: int | None = None,
    ) -> ExpertCodeExecutionResult:
        """Run and persist one already-started execution as one terminal transaction."""

        runtime_root = work_root / ".runtime"
        execution_record = self.store.get_code_execution(execution_id)
        if execution_record is None:
            raise ExpertCodeExecutionError("Expert code execution record is unavailable")
        runtime_environment = {
            "PATH": os.pathsep.join((str(runtime.executable.parent), "/usr/bin", "/bin")),
            "CONDA_DEFAULT_ENV": runtime.environment_name,
            "CONDA_PREFIX": str(runtime.prefix),
            "OCEAN_INPUT_MANIFEST": str(input_manifest),
            "OCEAN_WORK_DIR": str(working_root),
            "OCEAN_OUTPUT_DIR": str(output_root),
            "OCEAN_RESULT_MANIFEST": str(result_manifest),
            "OCEAN_AGENT_KEY": execution_record.agent_thread_id,
            "OCEAN_ORIGIN_REQUEST_ID": origin_request_id or "",
            "OCEAN_TEMP_DIR": str(temporary_root),
            "PYTHONNOUSERSITE": "1",
        }

        authority = hashlib.sha256(json.dumps({
            "sources": execution_record.request.get("source_bindings", []),
            "disclosure_policy": self.store.get_disclosure_policy(execution_record.workspace_id),
        }, sort_keys=True).encode()).hexdigest()
        policy = SandboxExecutionPolicy(
                read_only_roots=read_only_roots,
                runtime_read_roots=shell_runtime_roots(runtime.read_roots) if shell_command is not None else runtime.read_roots,
                writable_roots=(work_root,),
                output_root=output_root,
                temporary_root=temporary_root,
                limits=replace(self.limits, wall_time_seconds=min(timeout or self.limits.wall_time_seconds,
                    self.limits.wall_time_seconds) if self.limits.wall_time_seconds else (timeout or 300)),
                allow_child_processes=shell_command is not None,
                allow_network=True,
            )
        if shell_command is not None:
            runtime_environment.update({
                "PYTHONPATH": str(code_root),
            })
            (code_root / "command.sh").write_text(shell_command, encoding="utf-8")
            result = await run_sandboxed_command((POSIX_SHELL, "-c", shell_command),
                policy=policy, cwd=working_root, environment=runtime_environment)
        else:
            result = await self.kernels.execute(
                key=str(work_root), executable=runtime.executable, authority=authority,
                code=code_path.read_text(encoding="utf-8"), support_path=code_root, policy=policy,
                cwd=working_root, environment=runtime_environment,
            )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        ended_at = datetime.now(UTC).isoformat()
        notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        setup_cell = notebook["cells"][1]
        setup_cell["execution_count"] = 1
        code_cell = notebook["cells"][2]
        code_cell["execution_count"] = 1
        code_cell["outputs"] = [
            *(
                [
                    {
                        "name": "stdout",
                        "output_type": "stream",
                        "text": stdout.splitlines(keepends=True),
                    }
                ]
                if stdout
                else []
            ),
            *(
                [
                    {
                        "name": "stderr",
                        "output_type": "stream",
                        "text": stderr.splitlines(keepends=True),
                    }
                ]
                if stderr
                else []
            ),
        ]
        notebook["metadata"]["oceanmind_execution"] = {
            "execution_id": execution_id,
            "state": result.status.value,
            "returncode": result.returncode,
            "duration_seconds": result.duration_seconds,
            "limit_trigger": result.limit_trigger,
            "started_at": started_at,
            "ended_at": ended_at,
        }
        notebook_path.write_text(
            json.dumps(notebook, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (logs_root / "stdout.txt").write_text(stdout, encoding="utf-8")
        (logs_root / "stderr.txt").write_text(stderr, encoding="utf-8")
        output_files = tuple(
            path.relative_to(output_root).as_posix()
            for path in sorted(output_root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        )
        output_records: list[dict[str, object]] = []
        changed_output_files = []
        for output_name in output_files:
            output_path = output_root / output_name
            digest = hashlib.sha256()
            with output_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            changed_output_files.append(output_name)
            output_records.append(
                {
                    "name": output_name,
                    "bytes": output_path.stat().st_size,
                    "sha256": digest.hexdigest(),
                }
            )
        declaration_errors: list[str] = []
        discovered_results = self._read_result_events(
            result_manifest,
            output_files=output_files,
            errors=declaration_errors,
        )
        result_bundle = {
            "schema_version": "ocean-execution-result/v1",
            "execution_id": execution_id,
            "state": result.status.value,
            "returncode": result.returncode,
            "limit_trigger": result.limit_trigger,
            "duration_seconds": result.duration_seconds,
            "output_files": list(output_files),
            "outputs": output_records,
            "discovered_results": list(discovered_results),
            "invalid_candidate_results": declaration_errors,
            "output_bytes": result.output_summary.total_bytes,
            "stdout": self._bounded_evidence_text(stdout),
            "stderr": self._bounded_evidence_text(stderr, limit=2_000),
            "logs": {
                "stdout": str(logs_root / "stdout.txt"),
                "stderr": str(logs_root / "stderr.txt"),
            },
            "output_root": str(output_root),
            "working_root": str(working_root),
            "input_manifest": str(input_manifest),
            "code_path": str(editable_code),
            "work_root": str(work_root),
            "attempt_number": attempt_number,
            "attempt_limit": attempt_limit,
            "ended_at": ended_at,
        }
        result_fingerprint = execution_result_fingerprint(result_bundle)
        result_bundle["fingerprint"] = result_fingerprint
        result_bundles_root = runtime_root / "result-bundles"
        result_bundles_root.mkdir(exist_ok=True)
        result_bundle_path = result_bundles_root / f"{execution_id}.json"
        write_execution_result_manifest(result_bundle_path, result_bundle)
        write_execution_result_manifest(runtime_root / "latest-result.json", result_bundle)
        payload = ExpertCodeExecutionResult(
            execution_id=execution_id,
            state=result.status.value,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=result.duration_seconds,
            output_files=output_files,
            outputs=tuple(output_records),
            output_bytes=result.output_summary.total_bytes,
            limit_trigger=result.limit_trigger,
            code_path=str(editable_code),
            work_root=str(work_root),
            result_bundle_path=str(result_bundle_path),
            result_fingerprint=result_fingerprint,
            attempt_number=attempt_number,
            attempt_limit=attempt_limit,
            discovered_results=discovered_results,
            invalid_candidate_results=tuple(declaration_errors),
            changed_output_files=tuple(changed_output_files),
        )
        self.store.finish_code_execution(
            execution_id=execution_id,
            state=payload.state,
            result=payload.as_payload(),
            # Tool wall time includes artifact snapshotting; duration_seconds
            # remains the separately measured Python/kernel execution time.
            ended_at=datetime.now(UTC).isoformat(),
        )
        return payload


    @staticmethod
    def _read_result_events(
        manifest: Path,
        *,
        output_files: tuple[str, ...],
        errors: list[str] | None = None,
    ) -> tuple[dict[str, object], ...]:
        """Read current save events without silently losing declarations."""

        def reject(line_number: int, reason: str) -> None:
            if errors is not None and len(errors) < 32:
                errors.append(f"Saved-result event {line_number}: {reason[:400]}")

        if manifest.is_symlink():
            reject(0, "result manifest must not be a symlink")
            return ()
        if not manifest.exists():
            return ()
        available_outputs = set(output_files)
        discovered: dict[str, dict[str, object]] = {}
        try:
            lines = manifest.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            reject(0, f"cannot read result manifest: {exc}")
            return ()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                reject(line_number, "invalid JSON")
                continue
            if (
                not isinstance(event, dict)
                or event.get("schema_version") != "ocean-result-event/v1"
            ):
                reject(line_number, "unsupported result-event schema")
                continue
            normalized = dict(event)
            if event.get("kind") == "report":
                output_name = event.get("report_output")
            elif event.get("kind") == "interactive_view":
                if "field_output" in event:
                    reject(line_number, "unsupported field_output; current events use data_output")
                    continue
                output_name = event.get("data_output")
            else:
                reject(line_number, "unsupported result kind")
                continue
            if not isinstance(output_name, str) or output_name not in available_outputs:
                reject(line_number, f"declared output is missing or unavailable: {output_name!r}")
                continue
            dataset_output = normalized.get("dataset_output")
            if isinstance(dataset_output, str) and dataset_output not in available_outputs:
                reject(line_number, f"declared dataset is unavailable: {dataset_output}")
                continue
            preview = normalized.get("preview_output")
            if isinstance(preview, str) and preview not in available_outputs:
                normalized.pop("preview_output", None)
            attachments = normalized.get("attachment_outputs")
            if isinstance(attachments, list):
                normalized["attachment_outputs"] = [
                    name
                    for name in attachments
                    if isinstance(name, str) and name in available_outputs
                ]
            # save() atomically replaces the same file: the last declaration
            # must describe those bytes, not a superseded title or conclusion.
            discovered[output_name] = normalized
        return tuple(discovered.values())

    def resolve_task_sources(
        self,
        *,
        workspace_id: str,
        task_id: str,
    ) -> tuple[ExpertMountedSource, ...]:
        """Resolve the immutable sources attached to a research task."""

        task = self.store.get_research_task(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise ExpertCodeExecutionError("Expert code task is unavailable")

        sources: list[ExpertMountedSource] = []
        for attached in self.store.list_task_artifacts(task_id=task_id):
            if "source" not in attached.relations:
                continue
            artifact = attached.artifact
            ref = artifact.ref
            handle = f"source_{len(sources) + 1}"
            if artifact.artifact_type == "dataset":
                dataset = resolve_dataset_source(
                    store=self.store,
                    paths=self.paths,
                    workspace_id=workspace_id,
                    ref=ref,
                )
                paths = (dataset.path,)
                files = [
                    {
                        "path": str(dataset.path),
                        "format": dataset.format,
                    }
                ]
                primary_path = str(dataset.path)
                format_hint = dataset.format
            elif artifact.artifact_type == "project_context" and artifact.schema_version == "ocean-local-source/v1":
                from oceanx.local_sources import resolve_local_source
                local = resolve_local_source(store=self.store, workspace_id=workspace_id, ref=ref)
                paths = (local.path,)
                files = [{"path": str(local.path), "format": local.format}]
                primary_path, format_hint = str(local.path), local.format
            else:
                resolved_files: list[dict[str, object]] = []
                resolved_paths: list[Path] = []
                try:
                    for artifact_file in artifact.files:
                        path = self.paths.resolve_uri(artifact_file.uri)
                        if not path.exists():
                            raise ExpertCodeExecutionError(
                                f"Task Source file is unavailable: {artifact_file.uri}"
                            )
                        resolved_paths.append(path)
                        resolved_files.append(
                            {
                                "path": str(path),
                                "mime_type": artifact_file.mime_type,
                                "size_bytes": artifact_file.size_bytes,
                            }
                        )
                except StoragePolicyError as exc:
                    raise ExpertCodeExecutionError(
                        f"Task Source file cannot be mounted: {artifact.title}"
                    ) from exc
                paths = tuple(resolved_paths)
                files = resolved_files
                primary_path = str(paths[0]) if len(paths) == 1 else None
                format_hint = paths[0].suffix.lstrip(".").lower() if len(paths) == 1 else None

            manifest: dict[str, object] = {
                "handle": handle,
                "kind": artifact.artifact_type,
                "title": artifact.title,
                "files": files,
                "metadata": artifact.content,
            }
            # Retain the simple path/format keys for compact single-file programs.
            if primary_path is not None:
                manifest["path"] = primary_path
            if format_hint:
                manifest["format"] = format_hint
            sources.append(
                ExpertMountedSource(
                    handle=handle,
                    kind=artifact.artifact_type,
                    ref=ref,
                    title=artifact.title,
                    paths=paths,
                    manifest=manifest,
                )
            )
        return tuple(sources)


__all__ = [
    "ExpertCodeExecutionError",
    "ExpertCodeExecutionResult",
    "ExpertCodeExecutionService",
]

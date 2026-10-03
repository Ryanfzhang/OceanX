"""Small, model-free proof that the current Ocean runtime can enforce Seatbelt.

The desktop packager invokes this through the frozen sidecar. It is deliberately
separate from ``doctor``: capability discovery is useful to users, while release
validation needs to execute one constrained child process before it can claim
that Expert-owned scientific code execution is available.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from oceanx.sandbox import (
    ResourceLimits,
    SandboxExecutionPolicy,
    SandboxExecutionStatus,
    SandboxUnavailableError,
    current_python_executable,
    current_python_runtime_roots,
    get_sandbox_execution_capabilities,
    run_sandboxed_command,
)
from oceanx.sandbox_probe_entry import run_sandbox_probe

_PROBE_FILENAME = "sandbox-probe.json"
_REQUIRED_SCIENTIFIC_MODULES = ("zarr", "netCDF4", "gsw")


def _probe_command() -> tuple[str, ...]:
    executable = str(current_python_executable())
    return executable, str(Path(__file__).resolve().with_name("sandbox_probe_entry.py"))


def _probe_environment() -> dict[str, str]:
    """Never inject the backend virtualenv into the selected Conda runtime."""

    return {"PYTHONNOUSERSITE": "1"}


def _probe_runtime_roots() -> tuple[Path, ...]:
    roots = [*current_python_runtime_roots(), Path(__file__).resolve().parents[1]]
    return tuple(dict.fromkeys(path.resolve() for path in roots if path.exists()))


async def run_sandbox_self_check() -> dict[str, Any]:
    """Execute the minimal read/write isolation contract and return safe JSON."""

    capabilities = get_sandbox_execution_capabilities()
    report: dict[str, Any] = {
        "schema_version": "ocean-sandbox-self-check/v1",
        "backend": capabilities.backend,
        "available": capabilities.available,
        "passed": False,
        "checks": {
            "declared_output_written": False,
            "outside_read_denied": False,
            "scientific_imports": {
                module_name: False for module_name in _REQUIRED_SCIENTIFIC_MODULES
            },
        },
    }
    if not capabilities.available:
        report["reason"] = capabilities.reason
        return report

    with tempfile.TemporaryDirectory(prefix="ocean-sandbox-self-check-") as temporary_directory:
        root = Path(temporary_directory)
        work = root / "work"
        output = root / "output"
        temporary = root / "temporary"
        private = root / "private.txt"
        for directory in (work, output, temporary):
            directory.mkdir()
        private.write_text("must remain unreadable", encoding="utf-8")
        policy = SandboxExecutionPolicy(
            read_only_roots=(work,),
            runtime_read_roots=_probe_runtime_roots(),
            writable_roots=(output, temporary),
            output_root=output,
            temporary_root=temporary,
            limits=ResourceLimits(
                wall_time_seconds=10.0,
                cpu_time_seconds=8,
                memory_bytes=268_435_456,
                disk_bytes=65_536,
                process_count=4,
                open_files=64,
                stdout_bytes=4_096,
                stderr_bytes=4_096,
                output_file_count=4,
                output_total_bytes=65_536,
                termination_grace_seconds=0.5,
            ),
        )
        try:
            result = await run_sandboxed_command(
                (
                    *_probe_command(),
                    "--output-directory",
                    str(output),
                    "--outside-path",
                    str(private),
                    *(
                        argument
                        for module_name in _REQUIRED_SCIENTIFIC_MODULES
                        for argument in ("--required-module", module_name)
                    ),
                ),
                policy=policy,
                cwd=work,
                environment=_probe_environment(),
            )
        except SandboxUnavailableError as exc:
            report["reason"] = str(exc)
            return report

        report["result"] = {
            "status": result.status.value,
            "limit_trigger": result.limit_trigger,
            "returncode": result.returncode,
        }
        if result.status is not SandboxExecutionStatus.SUCCEEDED:
            diagnostic = result.stderr.decode("utf-8", errors="replace").strip()
            report["reason"] = diagnostic[-2_000:] or (
                f"Sandbox probe exited with code {result.returncode}"
            )
        probe_path = output / _PROBE_FILENAME
        try:
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            probe = {}
        output_written = result.output_summary.file_count == 1 and result.output_summary.unsafe_entries == ()
        outside_read_denied = probe.get("outside_read_denied") is True
        import_results = probe.get("scientific_imports")
        scientific_imports = {
            module_name: isinstance(import_results, dict)
            and import_results.get(module_name) is None
            for module_name in _REQUIRED_SCIENTIFIC_MODULES
        }
        report["checks"] = {
            "declared_output_written": output_written,
            "outside_read_denied": outside_read_denied,
            "scientific_imports": scientific_imports,
        }
        report["passed"] = (
            result.status is SandboxExecutionStatus.SUCCEEDED
            and output_written
            and outside_read_denied
            and all(scientific_imports.values())
        )
    return report


async def run_kernel_self_check() -> dict[str, Any]:
    """Start the sandboxed Python kernel an Expert's code tool uses and save to its output folder,
    then do it again in a fresh kernel that is offered the earlier output read-only, as later
    runs are. Both failed silently on a Linux server before: the kernel never started, and the
    output folder was locked after the first saved result."""

    from oceanx.expert_execution import _install_result_runtime
    from oceanx.kernels import KernelPool
    from oceanx.sandbox.execution import current_python_runtime

    report: dict[str, Any] = {
        "schema_version": "ocean-kernel-self-check/v1", "passed": False,
        "checks": {"kernel_started": False, "outputs_written_twice": False},
    }
    pool = KernelPool()
    with tempfile.TemporaryDirectory(prefix="ocean-kernel-self-check-") as temporary_directory:
        root = Path(temporary_directory).resolve()
        outputs, scratch, support = root / "outputs", root / "scratch", root / "code"
        for directory in (outputs, scratch, support):
            directory.mkdir()
        try:
            runtime = current_python_runtime()
            _install_result_runtime(support)
            for run, read_only in ((1, ()), (2, (outputs,))):
                saved = outputs / f"saved-{run}.txt"
                result = await pool.execute(
                    key=str(root), executable=runtime.executable, cwd=scratch, environment={},
                    support_path=support, code=f"open({str(saved)!r}, 'w').write('ok')",
                    policy=SandboxExecutionPolicy(
                        read_only_roots=read_only, runtime_read_roots=runtime.read_roots,
                        writable_roots=(root,), output_root=outputs, temporary_root=root,
                        limits=ResourceLimits(wall_time_seconds=60, cpu_time_seconds=0,
                                              memory_bytes=0, disk_bytes=0, process_count=0,
                                              open_files=0),
                        allow_network=True))
                report["checks"]["kernel_started"] = True
                if result.status is not SandboxExecutionStatus.SUCCEEDED or not saved.is_file():
                    report["reason"] = (result.stderr.decode("utf-8", errors="replace").strip()[-2_000:]
                                        or f"Run {run} did not save {saved.name}")
                    return report
                await pool.close(str(root))  # the second run gets a fresh kernel and sandbox
            report["checks"]["outputs_written_twice"] = report["passed"] = True
        except Exception as exc:  # noqa: BLE001 - every failure is the check's answer
            report["reason"] = str(exc)[-2_000:]
        finally:
            await pool.close()
    return report


__all__ = ["run_kernel_self_check", "run_sandbox_probe", "run_sandbox_self_check"]

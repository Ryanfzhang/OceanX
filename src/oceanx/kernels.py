"""Thread-owned Jupyter processes. Graph runs borrow kernels; they never own them.

Single-host service: the manager lives in the Agent Server process. Each kernel
is launched under the same filesystem sandbox as a normal Ocean code execution.
Files remain the durable record; kernel memory is explicitly disposable.
"""
from __future__ import annotations

import asyncio
import time
from queue import Empty
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from jupyter_client import AsyncKernelManager
from jupyter_client.kernelspec import KernelSpec

from oceanx.sandbox.execution import (
    ExecutionTrust,
    SandboxExecutionPolicy,
    SandboxExecutionResult,
    _build_limit_preexec,
    _build_sanitized_environment,
    _classify_terminal_status,
    build_macos_seatbelt_profile,
    require_sandbox_execution_capabilities,
    summarize_output_tree,
)


class SandboxedKernelManager(AsyncKernelManager):
    def __init__(self, *, executable: Path, policy: SandboxExecutionPolicy, cwd: Path, **kwargs):
        super().__init__(**kwargs)
        self._kernel_spec = KernelSpec(argv=[str(executable), "-m", "ipykernel_launcher",
                                           "-f", "{connection_file}"], display_name="OceanX")
        self.policy, self.workdir = policy, cwd
        self.resources = ExitStack()
        self.descriptors = ()

    def format_kernel_cmd(self, extra_arguments=None):
        command = super().format_kernel_cmd(extra_arguments)
        capabilities = require_sandbox_execution_capabilities()
        if capabilities.backend == "linux-bubblewrap-seccomp-v1":
            from oceanx.sandbox.linux import build_bubblewrap_command, seccomp_filter
            if not self.descriptors:
                handle = self.resources.enter_context(seccomp_filter(
                    allow_child_processes=False, allow_network=self.policy.allow_network))
                self.descriptors = (handle.fileno(),)
            return list(build_bubblewrap_command(capabilities.command or "bwrap", command,
                        policy=self.policy, cwd=self.workdir, seccomp_fd=self.descriptors[0]))
        if capabilities.backend == "macos-seatbelt-rlimit-v1":
            return [capabilities.command or "sandbox-exec", "-p",
                    build_macos_seatbelt_profile(self.policy), *command]
        raise RuntimeError("Persistent kernels require a supported sandbox launcher; no unsandboxed fallback")


@dataclass
class Kernel:
    manager: AsyncKernelManager
    client: object
    executable: Path
    authority: str = ""


class KernelPool:
    def __init__(self, manager_type=SandboxedKernelManager):
        self.manager_type = manager_type
        self.kernels: dict[str, Kernel] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.lost: set[str] = set()

    async def _stop(self, key: str):
        kernel = self.kernels.pop(key, None)
        if kernel:
            try:
                await kernel.manager.shutdown_kernel(now=True)
            finally:
                kernel.client.stop_channels()
                resources = getattr(kernel.manager, "resources", None)
                if resources:
                    resources.close()
                self.lost.add(key)

    async def close(self, key: str | None = None):
        for current in [key] if key is not None else list(self.kernels):
            async with self.locks.setdefault(current, asyncio.Lock()):
                await self._stop(current)

    async def execute(self, *, key: str, executable: Path, policy: SandboxExecutionPolicy,
                      cwd: Path, environment: dict[str, str], code: str,
                      support_path: Path, authority: str = "") -> SandboxExecutionResult:
        async with self.locks.setdefault(key, asyncio.Lock()):
            kernel = self.kernels.get(key)
            if kernel and (kernel.executable != executable or kernel.authority != authority
                           or not await kernel.manager.is_alive()):
                await self._stop(key)
                kernel = None
            if kernel is None:
                runtime_dir = cwd.parent / "kernel"
                if runtime_dir.exists():
                    self.lost.add(key)  # e.g. a server restart; never pretend RAM was checkpointed
                runtime_dir.mkdir(parents=True, exist_ok=True)
                manager = self.manager_type(executable=executable, policy=policy, cwd=cwd,
                                           connection_file=str(runtime_dir / "connection.json"))
                env = _build_sanitized_environment(policy, environment)
                env.update(IPYTHONDIR=str(runtime_dir / "ipython"),
                           JUPYTER_RUNTIME_DIR=str(runtime_dir), PYDEVD_DISABLE_FILE_VALIDATION="1")
                # Linux seccomp fd is allocated while formatting argv, before launch.
                manager.format_kernel_cmd()
                try:
                    await manager.start_kernel(cwd=str(cwd), env=env,
                                               pass_fds=manager.descriptors,
                                               preexec_fn=_build_limit_preexec(policy.limits))
                    client = manager.client()
                    client.start_channels()
                    await client.wait_for_ready(timeout=60)
                except BaseException:
                    await manager.shutdown_kernel(now=True)
                    manager.resources.close()
                    raise
                kernel = self.kernels[key] = Kernel(manager, client, executable, authority)
            notice = ""
            if key in self.lost:
                notice = "Kernel memory was lost; this is a fresh kernel. Saved files remain available.\n"
                self.lost.remove(key)
            setup = ("import os as _ox_os, sys as _ox_sys\n"
                     f"_ox_os.environ.update({environment!r})\n"
                     f"_ox_os.chdir({str(cwd)!r})\n"
                     f"_ox_sys.path.insert(0, {str(support_path)!r})\n"
                     "from oceanx.scientific_view import ScientificFigure\n")
            started = time.monotonic()
            msg_id = kernel.client.execute(setup + code, stop_on_error=True)
            stdout, stderr = [notice] if notice else [], []
            exit_code = 0
            limit_trigger = None
            async def collect():
                nonlocal exit_code
                while True:
                    try:
                        message = await asyncio.wait_for(kernel.client.get_iopub_msg(), timeout=1.0)
                    except (TimeoutError, Empty):
                        if not await kernel.manager.is_alive():
                            exit_code = 1
                            stderr.append("KernelExitedError: Python kernel exited before completing this execution. "
                                          "Captured output is preserved; this is not a successful calculation.\n")
                            await self._stop(key)
                            return
                        continue
                    if message.get("parent_header", {}).get("msg_id") != msg_id:
                        continue
                    content = message["content"]
                    kind = message["msg_type"]
                    if kind == "stream":
                        (stderr if content["name"] == "stderr" else stdout).append(content["text"])
                    elif kind == "error":
                        exit_code = 1
                        stderr.append("\n".join(content["traceback"]) + "\n")
                    elif kind in {"execute_result", "display_data"}:
                        stdout.append(content.get("data", {}).get("text/plain", "") + "\n")
                    elif kind == "status" and content["execution_state"] == "idle":
                        return
            try:
                async with asyncio.timeout(policy.limits.wall_time_seconds or None):
                    await collect()
            except TimeoutError:
                exit_code = 1
                limit_trigger = "wall_time"
                stderr.append("ExecutionTimeoutError: Code execution exceeded its wall-time limit.\n")
                await asyncio.shield(self._stop(key))
            except BaseException:
                # Cancel the actual computation, not just the wait for its result.
                await asyncio.shield(self._stop(key))
                raise
            output_summary = summarize_output_tree(policy.output_root, policy.limits)
            out, err = "".join(stdout).encode(), "".join(stderr).encode()
            status, trigger = _classify_terminal_status(returncode=exit_code, stdout=out,
                stderr=err, limit_trigger=limit_trigger, output_summary=output_summary)
            return SandboxExecutionResult(
                status=status,
                returncode=exit_code, stdout=out, stderr=err,
                duration_seconds=time.monotonic() - started,
                trust=ExecutionTrust.SANDBOXED, limit_trigger=trigger,
                output_summary=output_summary,
            )

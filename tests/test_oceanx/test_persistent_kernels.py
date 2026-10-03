"""Real sandboxed Jupyter processes; no LLM or paid network calls."""
import asyncio
import sys
from pathlib import Path

import pytest

from oceanx.kernels import KernelPool
from oceanx.expert_execution import _install_result_runtime
from oceanx.sandbox.execution import ResourceLimits, SandboxExecutionPolicy, current_python_runtime


@pytest.mark.asyncio
async def test_kernel_memory_isolated_and_survives_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    runtime = current_python_runtime()
    pool = KernelPool()
    async def run(key, code, timeout=0):
        root = tmp_path / key
        root.mkdir(exist_ok=True)
        output = root / "outputs"
        output.mkdir(exist_ok=True)
        support = root / "code"
        support.mkdir(exist_ok=True)
        _install_result_runtime(support)
        return await pool.execute(key=key, executable=Path(sys.executable),
            policy=SandboxExecutionPolicy(read_only_roots=(), runtime_read_roots=runtime.read_roots,
                writable_roots=(root,), output_root=output, temporary_root=root,
                limits=ResourceLimits(wall_time_seconds=timeout, cpu_time_seconds=0, memory_bytes=0,
                                      disk_bytes=0, process_count=0, open_files=0), allow_network=True),
            cwd=output, environment={}, support_path=support, code=code)
    try:
        first = await run("one", "temperature = [1, 2, 3]\nprint(sum(temperature))")
        assert first.returncode == 0, first.stderr.decode()
        assert b"6" in first.stdout
        second = await run("one", "print(sum(temperature) / len(temperature))")
        assert second.returncode == 0, second.stderr.decode()
        assert b"2.0" in second.stdout
        helper = await run("one", "import oceanx_array_ops as ao\nprint(ao.self_test())")
        assert helper.returncode == 0, helper.stderr.decode()
        assert b"self-test passed" in helper.stdout
        reused_helper = await run("one", "print(ao.masked_values([1, 2, 3], [True, False, True]))")
        assert reused_helper.returncode == 0, reused_helper.stderr.decode()
        assert b"[1 3]" in reused_helper.stdout
        other = await run("two", "temperature = [100]\nprint(sum(temperature))")
        assert other.returncode == 0, other.stderr.decode()
        again = await run("one", "print(temperature)")
        assert b"[1, 2, 3]" in again.stdout
        failure = await run("one", "raise ValueError('test error')")
        assert failure.returncode == 1
        assert b"[1, 2, 3]" in (await run("one", "print(temperature)")).stdout
        interrupted = await run("one", "raise KeyboardInterrupt('interrupted cell')")
        assert interrupted.returncode == 1 and b"KeyboardInterrupt" in interrupted.stderr
        assert b"[1, 2, 3]" in (await run("one", "print(temperature)")).stdout
        await pool.close("one")
        fresh = await run("one", "print('temperature' in globals())")
        assert b"Kernel memory was lost" in fresh.stdout and b"False" in fresh.stdout
        manager = pool.kernels["one"].manager
        busy = asyncio.create_task(run("one", "while True: pass"))
        await asyncio.sleep(0.2)
        busy.cancel()
        with pytest.raises(asyncio.CancelledError):
            await busy
        assert "one" not in pool.kernels
        assert not await manager.is_alive()
        # Death during an execution must not leave get_iopub_msg awaiting idle
        # forever. Verify captured output and subsequent fresh-kernel recovery.
        dead = await asyncio.wait_for(run("one", "print('before exit', flush=True)\nimport os\nos._exit(7)"), 20)
        assert dead.returncode == 1 and b"KernelExitedError" in dead.stderr
        assert "one" not in pool.kernels
        recovered = await run("one", "print('fresh after death')")
        assert b"fresh after death" in recovered.stdout
        timed = await run("one", "print('before timeout', flush=True)\nwhile True: pass", timeout=0.3)
        assert timed.status.value == "timed_out" and timed.limit_trigger == "wall_time"
        assert b"before timeout" in timed.stdout
        assert "one" not in pool.kernels
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_cancel_destroys_busy_kernel_not_just_its_wait(tmp_path, monkeypatch):
    # The lifecycle primitive must destroy the process before allowing another
    # execution. End-to-end code-tool coverage uses the test above.
    pool = KernelPool()
    class Manager:
        stopped = False
        async def shutdown_kernel(self, now):
            self.stopped = True
    class Client:
        def stop_channels(self):
            pass
    from oceanx.kernels import Kernel
    manager = Manager()
    pool.kernels["one"] = Kernel(manager, Client(), Path(sys.executable))
    await pool.close("one")
    assert manager.stopped and "one" not in pool.kernels and "one" in pool.lost


@pytest.mark.asyncio
async def test_kernel_has_the_helper_functions_and_logs_their_calls_per_execution(tmp_path, monkeypatch):
    from oceanx.expert_execution import read_tool_log
    from oceanx.research.memory import ResearchMemory
    from oceanx.research.toolbook import ToolBook
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    runtime = current_python_runtime()
    pool = KernelPool()
    root = tmp_path / "one"
    output, support = root / "outputs", root / "code"
    for directory in (output, support):
        directory.mkdir(parents=True)
    # What the execution service installs: the project's helper module with its call counter.
    _install_result_runtime(support, ToolBook(ResearchMemory(tmp_path / "research")).module_source())

    async def run(code, log):
        return await pool.execute(key="one", executable=Path(sys.executable),
            policy=SandboxExecutionPolicy(read_only_roots=(), runtime_read_roots=runtime.read_roots,
                writable_roots=(root,), output_root=output, temporary_root=root,
                limits=ResourceLimits(wall_time_seconds=0, cpu_time_seconds=0, memory_bytes=0,
                                      disk_bytes=0, process_count=0, open_files=0), allow_network=True),
            cwd=output, environment={"OCEAN_TOOL_LOG": str(root / log)}, support_path=support, code=code)
    try:
        # The helpers are one name away without an import.
        first = await run("print(ao.rate_per_day(2.0, input_unit='per_day'))", "first.log")
        assert first.returncode == 0, first.stderr.decode()
        assert b"2.0" in first.stdout
        # A variable the code itself calls ao is left alone, also in later cells.
        own = await run("ao = 'mine'", "second.log")
        assert own.returncode == 0 and b"mine" in (await run("print(ao)", "second.log")).stdout
        third = await run("import oceanx_array_ops as ao\n"
                          "for _ in range(2): ao.rate_per_day(1.0, input_unit='per_second')", "third.log")
        assert third.returncode == 0, third.stderr.decode()
        # Each execution logs its own calls, although the kernel imported the module only once.
        assert read_tool_log(root / "first.log") == {"rate_per_day": 1}
        assert read_tool_log(root / "second.log") == {}
        assert read_tool_log(root / "third.log") == {"rate_per_day": 2}
    finally:
        await pool.close()


def _policy(root: Path, runtime) -> SandboxExecutionPolicy:
    for directory in (root / "outputs", root / "code"):
        directory.mkdir(parents=True, exist_ok=True)
    return SandboxExecutionPolicy(read_only_roots=(), runtime_read_roots=runtime.read_roots,
        writable_roots=(root,), output_root=root / "outputs", temporary_root=root,
        limits=ResourceLimits(wall_time_seconds=0, cpu_time_seconds=0, memory_bytes=0,
                              disk_bytes=0, process_count=0, open_files=0), allow_network=True)


@pytest.mark.asyncio
async def test_a_kernel_that_dies_at_start_says_why(tmp_path, monkeypatch):
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    runtime = current_python_runtime()
    root = tmp_path / "one"
    policy = _policy(root, runtime)
    # `python -m` looks in the working directory first, so this stands in for ipykernel.
    (root / "outputs" / "ipykernel_launcher.py").write_text(
        "import sys\nsys.stderr.write('boom before kernel_info\\n')\nsys.exit(3)\n")
    pool = KernelPool()
    try:
        with pytest.raises(RuntimeError, match="boom before kernel_info"):
            await pool.execute(key="one", executable=Path(sys.executable), policy=policy,
                               cwd=root / "outputs", environment={}, support_path=root / "code",
                               code="print(1)")
        assert "one" not in pool.kernels
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_a_bubblewrap_kernel_is_not_given_a_parent_to_watch(tmp_path, monkeypatch):
    # Inside bubblewrap's PID namespace the kernel's parent is PID 1; ipykernel would
    # take that for a dead parent and exit before replying to kernel_info.
    import contextlib
    from types import SimpleNamespace

    from oceanx import kernels
    from oceanx.sandbox import linux
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    monkeypatch.setattr(kernels, "require_sandbox_execution_capabilities",
                        lambda: SimpleNamespace(backend="linux-bubblewrap-seccomp-v1", command="bwrap"))
    monkeypatch.setattr(linux, "seccomp_filter",
                        lambda **_: contextlib.nullcontext(SimpleNamespace(fileno=lambda: 9)))
    monkeypatch.setattr(linux, "build_bubblewrap_command", lambda _, command, **__: tuple(command))
    launched = {}

    class Manager(kernels.SandboxedKernelManager):
        async def start_kernel(self, **kw):
            launched.update(kw)
            raise RuntimeError("not launched in this test")

        async def shutdown_kernel(self, now=False, restart=False):
            pass

    root = tmp_path / "one"
    pool = KernelPool(manager_type=Manager)
    with pytest.raises(RuntimeError, match="not launched"):
        await pool.execute(key="one", executable=Path(sys.executable),
                           policy=_policy(root, current_python_runtime()), cwd=root / "outputs",
                           environment={}, support_path=root / "code", code="print(1)")
    assert launched["independent"] is True
    assert launched["stdout"] is launched["stderr"] and launched["stdout"] is not None

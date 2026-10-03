"""Finch notebook execution in Linux user namespaces, without Docker or OceanX."""
from __future__ import annotations

import asyncio
import math
import os
import sys
from pathlib import Path

BACKEND = "linux-bubblewrap-notebook-v1"
SYSTEM_ROOTS = ("/usr", "/bin", "/sbin", "/lib", "/lib64",
                "/etc/ld.so.cache", "/etc/fonts", "/etc/localtime")


def kernel_check():
    """Describe the exact interpreter and scientific packages used for computation."""
    import importlib.metadata

    import ipykernel
    import nbconvert
    import numpy
    import xarray
    del ipykernel, nbconvert, numpy, xarray
    return {"python": sys.version.split()[0], "executable": sys.executable,
            "runtime_roots": sorted({sys.prefix, sys.base_prefix}),
            "libraries": {d.metadata["Name"].lower(): d.version
                          for d in importlib.metadata.distributions() if d.metadata.get("Name")}}


def sandbox_command(spec, command):
    """Empty host view: system/runtime RO, declared datasets RO, workspace RW."""
    workspace = Path(spec["workspace"]).resolve()
    roots = [Path(p) for p in SYSTEM_ROOTS if Path(p).exists()]
    for name in spec["kernel"]["runtime_roots"]:
        root = Path(name).resolve()
        if root in {Path("/"), Path("/home"), Path("/tmp"), Path.home()}:
            raise ValueError(f"Unsafe kernel runtime root: {root}")
        if not any(root == mounted or root.is_relative_to(mounted) for mounted in roots):
            roots.append(root)
    args = [spec["bwrap"], "--unshare-all", "--die-with-parent", "--new-session",
            "--cap-drop", "ALL", "--clearenv", "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--dir", "/inputs"]
    for root in roots:
        args += ["--ro-bind", str(root), str(root)]
    args += ["--bind", str(workspace), "/workspace"]
    for mount in spec["mounts"]:
        args += ["--ro-bind", mount["source"], mount["target"]]
    count = max(1, min(math.ceil(spec["cpus"]), len(spec["cpu_ids"])))
    environment = {"PATH": str(Path(spec["kernel"]["executable"]).parent) + ":/usr/bin:/bin",
                   "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1",
                   "MPLCONFIGDIR": "/tmp/matplotlib", "IPYTHONDIR": "/tmp/ipython",
                   "JUPYTER_RUNTIME_DIR": "/tmp/jupyter", "TMPDIR": "/tmp",
                   "OMP_NUM_THREADS": str(count), "OPENBLAS_NUM_THREADS": str(count),
                   "MKL_NUM_THREADS": str(count)}
    for key, value in environment.items():
        args += ["--setenv", key, value]
    args += ["--chdir", "/workspace", "--remount-ro", "/", "--",
             spec["prlimit"], f"--as={spec['memory_bytes']}:{spec['memory_bytes']}",
             "--core=0:0", "--nproc=256:256", "--", spec["taskset"], "--cpu-list",
             ",".join(str(cpu) for cpu in spec["cpu_ids"][:count]), *command]
    return args


def notebook_command(spec):
    return sandbox_command(spec, [spec["kernel"]["executable"], "-m", "nbconvert",
        "--to", "notebook", "--execute", "--inplace", "/workspace/notebook.ipynb",
        "--allow-errors", "--ExecutePreprocessor.kernel_name=python3",
        f"--ExecutePreprocessor.timeout={max(1, int(spec['execution_timeout']))}"])


async def execute_notebook(spec, log_path):
    """A fresh notebook kernel per replay, as in Finch's previous container path.

    The sandbox owns a private PID namespace. Killing its launcher tears down all
    notebook descendants, including a kernel that created a separate process group.
    """
    process = await asyncio.create_subprocess_exec(*notebook_command(spec),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    tail = b""

    async def consume():
        nonlocal tail
        size = 0
        with log_path.open("wb") as stream:
            while chunk := await process.stdout.read(65536):
                size += len(chunk)
                if size > 10 * 1024**2:
                    raise RuntimeError("Notebook execution log exceeded 10 MiB")
                stream.write(chunk)
                tail = (tail + chunk)[-4000:]
        return await process.wait(), tail.decode("utf-8", errors="replace")

    try:
        return await asyncio.wait_for(consume(), timeout=spec["execution_timeout"])
    except TimeoutError as exc:
        message = (f"Finch full notebook replay timed out after {spec['execution_timeout']} seconds. "
                   f"Execution log: {log_path.name}.")
        if tail:
            message += "\nLog tail:\n" + tail.decode("utf-8", errors="replace")
        raise TimeoutError(message) from exc
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


def cpu_ids():
    return sorted(os.sched_getaffinity(0))

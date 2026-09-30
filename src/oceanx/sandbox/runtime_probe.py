"""Best-effort runtime facts. Never a prerequisite for delegation or execution."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import threading

from oceanx.sandbox.execution import current_python_runtime

SCIENTIFIC_MODULES = (
    "numpy", "pandas", "scipy", "xarray", "matplotlib", "PIL", "h5py",
    "h5netcdf", "zarr", "fsspec", "dask.array", "rasterio", "pyproj",
    "shapely", "netCDF4", "cartopy", "gsw",
)


class RuntimeCapabilityProbe:
    """One background probe, with explicit retries of only unconfirmed facts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._facts: dict = {
            "state": "unknown", "interpreter": None,
            "modules": {}, "note": "Capability probe has not completed; unknown is not unavailable.",
        }

    def snapshot(self, *, retry: bool = False) -> dict:
        with self._lock:
            if not self._running and (
                self._facts["state"] == "unknown"
                or (retry and self._facts["state"] == "incomplete")
            ):
                self._running = True
                threading.Thread(target=self._run, daemon=True, name="oceanx-runtime-probe").start()
            return copy.deepcopy(self._facts)

    def _run(self) -> None:
        note = None
        try:
            runtime = current_python_runtime()
            with self._lock:
                self._facts["interpreter"] = {
                    "executable": str(runtime.executable), "version": runtime.version,
                    "prefix": str(runtime.prefix), "environment": runtime.environment_name,
                }
                remaining = [name for name in SCIENTIFIC_MODULES if name not in self._facts["modules"]]
            script = '''
import importlib, json, sys
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
        fact = {"status": "available"}
    except (ImportError, OSError) as exc:
        fact = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps({"module": name, **fact}), flush=True)
'''
            # Isolated temporary caches avoid GUI initialization and concurrent
            # cold-cache writes. This is a subprocess, not a persistent kernel.
            with tempfile.TemporaryDirectory(prefix="oceanx-capability-") as cache_dir:
                try:
                    result = subprocess.run(
                        (str(runtime.executable), "-u", "-c", script, json.dumps(remaining)),
                        capture_output=True, text=True, timeout=60, check=False,
                        env={**os.environ, "PYTHONNOUSERSITE": "1", "MPLBACKEND": "Agg",
                             "MPLCONFIGDIR": cache_dir},
                    )
                    output = result.stdout
                    if result.returncode:
                        note = f"Probe incomplete (exit {result.returncode}): {result.stderr[-1000:]}"
                except subprocess.TimeoutExpired as exc:
                    output = exc.stdout or ""
                    note = "Probe incomplete: time limit reached; unreported modules remain unknown."
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            for line in output.splitlines():
                try:
                    fact = json.loads(line)
                    if not isinstance(fact, dict):
                        continue
                    name = fact.pop("module", None)
                    if name in remaining and fact.get("status") in {"available", "unavailable"}:
                        with self._lock:
                            self._facts["modules"][name] = fact
                except (ValueError, TypeError):
                    continue
        except Exception as exc:  # noqa: BLE001
            # Diagnostic exceptions do not escape the background worker and
            # cannot alter a work order's execution state.
            note = f"Probe incomplete: {type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                complete = len(self._facts["modules"]) == len(SCIENTIFIC_MODULES)
                self._facts["state"] = "complete" if complete else "incomplete"
                self._facts["note"] = note if not complete else None
                self._running = False


_PROBES: dict[tuple, RuntimeCapabilityProbe] = {}
_PROBES_LOCK = threading.Lock()


def runtime_capabilities(*, retry: bool = False) -> dict:
    """Start once per configured environment; immediately return known facts."""
    key = tuple(os.environ.get(name) for name in (
        "OCEAN_SANDBOX_PYTHON", "OCEAN_CONDA_ENV", "CONDA_PREFIX", "CONDA_ENVS_PATH",
    ))
    with _PROBES_LOCK:
        probe = _PROBES.setdefault(key, RuntimeCapabilityProbe())
    return probe.snapshot(retry=retry)

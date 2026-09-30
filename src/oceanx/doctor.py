"""Machine-readable local capability report for Ocean Partner execution."""

from __future__ import annotations

import platform
import sys
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from oceanx.desktop_contract import (
    DESKTOP_BACKEND_SCHEMA,
    DESKTOP_RUNTIME_CAPABILITY_SCHEMA,
    DESKTOP_RUNTIME_CONNECTIONS,
)
from oceanx.sandbox import (
    get_sandbox_execution_capabilities,
)
from oceanx.sandbox.runtime_probe import runtime_capabilities
from oceanx.scientific_runtime import frozen_scientific_runtime_capability
from oceanx.skills import ocean_skill_metadata

_OPTIONAL_EXTRAS = {
    "numpy": "array computation",
    "pandas": "tabular data",
    "xarray": "labelled array and NetCDF workflows",
    "matplotlib": "static plotting",
    "h5py": "HDF5 bindings required by h5netcdf",
    "h5netcdf": "NetCDF via h5py",
    "netCDF4": "NetCDF4 bindings",
    "zarr": "Zarr stores",
    "cartopy": "map projections",
    "gsw": "TEOS-10 seawater calculations",
}

def ocean_doctor() -> dict[str, Any]:
    """Describe the exact local execution capabilities without attempting installation."""

    sandbox = get_sandbox_execution_capabilities()
    facts = runtime_capabilities()
    interpreter = facts.get("interpreter") or {}
    # Availability here means the execution tool can be attempted. A pending
    # diagnostic must not disable it; real launches validate their interpreter.
    expert_execution_available = sandbox.available
    frozen_runtime = frozen_scientific_runtime_capability()
    extras = {
        name: {
            "available": {"available": True, "unavailable": False}.get(
                facts["modules"].get(name, {}).get("status")
            ),
            "status": facts["modules"].get(name, {}).get("status", "unknown"),
            "purpose": purpose,
        }
        for name, purpose in _OPTIONAL_EXTRAS.items()
    }
    nc, h5nc, h5 = (extras[name]["available"] for name in ("netCDF4", "h5netcdf", "h5py"))
    netcdf_available = (
        True if nc is True or (h5nc is True and h5 is True)
        else False if nc is False and (h5nc is False or h5 is False)
        else None
    )
    return {
        "schema_version": "ocean-doctor/v1",
        "backend_schema": DESKTOP_BACKEND_SCHEMA,
        "interpreter": {
            "executable": interpreter.get("executable"),
            "implementation": platform.python_implementation(),
            "version": interpreter.get("version"),
            "environment": interpreter.get("environment"),
            "prefix": interpreter.get("prefix"),
        },
        "capability_probe": facts,
        "sandbox": asdict(sandbox),
        "frozen_scientific_runtime": frozen_runtime,
        "extras": extras,
        "capabilities": {
            "expert_code_execution": expert_execution_available,
            "web_search": True,
            "jina_reader": True,
            "maps": extras["cartopy"]["available"],
            "zarr": extras["zarr"]["available"],
            "gsw": extras["gsw"]["available"],
            "netcdf": netcdf_available,
        },
        "unavailable_reasons": {
            "expert_code_execution": (
                None
                if expert_execution_available
                else sandbox.reason
            ),
            "web_search": None,
            "jina_reader": None,
            "maps": facts["modules"].get("cartopy", {}).get("error"),
            "zarr": facts["modules"].get("zarr", {}).get("error"),
            "gsw": facts["modules"].get("gsw", {}).get("error"),
            "netcdf": (
                None
                if netcdf_available is not False
                else "Neither probed NetCDF backend is usable; see extras and capability_probe."
            ),
        },
        "runtime": {
            "backend_sys_prefix": sys.prefix,
            "sandbox_sys_prefix": interpreter.get("prefix"),
        },
    }


def desktop_runtime_capabilities(
    *,
    skill_capabilities: Iterable[str] = (),
) -> dict[str, Any]:
    """Return the bounded runtime projection that may cross into a renderer.

    ``ocean_doctor`` remains an operator-facing local diagnostic and can include
    executable or installation details. The Desktop handshake must never expose
    those details to an untrusted renderer, so this projection is deliberately
    constructed from a small, reviewed allowlist rather than by filtering the
    diagnostic document after the fact.
    """

    doctor = ocean_doctor()
    capabilities = doctor["capabilities"]
    frozen_runtime = doctor["frozen_scientific_runtime"]
    scientific_runtime: dict[str, Any] = {
        "available": bool(frozen_runtime.get("available")),
    }
    if scientific_runtime["available"]:
        schema_version = frozen_runtime.get("schema_version")
        fingerprint = frozen_runtime.get("fingerprint_sha256")
        dependency_count = frozen_runtime.get("dependency_count")
        if isinstance(schema_version, str):
            scientific_runtime["schema_version"] = schema_version
        if isinstance(fingerprint, str):
            scientific_runtime["fingerprint_sha256"] = fingerprint
        if isinstance(dependency_count, int) and not isinstance(dependency_count, bool):
            scientific_runtime["dependency_count"] = dependency_count

    return {
        "schema_version": DESKTOP_RUNTIME_CAPABILITY_SCHEMA,
        "backend_schema": DESKTOP_BACKEND_SCHEMA,
        "connections": [
            {
                "id": identifier,
                "label": label,
                "available": bool(capabilities.get(identifier)),
            }
            for identifier, label in DESKTOP_RUNTIME_CONNECTIONS
        ],
        "scientific_runtime": scientific_runtime,
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
            }
            for skill in ocean_skill_metadata(capabilities=skill_capabilities)
        ],
    }


__all__ = ["desktop_runtime_capabilities", "ocean_doctor"]

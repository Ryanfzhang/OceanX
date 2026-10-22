"""The single server-owned web configuration file."""
from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from oceanx.launch_config import ModelConfig as WebModelConfig
from oceanx.launch_config import parse_model_config

_SECTIONS = {"server", "model", "models", "map", "cleanup"}


def _read_config(path: Path) -> dict:
    try:
        with path.expanduser().open("rb") as stream:
            payload = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        # TOML parser errors can quote a line containing a credential.
        raise ValueError("Cannot read web config; check the file and TOML syntax") from None
    if set(payload) - _SECTIONS:
        raise ValueError("Unknown web config section; use server, model, models, map or cleanup")
    return payload


def load_web_model_config(path: Path) -> WebModelConfig:
    """Load only model profiles, using the same source as the complete web config."""
    return parse_model_config(_read_config(path))


@dataclass(frozen=True)
class WebConfig:
    workspace: Path
    frontend: Path
    source_roots: tuple[Path, ...]
    port: int
    log_dir: Path
    sandbox_python: Path | None
    cache_hours: float
    archived_cache_hours: float
    sweep_seconds: float
    model_config: WebModelConfig = field(repr=False)
    carto_api_key: str = field(default="", repr=False)


def load_web_config(path: Path) -> WebConfig:
    """All relative paths are relative to this one TOML file, never the shell cwd."""
    path = path.expanduser().resolve()
    payload = _read_config(path)
    tables = {}
    for section, fields in {
        "server": {"workspace", "frontend", "source_roots", "port", "log_dir", "sandbox_python"},
        "cleanup": {"cache_hours", "archived_cache_hours", "sweep_minutes"},
        "map": {"carto_api_key"},
    }.items():
        table = payload.get(section, {})
        if not isinstance(table, dict) or set(table) - fields:
            raise ValueError(f"Unknown or invalid settings in [{section}]")
        tables[section] = table

    def local_path(value, name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Set a non-empty path for {name}")
        result = Path(value).expanduser()
        return (path.parent / result).absolute() if not result.is_absolute() else result.absolute()

    server, cleanup, basemap = (tables[k] for k in ("server", "cleanup", "map"))
    workspace = local_path(server.get("workspace"), "server.workspace").resolve()
    frontend = local_path(server["frontend"], "server.frontend") if "frontend" in server else (
        Path(__file__).resolve().parents[3] / "frontend/ocean-web/dist")
    port = server.get("port", 8765)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("server.port must be an integer between 1 and 65535")
    roots = server.get("source_roots", [])
    if not isinstance(roots, list):
        raise ValueError("server.source_roots must be an array of paths")  # noqa: TRY004 - user config error
    source_roots = tuple(local_path(root, "server.source_roots") for root in roots)
    if not all(root.is_dir() for root in source_roots):
        raise ValueError("Every source root must be an existing directory")
    log_dir = local_path(server["log_dir"], "server.log_dir") if "log_dir" in server else workspace / ".oceanx-web"
    sandbox = local_path(server["sandbox_python"], "server.sandbox_python") if "sandbox_python" in server else None
    if sandbox is not None and (not sandbox.is_file() or not os.access(sandbox, os.X_OK)):
        raise ValueError("server.sandbox_python must be an executable Python file")
    times = []
    for name, default in (("cache_hours", 24), ("archived_cache_hours", 6), ("sweep_minutes", 60)):
        value = cleanup.get(name, default)
        if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
            raise ValueError(f"cleanup.{name} must be finite and positive")
        times.append(float(value))
    carto = basemap.get("carto_api_key", "")
    if not isinstance(carto, str):
        raise ValueError("map.carto_api_key must be a string")  # noqa: TRY004 - user config error
    return WebConfig(workspace, frontend.resolve(), source_roots, port, log_dir, sandbox,
                     times[0], times[1], times[2] * 60, parse_model_config(payload), carto.strip())

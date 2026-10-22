"""Server-owned model settings, translated into isolated native profiles."""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_ROLES = ("coordinator", "expert")
_FIELDS = {"provider", "model", "base_url", "api_key", "api_key_env", "max_tokens", "image_inputs"}
_SECTIONS = {"server", "model", "models", "map", "cleanup"}


@dataclass(frozen=True, repr=False)
class WebModelConfig:
    # Credentials must never appear in repr, logs or the browser's config response.
    roles: dict = field(repr=False)

    def status(self):
        profiles = {
            role: {"profile": f"ocean-web-{role}", "label": f"Web {role}",
                   "provider": profile["provider"], "model": profile["model"],
                   "configured": bool(profile["api_key"]),
                   "imageInputs": bool(profile["image_inputs"])}
            for role, profile in self.roles.items()
        }
        return {**profiles, "configured": all(p["configured"] for p in profiles.values())}

    def materialize(self, directory: Path) -> Path:
        """Use the existing model loader without modifying Desktop settings."""
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("Web model state must not be a symlink")
        directory.chmod(0o700)
        profiles, credentials, slots = {}, {}, {}
        for role, profile in self.roles.items():
            slot = f"ocean-web-{role}"
            slots[role] = slot
            profiles[slot] = {"label": f"Web {role}", "provider": profile["provider"],
                              "default_model": profile["model"], "base_url": profile["base_url"],
                              "image_inputs": profile["image_inputs"], "credential_slot": slot}
            credentials[f"profile:{slot}"] = {"api_key": profile["api_key"]}
        # Native profiles have one output-token limit shared by both roles.
        payload = {"active_profile": slots["coordinator"], "role_profiles": slots,
                   "profiles": profiles, "max_tokens": self.roles["coordinator"]["max_tokens"]}
        for filename, value in (("settings.json", payload), ("credentials.json", credentials)):
            fd, temporary = tempfile.mkstemp(dir=directory)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(value, stream)
                    stream.write("\n")
                os.replace(temporary, directory / filename)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return directory.resolve()


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
    return _models(_read_config(path))


def _models(payload: dict) -> WebModelConfig:
    common = payload.get("model", {})
    overrides = payload.get("models", {})
    if not isinstance(common, dict) or not isinstance(overrides, dict) or set(overrides) - set(_ROLES):
        raise ValueError("Invalid web model tables")
    roles = {}
    for role in _ROLES:
        override = overrides.get(role, {})
        if not isinstance(override, dict) or (set(common) | set(override)) - _FIELDS:
            raise ValueError(f"Unknown web model setting for {role}")
        raw = {**common, **override}
        # An override may switch from an environment credential to a literal, or vice versa.
        if "api_key" in override and "api_key_env" not in override:
            raw.pop("api_key_env", None)
        if "api_key_env" in override and "api_key" not in override:
            raw.pop("api_key", None)
        provider, model = raw.get("provider"), raw.get("model")
        if not isinstance(provider, str) or provider not in {"deepseek", "openai", "anthropic"}:
            raise ValueError(f"Set a supported provider for {role}: deepseek, openai or anthropic")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"Set a model ID for {role}")
        endpoint = raw.get("base_url")
        if endpoint is not None:
            if not isinstance(endpoint, str):
                raise ValueError(f"Invalid base_url for {role}")
            try:
                url = urlsplit(endpoint)
                valid = (url.scheme in {"http", "https"} and url.hostname and not url.username
                         and not url.password and not url.query and not url.fragment)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"Invalid base_url for {role}")
        if ("api_key" in raw) == ("api_key_env" in raw):
            raise ValueError(f"Set exactly one of api_key or api_key_env for {role}")
        key = raw.get("api_key")
        if "api_key_env" in raw:
            name = raw["api_key_env"]
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"Invalid api_key_env for {role}")
            key = os.environ.get(name)
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"No API key configured for web {role}")
        limit = raw.get("max_tokens", 65_536)
        if type(limit) is not int or limit < 24_576:
            raise ValueError("max_tokens must be an integer of at least 24576 (native model limit)")
        images = raw.get("image_inputs")
        if images is not None and not isinstance(images, bool):
            raise ValueError(f"image_inputs must be true or false for {role}")
        roles[role] = {"provider": provider, "model": model.strip(), "base_url": endpoint,
                       "api_key": key.strip(), "max_tokens": limit, "image_inputs": images}
    if roles["coordinator"]["max_tokens"] != roles["expert"]["max_tokens"]:
        raise ValueError("Both roles must use the same max_tokens (native model limit)")
    return WebModelConfig(roles)


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
                     times[0], times[1], times[2] * 60, _models(payload), carto.strip())

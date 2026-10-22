"""Launch the existing Desktop app with one local desktop.toml configuration."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from oceanx.launch_config import ModelConfig, parse_model_config


@dataclass(frozen=True)
class DesktopConfig:
    runtime_dir: Path
    sandbox_python: Path | None
    model_config: ModelConfig = field(repr=False)
    carto_api_key: str = field(default="", repr=False)


def load_desktop_config(path: Path) -> DesktopConfig:
    path = path.expanduser().resolve()
    try:
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError("Cannot read desktop config; check the file and TOML syntax") from None
    if set(payload) - {"desktop", "model", "models", "map"}:
        raise ValueError("Unknown desktop config section; use desktop, model, models or map")
    desktop, basemap = payload.get("desktop", {}), payload.get("map", {})
    if not isinstance(desktop, dict) or set(desktop) - {"runtime_dir", "sandbox_python"}:
        raise ValueError("Unknown or invalid settings in [desktop]")
    if not isinstance(basemap, dict) or set(basemap) - {"carto_api_key"}:
        raise ValueError("Unknown or invalid settings in [map]")

    def local_path(value, name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Set a non-empty path for {name}")
        result = Path(value).expanduser()
        return (path.parent / result).resolve()

    runtime = local_path(desktop.get("runtime_dir", ".oceanx/desktop-launch"), "desktop.runtime_dir")
    # Always generate native profiles in the launcher's own directory. Never
    # overwrite the ordinary Desktop config when adopting the TOML launcher.
    legacy = Path(os.environ.get("OCEANMIND_CONFIG_DIR") or Path.home() / ".oceanmind").expanduser().resolve()
    if runtime == legacy:
        raise ValueError("desktop.runtime_dir must be separate from the existing Desktop configuration")
    sandbox = local_path(desktop["sandbox_python"], "desktop.sandbox_python") if "sandbox_python" in desktop else None
    if sandbox is not None and (not sandbox.is_file() or not os.access(sandbox, os.X_OK)):
        raise ValueError("desktop.sandbox_python must be an executable Python file")
    carto = basemap.get("carto_api_key", "")
    if not isinstance(carto, str):
        raise ValueError("map.carto_api_key must be a string")  # noqa: TRY004 - config error
    return DesktopConfig(runtime, sandbox, parse_model_config(payload, namespace="desktop"), carto.strip())


def prepare_environment(config: DesktopConfig, repo: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["OCEANMIND_CONFIG_DIR"] = str(config.model_config.materialize(config.runtime_dir))
    environment["OCEAN_PYTHON"] = sys.executable
    environment["OCEAN_SANDBOX_PYTHON"] = str(config.sandbox_python or sys.executable)
    environment["VITE_CARTO_BASEMAPS_API_KEY"] = config.carto_api_key
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (str(repo / "src"), environment.get("PYTHONPATH"))))
    # Never let automation-specific flags replace the normal backend/profile.
    for key in tuple(environment):
        if key == "ELECTRON_RUN_AS_NODE" or key.startswith("OCEAN_DESKTOP_TEST_"):
            environment.pop(key)
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("desktop.toml"))
    parser.add_argument("--check", action="store_true", help="Validate config without opening Desktop or calling a model")
    args = parser.parse_args()
    try:
        config = load_desktop_config(args.config)
    except ValueError as exc:
        parser.error(str(exc))
    repo = Path(__file__).resolve().parents[2]
    if args.check:
        print(json.dumps({"configured": True, "models": config.model_config.status(),
                          "map_configured": bool(config.carto_api_key)}))
        return
    if not (repo / "frontend/ocean-desktop/node_modules").is_dir():
        parser.error("Install Desktop dependencies first: npm --prefix frontend/ocean-desktop ci")
    os.umask(0o077)
    environment = prepare_environment(config, repo)
    os.chdir(repo / "frontend/ocean-desktop")
    # Keep sidecar checks, build, Electron and all agent/backend behavior native.
    os.execvpe("npm", ["npm", "start"], environment)


if __name__ == "__main__":
    main()

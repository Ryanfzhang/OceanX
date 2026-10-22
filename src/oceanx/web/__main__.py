"""Run the single-user web entry using one server-owned web.toml file."""
import argparse
import copy
import os
from pathlib import Path

import uvicorn

from oceanx.web.config import load_web_config
from oceanx.web.server import WebSettings, create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("web.toml"),
                        help="One web configuration file (default: ./web.toml)")
    args = parser.parse_args()
    try:
        config = load_web_config(args.config)
    except ValueError as exc:
        parser.error(str(exc))
    if not (config.frontend / "index.html").is_file():
        parser.error("Web frontend is not built; run npm ci and npm run build in frontend/ocean-web")
    os.umask(0o077)
    config.log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = WebSettings(
        workspace=config.workspace, frontend=config.frontend, source_roots=config.source_roots,
        cache_hours=config.cache_hours, archived_cache_hours=config.archived_cache_hours,
        sweep_seconds=config.sweep_seconds, model_config=config.model_config,
        log_dir=config.log_dir, sandbox_python=config.sandbox_python, carto_api_key=config.carto_api_key,
    )
    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["handlers"]["web_file"] = {
        "class": "logging.FileHandler", "filename": str(config.log_dir / "web-console.log"),
        "mode": "a", "encoding": "utf-8", "formatter": "default",
    }
    log_config["loggers"]["uvicorn"]["handlers"].append("web_file")
    log_config["loggers"]["uvicorn.access"]["handlers"].append("web_file")
    log_config["root"] = {"level": "INFO", "handlers": ["default", "web_file"]}
    # No public binding option: remote access is through the owner's SSH tunnel.
    uvicorn.run(create_app(settings), host="127.0.0.1", port=config.port,
                ws_max_size=1024 * 1024, log_config=log_config)


if __name__ == "__main__":
    main()

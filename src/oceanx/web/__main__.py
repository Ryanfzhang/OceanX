"""Run a single-user browser entry on a server and forward its port with SSH."""
import argparse
import math
import os
from pathlib import Path

import uvicorn

from oceanx.web.config import load_web_model_config
from oceanx.web.server import WebSettings, create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True,
                        help="Server-only TOML model configuration; never inherits Desktop profiles")
    parser.add_argument("--workspace", type=Path, required=True, help="One server-side project directory")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-source-root", type=Path, action="append", default=[],
                        help="Allow exact source paths under this directory; repeatable, never listed in the UI")
    parser.add_argument("--frontend", type=Path,
                        default=Path(__file__).resolve().parents[3] / "frontend/ocean-web/dist")
    parser.add_argument("--cache-hours", type=float, default=24)
    parser.add_argument("--archived-cache-hours", type=float, default=6)
    parser.add_argument("--sweep-minutes", type=float, default=60)
    args = parser.parse_args()
    try:
        model_config = load_web_model_config(args.config)
    except ValueError as exc:
        parser.error(str(exc))
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if not all(math.isfinite(x) and x > 0 for x in (args.cache_hours, args.archived_cache_hours, args.sweep_minutes)):
        parser.error("cleanup times must be finite and positive")
    if not (args.frontend / "index.html").is_file():
        parser.error("Web frontend is not built; run npm ci and npm run build in frontend/ocean-web")
    roots = []
    for root in args.allow_source_root:
        root = root.expanduser().absolute()
        if not root.is_dir():
            parser.error("Every allowed source root must be an existing directory")
        roots.append(root)
    os.umask(0o077)
    workspace = args.workspace.expanduser().resolve()
    settings = WebSettings(workspace, args.frontend.resolve(), tuple(roots),
                           args.cache_hours, args.archived_cache_hours, args.sweep_minutes * 60,
                           model_config)
    # No public binding option: remote access is through the owner's SSH tunnel.
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, ws_max_size=1024 * 1024)


if __name__ == "__main__":
    main()

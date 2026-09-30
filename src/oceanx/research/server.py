"""Single-host Agent Server entry point used by desktop and benchmarking."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

GRAPH_EXPORTS = {"coordinator": "coordinator"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not os.environ.get("OCEAN_SERVER_TOKEN"):
        raise RuntimeError("A local-launch authentication token is required")
    root = args.state.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["OCEAN_STATE_DIRECTORY"] = str(root)
    # This is not a research stopping policy. Let agents finish or be cancelled;
    # the framework's default 24-hour background-run deadline is disabled.
    os.environ["BG_JOB_TIMEOUT_SECS"] = "inf"
    # Server checkpoint persistence is relative to cwd. Do not put it in the source tree.
    os.chdir(root)
    from langgraph_api.cli import run_server
    run_server(host="127.0.0.1", port=args.port, reload=False, open_browser=False,
               n_jobs_per_worker=64, allow_blocking=True, disable_persistence=False,
               graphs={k: f"oceanx.research.graphs:{v}" for k, v in GRAPH_EXPORTS.items()},
               http={"app": "oceanx.research.app:app"},
               auth={"path": "oceanx.research.auth:auth"})


if __name__ == "__main__":
    main()

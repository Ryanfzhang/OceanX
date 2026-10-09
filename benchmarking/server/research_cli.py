#!/usr/bin/env python3
"""Run `ocean research ...` (labels, the meta-agent's review, marks, snapshots) with benchmarking/.env.

The offline meta-agent and node labels use the same model and credentials as the analysis roles
(DeepSeek Flash by default). The server's everyday OceanX settings are neither read nor changed.
Example: python benchmarking/server/research_cli.py library --project <evolution-runs-folder>
"""
import os
import sys

from benchmark_models import install_oceanx_models


def main():
    # One review of a dozen tasks is all a benchmark round gets, so the repeated code of one
    # question is enough for a tool here; everyday OceanX asks for two (toolbook.py).
    os.environ.setdefault("OCEANX_TOOL_MIN_SUPPORT", "1")
    install_oceanx_models()
    from oceanx.research.cli import research_app
    research_app(args=sys.argv[1:], prog_name="research_cli.py")


if __name__ == "__main__":
    main()

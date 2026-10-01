#!/usr/bin/env python3
"""Run `ocean research ...` (labels, lesson mining, lesson decisions) with the benchmark.yaml model.

The meta model used for judge labels and lesson mining is then the same model as the benchmark runs,
and the server's everyday OceanX model settings are neither read nor changed.
Example: python benchmarking/server/research_cli.py lessons --project <evolution-runs-folder>
"""
import sys

from benchmark_models import install_oceanx_models


def main():
    install_oceanx_models()
    from oceanx.research.cli import research_app
    research_app(args=sys.argv[1:], prog_name="research_cli.py")


if __name__ == "__main__":
    main()

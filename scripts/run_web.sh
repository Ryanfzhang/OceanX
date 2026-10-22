#!/usr/bin/env bash
set -euo pipefail
umask 077
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
# Source always comes from this checkout. Optional isolated dependencies are
# useful when the server's shared conda environment must remain untouched.
export PYTHONPATH="$repo/.web-python-deps:$repo/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m oceanx.web "$@"

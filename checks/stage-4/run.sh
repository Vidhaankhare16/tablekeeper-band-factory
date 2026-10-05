#!/usr/bin/env bash
# Usage: bash checks/stage-4/run.sh <stage-4 base url> [pytest args...]
#   e.g. bash checks/stage-4/run.sh http://127.0.0.1:8084 -q
# The stage-4 service must already be running. The upgrade checks need the accepted stage-1, stage-2 and stage-3 services: this
# script builds and starts them (docker, ports 8081, 8082, 8083) unless TK_PREV_URL / TK_PREV2_URL / TK_PREV3_URL are already set.
set -euo pipefail
BASE="${1:?usage: run.sh <base-url> [pytest args]}"; shift || true
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=python3
[ -x /tmp/hv/bin/python ] && PY=/tmp/hv/bin/python
$PY -c "import pytest" 2>/dev/null || $PY -m pip install -q pytest
$PY -c "import playwright" 2>/dev/null || $PY -m pip install -q playwright==1.63.0
if [ -z "${TK_PREV_URL:-}" ]; then bash "$HERE/prev_up.sh" 52137c093465d88285cd0d433ca751e912e131a3 stage-1 8081 tk-prev1; export TK_PREV_URL=http://127.0.0.1:8081; fi
if [ -z "${TK_PREV2_URL:-}" ]; then bash "$HERE/prev_up.sh" a1706213274dcdacc4f35b935af27c935ebccc3d stage-2 8082 tk-prev2; export TK_PREV2_URL=http://127.0.0.1:8082; fi
if [ -z "${TK_PREV3_URL:-}" ]; then bash "$HERE/prev_up.sh" b5f097dc3a7e433298033c24209e6e6c56fa753e stage-3 8083 tk-prev3; export TK_PREV3_URL=http://127.0.0.1:8083; fi
TK_BASE_URL="$BASE" exec $PY -m pytest -p no:cacheprovider --rootdir "$HERE" "$HERE" "$@"

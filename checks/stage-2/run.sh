#!/usr/bin/env bash
# Usage: bash checks/stage-2/run.sh <stage-2 base url> [pytest args...]
#   e.g. bash checks/stage-2/run.sh http://127.0.0.1:8080 -q
# The stage-2 service must already be running. The upgrade checks need the accepted stage-1 service: this script
# starts it (docker, port 8081) unless TK_PREV_URL is already set to a running one.
set -euo pipefail
BASE="${1:?usage: run.sh <base-url> [pytest args]}"; shift || true
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=python3
[ -x /tmp/hv/bin/python ] && PY=/tmp/hv/bin/python
$PY -c "import pytest" 2>/dev/null || $PY -m pip install -q pytest
$PY -c "import playwright" 2>/dev/null || $PY -m pip install -q playwright==1.63.0
if [ -z "${TK_PREV_URL:-}" ]; then bash "$HERE/prev_up.sh" 8081; export TK_PREV_URL=http://127.0.0.1:8081; fi
TK_BASE_URL="$BASE" exec $PY -m pytest -p no:cacheprovider --rootdir "$HERE" "$HERE" "$@"

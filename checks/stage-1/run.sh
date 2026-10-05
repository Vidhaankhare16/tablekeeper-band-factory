#!/usr/bin/env bash
# Usage: bash checks/stage-1/run.sh <base-url> [pytest args...]
#   e.g. bash checks/stage-1/run.sh http://127.0.0.1:8080 -x -q
# The service must already be running (docker run -e PORT=8080 -p 8080:8080 <image>).
set -euo pipefail
BASE="${1:?usage: run.sh <base-url> [pytest args]}"; shift || true
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=python3
[ -x /tmp/hv/bin/python ] && PY=/tmp/hv/bin/python
$PY -c "import pytest" 2>/dev/null || $PY -m pip install -q pytest
TK_BASE_URL="$BASE" exec $PY -m pytest -p no:cacheprovider --rootdir "$HERE" "$HERE" "$@"

#!/usr/bin/env bash
# Build the accepted stage-1 image (revision 52137c093465d88285cd0d433ca751e912e131a3) from git history and run it on
# port ${1:-8081}, for the upgrade checks. Usage: bash checks/stage-2/prev_up.sh [port]
set -euo pipefail
PORT="${1:-8081}"
REV=52137c093465d88285cd0d433ca751e912e131a3
ROOT="$(git rev-parse --show-toplevel)"
D="$(mktemp -d)"
git -C "$ROOT" cat-file -e "$REV^{commit}" 2>/dev/null || git -C "$ROOT" fetch -q origin
git -C "$ROOT" archive "$REV" stage-1 | tar -x -C "$D"
docker build -q -t tk-prev-s1 "$D/stage-1" >/dev/null
docker rm -f tk-prev >/dev/null 2>&1 || true
docker run -d --name tk-prev --cpus 2 --memory 2g -e PORT=8080 -p "$PORT":8080 tk-prev-s1 >/dev/null
for i in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && { echo "stage-1 ($REV) healthy on :$PORT"; exit 0; }; sleep 1; done
echo "stage-1 container did not become healthy" >&2; exit 1

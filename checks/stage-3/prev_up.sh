#!/usr/bin/env bash
# Build an accepted earlier stage from git history and run it on a local port, for the upgrade checks.
# Usage: bash checks/stage-3/prev_up.sh <revision> <stage-folder> <port> <container-name>
#   stage 1 accepted: 52137c093465d88285cd0d433ca751e912e131a3 (stage-1)
#   stage 2 accepted: a1706213274dcdacc4f35b935af27c935ebccc3d (stage-2)
set -euo pipefail
REV="${1:?revision}"; DIR="${2:?stage folder}"; PORT="${3:?port}"; NAME="${4:?name}"
ROOT="$(git rev-parse --show-toplevel)"
D="$(mktemp -d)"
git -C "$ROOT" cat-file -e "$REV^{commit}" 2>/dev/null || git -C "$ROOT" fetch -q origin
git -C "$ROOT" archive "$REV" "$DIR" | tar -x -C "$D"
docker build -q -t "tk-$NAME" "$D/$DIR" >/dev/null
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --cpus 2 --memory 2g -e PORT=8080 -p "$PORT":8080 "tk-$NAME" >/dev/null
for i in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && { echo "$DIR ($REV) healthy on :$PORT"; exit 0; }; sleep 1; done
echo "$NAME did not become healthy" >&2; exit 1

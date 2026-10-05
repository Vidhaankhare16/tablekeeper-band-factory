#!/usr/bin/env bash
# Seat runtime: start the Docker daemon in cloud sessions, pulling public images through the
# mirror.gcr.io Docker Hub mirror (shared cloud IPs hit Docker Hub's anonymous rate limit).
# Runs on every session start and resume; does nothing outside cloud sessions.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
SUDO=""; [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo -n"
if docker info --format '{{.RegistryConfig.Mirrors}}' 2>/dev/null | grep -q mirror.gcr.io; then exit 0; fi
$SUDO mkdir -p /etc/docker
echo '{"registry-mirrors": ["https://mirror.gcr.io"]}' | $SUDO tee /etc/docker/daemon.json >/dev/null
if docker info >/dev/null 2>&1; then $SUDO pkill dockerd; sleep 3; fi
nohup $SUDO dockerd >/tmp/dockerd.log 2>&1 &
for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && exit 0; sleep 1; done
echo "dockerd did not become ready; see /tmp/dockerd.log" >&2
exit 0

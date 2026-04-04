#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR=${CONFIG_DIR:-/srv/flaresolverr/config}
IMAGE=${IMAGE:-ghcr.io/smeinecke/flaresolverr:latest}

podman run -d \
  --name flaresolverr \
  --replace \
  -p 127.0.0.1:8191:8191 \
  -v "${CONFIG_DIR}:/config:Z" \
  -e LOG_LEVEL="${LOG_LEVEL:-info}" \
  -e LOG_FILE="${LOG_FILE:-/config/flaresolverr.log}" \
  -e TZ="${TZ:-UTC}" \
  --restart unless-stopped \
  "${IMAGE}"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
IMAGE=${IMAGE:-flaresolverr-dnsdist:latest}

podman build \
  -t "${IMAGE}" \
  -f "${SCRIPT_DIR}/dnsdist/Containerfile" \
  "${SCRIPT_DIR}/dnsdist"

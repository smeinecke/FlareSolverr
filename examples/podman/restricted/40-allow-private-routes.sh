#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <private-cidr> [<private-cidr> ...]" >&2
  exit 1
fi

CONTAINER_NAME=${CONTAINER_NAME:-flaresolverr}
GATEWAY=${GATEWAY:-10.89.60.1}
PID=$(podman inspect -f '{{.State.Pid}}' "${CONTAINER_NAME}")

if [[ -z "${PID}" || "${PID}" == "0" ]]; then
  echo "could not determine PID for container ${CONTAINER_NAME}" >&2
  exit 1
fi

nsenter -t "${PID}" -n ip route del default || true

for cidr in "$@"; do
  nsenter -t "${PID}" -n ip route replace "${cidr}" via "${GATEWAY}"
done

nsenter -t "${PID}" -n ip route

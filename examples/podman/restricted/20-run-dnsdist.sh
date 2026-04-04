#!/usr/bin/env bash
set -euo pipefail

RESTRICTED_NETWORK=${RESTRICTED_NETWORK:-flaresolverr_restricted}
DNS_UPLINK_NETWORK=${DNS_UPLINK_NETWORK:-flaresolverr_dns_uplink}
DNSDIST_IP=${DNSDIST_IP:-10.89.60.53}
DNSDIST_BIND_ADDRESS=${DNSDIST_BIND_ADDRESS:-${DNSDIST_IP}:53}
DNSDIST_ALLOW_FROM=${DNSDIST_ALLOW_FROM:-10.89.60.0/24}
IMAGE=${IMAGE:-flaresolverr-dnsdist:latest}

podman run -d \
  --name flaresolverr-dnsdist \
  --replace \
  --network "${RESTRICTED_NETWORK}" \
  --ip "${DNSDIST_IP}" \
  -e DNSDIST_BIND_ADDRESS="${DNSDIST_BIND_ADDRESS}" \
  -e DNSDIST_ALLOW_FROM="${DNSDIST_ALLOW_FROM}" \
  -e PUBLIC_DNSDIST_URL="${PUBLIC_DNSDIST_URL:-https://raw.githubusercontent.com/disposable/public-dns/main/txt/dnsdist.conf}" \
  --restart unless-stopped \
  "${IMAGE}"

podman network connect "${DNS_UPLINK_NETWORK}" flaresolverr-dnsdist 2>/dev/null || true

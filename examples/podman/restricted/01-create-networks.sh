#!/usr/bin/env bash
set -euo pipefail

RESTRICTED_NETWORK=${RESTRICTED_NETWORK:-flaresolverr_restricted}
RESTRICTED_SUBNET=${RESTRICTED_SUBNET:-10.89.60.0/24}
RESTRICTED_GATEWAY=${RESTRICTED_GATEWAY:-10.89.60.1}
DNS_UPLINK_NETWORK=${DNS_UPLINK_NETWORK:-flaresolverr_dns_uplink}
DNS_UPLINK_SUBNET=${DNS_UPLINK_SUBNET:-10.89.61.0/24}
DNS_UPLINK_GATEWAY=${DNS_UPLINK_GATEWAY:-10.89.61.1}

if ! podman network inspect "${RESTRICTED_NETWORK}" >/dev/null 2>&1; then
  podman network create \
    --subnet "${RESTRICTED_SUBNET}" \
    --gateway "${RESTRICTED_GATEWAY}" \
    --disable-dns \
    "${RESTRICTED_NETWORK}"
fi

if ! podman network inspect "${DNS_UPLINK_NETWORK}" >/dev/null 2>&1; then
  podman network create \
    --subnet "${DNS_UPLINK_SUBNET}" \
    --gateway "${DNS_UPLINK_GATEWAY}" \
    "${DNS_UPLINK_NETWORK}"
fi

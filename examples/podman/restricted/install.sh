#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "please run as root (use sudo)" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SYSTEMD_DIR=${SYSTEMD_DIR:-/etc/systemd/system}
DNSDIST_CONFIG_DIR=${DNSDIST_CONFIG_DIR:-/etc/flaresolverr}
DNSDIST_CONFIG_PATH=${DNSDIST_CONFIG_PATH:-${DNSDIST_CONFIG_DIR}/dnsdist.conf}
ENV_FILE=${ENV_FILE:-${DNSDIST_CONFIG_DIR}/podman-restricted.env}
CONFIG_DIR=${CONFIG_DIR:-/srv/flaresolverr/config}
IMAGE=${IMAGE:-ghcr.io/smeinecke/flaresolverr:latest}
DNSDIST_IMAGE=${DNSDIST_IMAGE:-docker.io/powerdns/dnsdist-19:latest}
RESTRICTED_NETWORK=${RESTRICTED_NETWORK:-flaresolverr_restricted}
RESTRICTED_SUBNET=${RESTRICTED_SUBNET:-10.89.60.0/24}
RESTRICTED_GATEWAY=${RESTRICTED_GATEWAY:-10.89.60.1}
DNS_UPLINK_NETWORK=${DNS_UPLINK_NETWORK:-flaresolverr_dns_uplink}
DNS_UPLINK_SUBNET=${DNS_UPLINK_SUBNET:-10.89.61.0/24}
DNS_UPLINK_GATEWAY=${DNS_UPLINK_GATEWAY:-10.89.61.1}
DNSDIST_IP=${DNSDIST_IP:-10.89.60.53}
DNSDIST_BIND_ADDRESS=${DNSDIST_BIND_ADDRESS:-${DNSDIST_IP}:53}
DNSDIST_ALLOW_FROM=${DNSDIST_ALLOW_FROM:-10.89.60.0/24}
ALLOWED_PRIVATE_CIDRS=${ALLOWED_PRIVATE_CIDRS:-192.168.50.0/24}
LOG_LEVEL=${LOG_LEVEL:-info}
LOG_FILE=${LOG_FILE:-/config/flaresolverr.log}
TZ=${TZ:-UTC}

install -D -m 0644 \
  "${SCRIPT_DIR}/systemd/flaresolverr-podman-networks.service" \
  "${SYSTEMD_DIR}/flaresolverr-podman-networks.service"
install -D -m 0644 \
  "${SCRIPT_DIR}/systemd/flaresolverr-podman-dnsdist.service" \
  "${SYSTEMD_DIR}/flaresolverr-podman-dnsdist.service"
install -D -m 0644 \
  "${SCRIPT_DIR}/systemd/flaresolverr-podman-restricted.service" \
  "${SYSTEMD_DIR}/flaresolverr-podman-restricted.service"
install -D -m 0644 \
  "${SCRIPT_DIR}/dnsdist/dnsdist.conf" \
  "${DNSDIST_CONFIG_PATH}"

install -d -m 0755 "${CONFIG_DIR}"
cat > "${ENV_FILE}" <<EOF
IMAGE=${IMAGE}
DNSDIST_IMAGE=${DNSDIST_IMAGE}
CONFIG_DIR=${CONFIG_DIR}
RESTRICTED_NETWORK=${RESTRICTED_NETWORK}
RESTRICTED_SUBNET=${RESTRICTED_SUBNET}
RESTRICTED_GATEWAY=${RESTRICTED_GATEWAY}
DNS_UPLINK_NETWORK=${DNS_UPLINK_NETWORK}
DNS_UPLINK_SUBNET=${DNS_UPLINK_SUBNET}
DNS_UPLINK_GATEWAY=${DNS_UPLINK_GATEWAY}
DNSDIST_IP=${DNSDIST_IP}
DNSDIST_BIND_ADDRESS=${DNSDIST_BIND_ADDRESS}
DNSDIST_ALLOW_FROM=${DNSDIST_ALLOW_FROM}
DNSDIST_CONFIG_PATH=${DNSDIST_CONFIG_PATH}
ALLOWED_PRIVATE_CIDRS="${ALLOWED_PRIVATE_CIDRS}"
LOG_LEVEL=${LOG_LEVEL}
LOG_FILE=${LOG_FILE}
TZ=${TZ}
EOF

systemctl daemon-reload
systemctl enable --now flaresolverr-podman-networks.service
systemctl enable --now flaresolverr-podman-dnsdist.service
systemctl enable --now flaresolverr-podman-restricted.service

echo "restricted Podman install complete."
echo "ENV_FILE=${ENV_FILE}"
echo
echo "Verify:"
echo "  systemctl status flaresolverr-podman-networks.service"
echo "  systemctl status flaresolverr-podman-dnsdist.service"
echo "  systemctl status flaresolverr-podman-restricted.service"

#!/usr/bin/env bash
set -euo pipefail

PUBLIC_DNSDIST_URL=${PUBLIC_DNSDIST_URL:-https://raw.githubusercontent.com/disposable/public-dns/main/txt/dnsdist.conf}
DNSDIST_BIND_ADDRESS=${DNSDIST_BIND_ADDRESS:-0.0.0.0:53}
DNSDIST_ALLOW_FROM=${DNSDIST_ALLOW_FROM:-10.89.60.0/24}
CONFIG_PATH=/etc/dnsdist/dnsdist.conf
TMP_PATH=/tmp/public-dnsdist.conf

mkdir -p /etc/dnsdist
curl -fsSL "${PUBLIC_DNSDIST_URL}" -o "${TMP_PATH}"

cat > "${CONFIG_PATH}" <<EOF2
setLocal('${DNSDIST_BIND_ADDRESS}')
setACL({'${DNSDIST_ALLOW_FROM}'})
EOF2
cat "${TMP_PATH}" >> "${CONFIG_PATH}"

dnsdist --check-config -C "${CONFIG_PATH}"
exec dnsdist --supervised --disable-syslog -C "${CONFIG_PATH}"

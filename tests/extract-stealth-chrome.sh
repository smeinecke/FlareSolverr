#!/usr/bin/env bash
# Extract the custom stealth Chromium from the Docker image for local non-headless use.
#
# After running this script, start FlareSolverr with:
#   HEADLESS=false uv run python src/flaresolverr/flaresolverr.py
#
# To run a specific test against it:
#   uv run python -m pytest tests/integration/test_api.py::TestFlareSolverr::test_v1_endpoint_request_get_ddos_guard_js -v -m integration -s

set -euo pipefail

IMAGE="ghcr.io/smeinecke/chromium-stealth:latest"
DEST="src/flaresolverr/chrome"

echo "==> Pulling $IMAGE ..."
docker pull "$IMAGE"

echo "==> Extracting binaries to $DEST ..."
rm -rf "$DEST"
mkdir -p "$DEST"

cid=$(docker create "$IMAGE")
docker cp "$cid:/opt/chromium/." "$DEST/"
docker rm "$cid" > /dev/null

chmod +x "$DEST/chrome" "$DEST/chromedriver" 2>/dev/null || true

echo "==> Creating /opt/chromium/.stealth-patched sentinel ..."
sudo mkdir -p /opt/chromium
sudo touch /opt/chromium/.stealth-patched

echo ""
echo "Done. Start FlareSolverr with:"
echo "  HEADLESS=false uv run python -m flaresolverr.flaresolverr"

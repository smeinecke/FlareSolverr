#!/usr/bin/env bash
set -euo pipefail

# Standalone build script for custom Chromium with FlareSolverr stealth patches.
# Usage: ./build.sh [CHROMIUM_VERSION]
# If no version is provided, the latest stable tag is fetched automatically.
#
# Note: The Dockerfile splits this into separate stages (source sync vs. build)
# for layer caching. This script is for local/CI use outside Docker.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHROMIUM_VERSION="${1:-}"

# --- resolve latest stable if not given ---
if [[ -z "$CHROMIUM_VERSION" ]]; then
    echo "Fetching latest stable Chromium version..."
    CHROMIUM_VERSION=$(curl -s 'https://chromiumdash.appspot.com/fetch_releases?channel=Stable' | python3 -c "
import sys, json
data = json.load(sys.stdin)
releases = [r for r in data if r.get('version')]
if not releases:
    print('134.0.6998.0')  # fallback
else:
    # Use tuple comparison to correctly order patch versions (e.g. 9 < 100)
    latest = sorted(releases, key=lambda r: tuple(map(int, r['version'].split('.'))), reverse=True)[0]
    print(latest['version'])
")
    echo "Latest stable: $CHROMIUM_VERSION"
fi

# depot_tools
if [[ ! -d /depot_tools ]]; then
    echo "Cloning depot_tools..."
    git clone --depth=1 https://chromium.googlesource.com/chromium/tools/depot_tools.git /depot_tools
fi
export PATH="/depot_tools:$PATH"

# --- fetch Chromium source ---
# For local development mount a persistent volume to avoid re-downloading:
#   docker run -v /your/host/chromium-cache:/chromium ...
CHROMIUM_ROOT="${CHROMIUM_ROOT:-/chromium}"
if [[ ! -d "$CHROMIUM_ROOT/src" ]]; then
    mkdir -p "$CHROMIUM_ROOT"
    cd "$CHROMIUM_ROOT"
    echo "Fetching Chromium source at $CHROMIUM_VERSION (no-history; ~8 GB instead of 60+ GB)..."
    # --no-history: shallow clone; only the working tree at HEAD is kept.
    fetch --nohooks --no-history chromium
    cd src
    git fetch origin "refs/tags/$CHROMIUM_VERSION:refs/tags/$CHROMIUM_VERSION" --no-tags --depth=1 || true
    git checkout "$CHROMIUM_VERSION" || git checkout "tags/$CHROMIUM_VERSION"
    # -D prunes stale dependencies; --no-history keeps the tree minimal.
    gclient sync --with_branch_refs --with_tags --no-history -D
    echo "Running hooks..."
    gclient runhooks
else
    cd "$CHROMIUM_ROOT/src"
fi

# --- apply patches ---
echo "Applying FlareSolverr patches..."
for patch in "$SCRIPT_DIR"/patches/*.patch; do
    if [[ -f "$patch" ]]; then
        echo "Applying $(basename "$patch") ..."
        git apply "$patch" || {
            echo "Failed to apply $(basename "$patch")"; exit 1;
        }
    fi
done

# --- gn gen ---
echo "Generating build files..."
gn gen out/Release --args="$(cat "$SCRIPT_DIR/gn-args.txt")"

# --- build ---
echo "Building chrome and chromedriver..."
ninja -C out/Release chrome chromedriver

# --- collect runtime artifacts ---
echo "Collecting runtime artifacts..."
mkdir -p /opt/chromium

cp out/Release/chrome /opt/chromium/chrome
cp out/Release/chromedriver /opt/chromium/chromedriver
cp out/Release/*.pak /opt/chromium/ 2>/dev/null || true
cp out/Release/icudtl.dat /opt/chromium/ 2>/dev/null || true
cp -r out/Release/locales /opt/chromium/ 2>/dev/null || true
cp -r out/Release/resources /opt/chromium/ 2>/dev/null || true

# Sentinel file checked by utils.py to detect the patched build.
touch /opt/chromium/.stealth-patched

echo "Build complete. Artifacts in /opt/chromium"

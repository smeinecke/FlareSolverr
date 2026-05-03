# Multi-stage Dockerfile for building patched Chromium.
# Usage:
#   docker build --target runtime -t ghcr.io/smeinecke/chromium-stealth:<version> .

# ---------------------------------------------------------------------------
# Stage 1: Build environment
# ---------------------------------------------------------------------------
FROM ubuntu:22.04 AS build-env

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl python3 python3-pip python3-venv python3-dev \
    build-essential ccache lld clang ninja-build pkg-config \
    libgl1-mesa-dev libgles2-mesa-dev \
    libx11-dev libxkbcommon-dev libwayland-dev \
    libnss3-dev libdbus-1-dev \
    libdrm-dev libgbm-dev \
    libasound2-dev libpulse-dev \
    libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3 libxi6 \
    libxrandr2 libxrender1 libxtst6 libxshmfence-dev \
    libgtk-3-dev libpango1.0-dev libatk1.0-dev libcairo2-dev \
    libgdk-pixbuf-2.0-dev libatspi2.0-dev \
    libjpeg-dev libpng-dev libwebp-dev libtiff-dev \
    libxml2-dev libxslt1-dev \
    libfontconfig1-dev \
    && rm -rf /var/lib/apt/lists/*

ENV CCACHE_DIR=/ccache
ENV CCACHE_MAXSIZE=10G
RUN mkdir -p /ccache

# ---------------------------------------------------------------------------
# Stage 2: Source sync only (no patches, no build — separate for caching)
# ---------------------------------------------------------------------------
FROM build-env AS source

WORKDIR /chromium

ARG CHROMIUM_VERSION
RUN if [ -z "$CHROMIUM_VERSION" ]; then \
        echo "CHROMIUM_VERSION build arg is required" && exit 1; \
    fi && \
    # Configure git to retry on rate limits (429 errors)
    git config --global http.lowSpeedLimit 0 && \
    git config --global http.lowSpeedTime 999999 && \
    git clone --depth=1 https://chromium.googlesource.com/chromium/tools/depot_tools.git /depot_tools && \
    export PATH="/depot_tools:$PATH" && \
    # --no-history avoids downloading the full 60+ GB git history; we only need the tree at one revision.
    # Retry fetch up to 5 times with 60s backoff on rate limits
    for i in 1 2 3 4 5; do \
        fetch --nohooks --no-history chromium && break || sleep 60; \
    done && \
    cd src && \
    git fetch origin "refs/tags/$CHROMIUM_VERSION:refs/tags/$CHROMIUM_VERSION" --no-tags --depth=1 || true && \
    git checkout "$CHROMIUM_VERSION" || git checkout "tags/$CHROMIUM_VERSION" && \
    # -D removes any stale dependencies to keep the tree minimal.
    # Retry gclient sync up to 5 times with 60s backoff on rate limits
    for i in 1 2 3 4 5; do \
        gclient sync --with_tags --no-history -D && break || sleep 60; \
    done && \
    gclient runhooks && \
    # Fix execute permissions on third-party binaries that may lack them
    find third_party -type f -name "node" -exec chmod +x {} \; 2>/dev/null || true && \
    find . -type f -name "*.bin" -exec chmod +x {} \; 2>/dev/null || true

# ---------------------------------------------------------------------------
# Stage 3: Apply patches and build (patch changes don't invalidate source)
# ---------------------------------------------------------------------------
FROM source AS patched-build

WORKDIR /chromium/src

# Build arguments for optimization
ARG NINJA_JOBS=0
ARG IS_COMPONENT_BUILD=false

COPY patches/ /chromium/patches/
COPY gn-args.txt /chromium/gn-args.txt

RUN python3 /chromium/patches/apply.py

# Generate build files with optional component build setting
RUN export PATH="/depot_tools:$PATH" && \
    GN_ARGS="$(cat /chromium/gn-args.txt)" && \
    if [ "$IS_COMPONENT_BUILD" = "true" ]; then \
      GN_ARGS="${GN_ARGS} is_component_build=true"; \
    fi && \
    gn gen out/Release --args="${GN_ARGS}"

# Build with optimal parallelism - use all CPUs if NINJA_JOBS not specified
RUN --mount=type=cache,target=/ccache \
    export PATH="/depot_tools:$PATH" && \
    export CCACHE_DIR=/ccache && \
    if [ "$NINJA_JOBS" = "0" ]; then \
      NINJA_JOBS=$(nproc); \
    fi && \
    echo "Building with $NINJA_JOBS parallel jobs" && \
    ninja -C out/Release -j${NINJA_JOBS} chrome chromedriver

RUN mkdir -p /opt/chromium && \
    cp out/Release/chrome /opt/chromium/chrome && \
    cp out/Release/chromedriver /opt/chromium/chromedriver && \
    cp out/Release/chrome_crashpad_handler /opt/chromium/ 2>/dev/null || true && \
    cp out/Release/*.so /opt/chromium/ 2>/dev/null || true && \
    cp out/Release/*.pak /opt/chromium/ 2>/dev/null || true && \
    cp out/Release/icudtl.dat /opt/chromium/ 2>/dev/null || true && \
    cp -r out/Release/locales /opt/chromium/ 2>/dev/null || true && \
    cp -r out/Release/resources /opt/chromium/ 2>/dev/null || true

# ---------------------------------------------------------------------------
# Stage 4: Runtime (minimal image)
# ---------------------------------------------------------------------------
FROM debian:trixie-slim AS runtime

ARG CHROMIUM_VERSION
LABEL org.opencontainers.image.title="Chromium Stealth Build" \
      org.opencontainers.image.version="${CHROMIUM_VERSION}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libdbus-1-3 libdrm2 libxkbcommon0 libgbm1 \
    libasound2 libfontconfig1 libfreetype6 libjpeg62-turbo libpng16-16 \
    libwebp7 libwebpdemux2 libxml2 libxslt1.1 \
    libx11-6 libxcomposite1 libxcursor1 libxdamage1 libxext6 \
    libxfixes3 libxi6 libxrandr2 libxrender1 libxtst6 \
    libpango-1.0-0 libcairo2 libatk1.0-0 libatk-bridge2.0-0 libgdk-pixbuf-2.0-0 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=patched-build /opt/chromium/ /opt/chromium/

# Sentinel file: utils.py checks for this to detect the patched build.
RUN touch /opt/chromium/.stealth-patched

RUN apt-get update && apt-get install -y --no-install-recommends binutils \
    && echo "=== ldd chrome ===" && ldd /opt/chromium/chrome \
    && echo "=== ldd chromedriver ===" && ldd /opt/chromium/chromedriver \
    && apt-get remove -y binutils && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN /opt/chromium/chrome --version && /opt/chromium/chromedriver --version

CMD ["/opt/chromium/chrome", "--version"]

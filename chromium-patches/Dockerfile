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
    libxshmfence-dev \
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
    git clone --depth=1 https://chromium.googlesource.com/chromium/tools/depot_tools.git /depot_tools && \
    export PATH="/depot_tools:$PATH" && \
    # --no-history avoids downloading the full 60+ GB git history; we only need the tree at one revision.
    fetch --nohooks --no-history chromium && \
    cd src && \
    git fetch origin "refs/tags/$CHROMIUM_VERSION:refs/tags/$CHROMIUM_VERSION" --no-tags --depth=1 || true && \
    git checkout "$CHROMIUM_VERSION" || git checkout "tags/$CHROMIUM_VERSION" && \
    # -D removes any stale dependencies to keep the tree minimal.
    gclient sync --with_tags --no-history -D && \
    gclient runhooks

# ---------------------------------------------------------------------------
# Stage 3: Apply patches and build (patch changes don't invalidate source)
# ---------------------------------------------------------------------------
FROM source AS patched-build

WORKDIR /chromium/src

COPY patches/ /chromium/patches/
COPY gn-args.txt /chromium/gn-args.txt

RUN python3 /chromium/patches/apply.py

RUN export PATH="/depot_tools:$PATH" && \
    gn gen out/Release --args="$(cat /chromium/gn-args.txt)"

RUN --mount=type=cache,target=/ccache \
    export PATH="/depot_tools:$PATH" && \
    export CCACHE_DIR=/ccache && \
    ninja -C out/Release chrome chromedriver

RUN mkdir -p /opt/chromium && \
    cp out/Release/chrome /opt/chromium/chrome && \
    cp out/Release/chromedriver /opt/chromium/chromedriver && \
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
    && rm -rf /var/lib/apt/lists/*

COPY --from=patched-build /opt/chromium/ /opt/chromium/

# Sentinel file: utils.py checks for this to detect the patched build.
RUN touch /opt/chromium/.stealth-patched

RUN /opt/chromium/chrome --version && /opt/chromium/chromedriver --version

CMD ["/opt/chromium/chrome", "--version"]

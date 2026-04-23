FROM python:3.13-slim-trixie AS dummy-packages

# Keep the current workaround until all target arches are validated without it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends equivs \
    && equivs-control libgl1-mesa-dri \
    && printf 'Section: misc\nPriority: optional\nStandards-Version: 3.9.2\nPackage: libgl1-mesa-dri\nVersion: 99.0.0\nDescription: Dummy package for libgl1-mesa-dri\n' >> libgl1-mesa-dri \
    && equivs-build libgl1-mesa-dri \
    && mv libgl1-mesa-dri_*.deb /libgl1-mesa-dri.deb \
    && equivs-control adwaita-icon-theme \
    && printf 'Section: misc\nPriority: optional\nStandards-Version: 3.9.2\nPackage: adwaita-icon-theme\nVersion: 99.0.0\nDescription: Dummy package for adwaita-icon-theme\n' >> adwaita-icon-theme \
    && equivs-build adwaita-icon-theme \
    && mv adwaita-icon-theme_*.deb /adwaita-icon-theme.deb \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.13-slim-trixie AS python-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv for the correct target architecture (pinned version)
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && case "${TARGETARCH}" in \
        amd64) UV_ARCH="x86_64-unknown-linux-gnu" ;; \
        arm64) UV_ARCH="aarch64-unknown-linux-gnu" ;; \
        arm) UV_ARCH="armv7-unknown-linux-gnueabihf" ;; \
        386) UV_ARCH="i686-unknown-linux-gnu" ;; \
        *) UV_ARCH="x86_64-unknown-linux-gnu" ;; \
    esac \
    && curl -sL "https://github.com/astral-sh/uv/releases/download/0.10.8/uv-${UV_ARCH}.tar.gz" | tar xz -C /usr/local/bin --strip-components=1 \
    && chmod +x /usr/local/bin/uv /usr/local/bin/uvx

WORKDIR /app

# Preserve repo layout so the editable install still points at /app/src.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Create the virtualenv and install locked, non-dev dependencies.
RUN uv sync --frozen --no-dev \
    && rm -rf /root/.cache /tmp/*

FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/app \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src

WORKDIR /app

COPY --from=dummy-packages /libgl1-mesa-dri.deb /adwaita-icon-theme.deb /

RUN dpkg -i /libgl1-mesa-dri.deb /adwaita-icon-theme.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        xvfb \
        dumb-init \
        xauth \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /libgl1-mesa-dri.deb /adwaita-icon-theme.deb \
    && rm -f /usr/lib/*-linux-gnu/libmfxhw* \
    && rm -f /usr/lib/*-linux-gnu/mfx/* \
    && useradd --home-dir /app --shell /bin/sh flaresolverr \
    && mkdir -p /config "/app/.config/chromium/Crash Reports/pending" \
    && cp /usr/bin/chromedriver /app/chromedriver \
    && chown -R flaresolverr:flaresolverr /config /app

VOLUME /config

COPY --from=python-deps --chown=flaresolverr:flaresolverr /app/.venv /app/.venv
COPY --chown=flaresolverr:flaresolverr pyproject.toml /app/pyproject.toml
COPY --chown=flaresolverr:flaresolverr src /app/src

USER flaresolverr

EXPOSE 8191
EXPOSE 8192

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["python", "-u", "/app/src/flaresolverr/flaresolverr.py"]

# Local build
# docker build -t ngosang/flaresolverr:3.4.6 .
# docker run -p 8191:8191 ngosang/flaresolverr:3.4.6

# Multi-arch build
# docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
# docker buildx create --use
# docker buildx build -t ngosang/flaresolverr:3.4.6 --platform linux/386,linux/amd64,linux/arm/v7,linux/arm64/v8 .
#   add --push to publish in DockerHub

# Test multi-arch build
# docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
# docker buildx create --use
# docker buildx build -t ngosang/flaresolverr:3.4.6 --platform linux/arm/v7 --load .
# docker run -p 8191:8191 --platform linux/arm/v7 ngosang/flaresolverr:3.4.6

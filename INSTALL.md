## Installation

### Docker

It is recommended to install using a Docker container because the project depends on an external browser that is
already included within the image.

Docker images are available in:

- GitHub Container Registry => `ghcr.io/smeinecke/flaresolverr:latest`
- GitHub Packages => <https://github.com/smeinecke/FlareSolverr/pkgs/container/flaresolverr>

Supported architectures are:

| Architecture | Tag          | Notes                                           |
| ------------ | ------------ | ----------------------------------------------- |
| x86          | linux/386    | Uses stock Debian Chromium (no stealth patches) |
| x86-64       | linux/amd64  | Includes custom stealth Chromium                |
| ARM32        | linux/arm/v7 | Uses stock Debian Chromium (no stealth patches) |
| ARM64        | linux/arm64  | Uses stock Debian Chromium (no stealth patches) |

> **Note:** The custom stealth-patched Chromium build is only available for **amd64**. On other architectures FlareSolverr falls back to the stock Debian `chromium` package; stealth mode still works but with reduced hardening (CDP-based JS patches only, no C++ binary patches).

We provide a `docker-compose.yml` configuration file. Clone this repository and execute
`docker-compose up -d` _(Compose V1)_ or `docker compose up -d` _(Compose V2)_ to start
the container.

If you prefer the `docker cli` execute the following command:

**Bash**

```bash
docker run -d \
  --name=flaresolverr \
  -p 8191:8191 \
  -e LOG_LEVEL=info \
  --restart unless-stopped \
  ghcr.io/smeinecke/flaresolverr:latest
```

**Command Prompt or Powershell**

```cmd
docker run -d --name=flaresolverr -p 8191:8191 -e LOG_LEVEL=info --restart unless-stopped ghcr.io/smeinecke/flaresolverr:latest
```

If your host OS is Debian, make sure `libseccomp2` version is 2.5.x. You can check the version with `sudo apt-cache policy libseccomp2`
and update the package with `sudo apt install libseccomp2=2.5.1-1~bpo10+1` or `sudo apt install libseccomp2=2.5.1-1+deb11u1`.
Remember to restart the Docker daemon and the container after the update.

### Podman

If you prefer Podman, see [PODMAN.md](./PODMAN.md) for two ready-to-run examples:

- a standard Podman deployment
- a restricted deployment with separate networks and a `dnsdist` DNS sidecar so FlareSolverr itself has no public egress

### HAProxy / Clustering

If you want to run multiple FlareSolverr instances behind a load balancer with session-aware routing, see [HAPROXY.md](./HAPROXY.md). It covers how to use the `X-FlareSolverr-Session` header with HAProxy to ensure requests for the same session always reach the backend that owns it.

### Precompiled binaries

> **Warning**
> Precompiled binaries are only available for x64 architecture. For other architectures see Docker images.

This is the recommended way for Windows users.

- Download the [FlareSolverr executable](https://github.com/smeinecke/FlareSolverr/releases) from the release's page. It is available for Windows x64 and Linux x64.
- Execute FlareSolverr binary. In the environment variables section you can find how to change the configuration.

### From source code

> **Warning**
> Installing from source code only works for x64 architecture. For other architectures see Docker images.

- Install [Python 3.13](https://www.python.org/downloads/).
- Install [Chrome](https://www.google.com/intl/en_us/chrome/) (all OS) or [Chromium](https://www.chromium.org/getting-involved/download-chromium/) (just Linux, it doesn't work in Windows) web browser.
- (Only in Linux) Install [Xvfb](https://en.wikipedia.org/wiki/Xvfb) package.
- (Only in macOS) Install [XQuartz](https://www.xquartz.org/) package.
- Install [uv](https://github.com/astral-sh/uv) (a fast Python package installer).
- Clone this repository and open a shell in that path.
- Run `uv sync` command to install FlareSolverr dependencies.
- Run `uv run python src/flaresolverr.py` command to start FlareSolverr.

### From source code (FreeBSD/TrueNAS CORE)

- Run `pkg install chromium python313 py313-pip xorg-vfbserver` command to install the required dependencies.
- Install [uv](https://github.com/astral-sh/uv) (a fast Python package installer).
- Clone this repository and open a shell in that path.
- Run `uv sync` command to install FlareSolverr dependencies.
- Run `uv run python src/flaresolverr.py` command to start FlareSolverr.

### Systemd service

We provide an example Systemd unit file `flaresolverr.service` as reference. You have to modify the file to suit your needs: paths, user and environment variables.

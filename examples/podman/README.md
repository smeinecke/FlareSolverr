# Podman Examples

This directory contains ready-to-run Podman examples for FlareSolverr.

The examples are centered around systemd-managed services so the containers start automatically on boot.

## Standard deployment

Runs FlareSolverr normally with standard outbound access.

Files:

- `standard/systemd/flaresolverr-podman.service`
- `standard/run.sh`

Quick start:

```bash
sudo mkdir -p /srv/flaresolverr/config
sudo cp examples/podman/standard/systemd/flaresolverr-podman.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flaresolverr-podman.service
curl http://127.0.0.1:8191/health
```

## Restricted deployment

Runs FlareSolverr on a restricted network with a separate `dnsdist` sidecar.
FlareSolverr uses the sidecar for DNS and can be limited to explicitly allowed private routes only.

Files:

- `restricted/systemd/flaresolverr-podman-networks.service`
- `restricted/systemd/flaresolverr-podman-dnsdist.service`
- `restricted/systemd/flaresolverr-podman-restricted.service`
- `restricted/01-create-networks.sh`
- `restricted/10-build-dnsdist.sh`
- `restricted/20-run-dnsdist.sh`
- `restricted/30-run-flaresolverr.sh`
- `restricted/40-allow-private-routes.sh`
- `restricted/dnsdist/Containerfile`
- `restricted/dnsdist/fetch-and-run.sh`

Quick start:

```bash
sudo cp examples/podman/restricted/systemd/flaresolverr-podman-networks.service /etc/systemd/system/
sudo cp examples/podman/restricted/systemd/flaresolverr-podman-dnsdist.service /etc/systemd/system/
sudo cp examples/podman/restricted/systemd/flaresolverr-podman-restricted.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flaresolverr-podman-networks.service
sudo ./examples/podman/restricted/10-build-dnsdist.sh
sudo mkdir -p /srv/flaresolverr/config
sudo systemctl enable --now flaresolverr-podman-dnsdist.service
sudo systemctl enable --now flaresolverr-podman-restricted.service
```

Before enabling `flaresolverr-podman-restricted.service`, edit the copied unit in `/etc/systemd/system/` and set `ALLOWED_PRIVATE_CIDRS` to the private CIDRs FlareSolverr is allowed to reach.

Verification:

```bash
sudo systemctl status flaresolverr-podman-networks.service
sudo systemctl status flaresolverr-podman-dnsdist.service
sudo systemctl status flaresolverr-podman-restricted.service
FS_PID=$(sudo podman inspect -f '{{.State.Pid}}' flaresolverr)
sudo nsenter -t "$FS_PID" -n ip route
sudo podman exec flaresolverr cat /etc/resolv.conf
```

Notes:

- The restricted example fetches upstream resolver backends from `https://raw.githubusercontent.com/disposable/public-dns/main/txt/dnsdist.conf`.
- That URL tracks `main` and can change over time.
- `PODMAN.md` contains the full explanation, security model, and verification steps.

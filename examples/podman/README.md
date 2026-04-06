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
- `restricted/systemd/podman-restricted.env.example`
- `restricted/install.sh`
- `restricted/dnsdist/dnsdist.conf`

Quick start:

```bash
sudo ALLOWED_PRIVATE_CIDRS="192.168.50.0/24 192.168.60.0/24" ./examples/podman/restricted/install.sh
```

`install.sh` writes `/etc/flaresolverr/podman-restricted.env`.
Update that file (or rerun `install.sh` with different variables) whenever your settings change.
You can use `restricted/systemd/podman-restricted.env.example` as a reference for all available keys.

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

- The restricted example uses `docker.io/powerdns/dnsdist-19:latest`.
- The resolver list is pinned in `restricted/dnsdist/dnsdist.conf`.
- `PODMAN.md` contains the full explanation, security model, and verification steps.

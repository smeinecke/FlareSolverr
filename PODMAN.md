# Running FlareSolverr with Podman

This repository ships two Podman example layouts:

- standard: FlareSolverr with normal outbound access
- restricted: FlareSolverr on a private-only network with a separate `dnsdist` sidecar for DNS

The examples are centered around systemd-managed services so the containers start automatically on boot.

## Image facts

The published image is:

```bash
ghcr.io/smeinecke/flaresolverr:latest
```

The image:

- listens on `8191/tcp` for the API
- optionally listens on `8192/tcp` when `PROMETHEUS_ENABLED=true`
- stores persistent data in `/config`
- runs as the non-root user `flaresolverr`

## Startup behavior

FlareSolverr performs a startup browser validation, but it does not fetch a fixed external test URL.
The current startup check is a local browser launch and user-agent retrieval.

That matters for restricted deployments: you do not need a special egress exception for startup.

## Recommendation

For strict outbound control, prefer a rootful Podman deployment with dedicated bridge networks.
That keeps the network boundaries easy to reason about and makes systemd-managed startup straightforward.

## Standard deployment

Files:

- [flaresolverr-podman.service](/home/stefan/github/FlareSolverr/examples/podman/standard/systemd/flaresolverr-podman.service)
- [run.sh](/home/stefan/github/FlareSolverr/examples/podman/standard/run.sh)

Install:

```bash
sudo mkdir -p /srv/flaresolverr/config
sudo cp examples/podman/standard/systemd/flaresolverr-podman.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flaresolverr-podman.service
```

Verify:

```bash
curl http://127.0.0.1:8191/
curl http://127.0.0.1:8191/health
sudo systemctl status flaresolverr-podman.service
sudo podman logs flaresolverr
```

Notes:

- The API is bound to `127.0.0.1:8191` by default.
- On SELinux hosts, the `:Z` volume suffix matters.
- The `run.sh` helper is useful for manual testing, but the systemd unit is the recommended long-running setup.

## Restricted deployment

Files:

- [flaresolverr-podman-networks.service](/home/stefan/github/FlareSolverr/examples/podman/restricted/systemd/flaresolverr-podman-networks.service)
- [flaresolverr-podman-dnsdist.service](/home/stefan/github/FlareSolverr/examples/podman/restricted/systemd/flaresolverr-podman-dnsdist.service)
- [flaresolverr-podman-restricted.service](/home/stefan/github/FlareSolverr/examples/podman/restricted/systemd/flaresolverr-podman-restricted.service)
- [podman-restricted.env.example](/home/stefan/github/FlareSolverr/examples/podman/restricted/systemd/podman-restricted.env.example)
- [install.sh](/home/stefan/github/FlareSolverr/examples/podman/restricted/install.sh)
- [dnsdist.conf](/home/stefan/github/FlareSolverr/examples/podman/restricted/dnsdist/dnsdist.conf)

Security model:

- FlareSolverr is dual-homed: primary interface on `flaresolverr_restricted`, secondary interface on `flaresolverr_dns_uplink` for DNS access.
- `dnsdist` is single-homed on `flaresolverr_dns_uplink` with upstream public resolvers.
- FlareSolverr uses the `dnsdist` listener on the uplink network as DNS.
- FlareSolverr's default route is removed after start, and only the private CIDRs in `ALLOWED_PRIVATE_CIDRS` are added back.

Defaults used by the example:

- restricted network: `10.89.60.0/24`
- restricted gateway: `10.89.60.1`
- uplink network: `10.89.61.0/24`
- uplink gateway: `10.89.61.1`
- dnsdist IP on uplink network: `10.89.61.2`
- dnsdist image: `docker.io/powerdns/dnsdist-19:latest`
- dnsdist resolver source: `examples/podman/restricted/dnsdist/dnsdist.conf`

Install:

```bash
sudo ALLOWED_PRIVATE_CIDRS="192.168.50.0/24 192.168.60.0/24" ./examples/podman/restricted/install.sh
```

`install.sh` writes `/etc/flaresolverr/podman-restricted.env`.
Edit that file (or rerun `install.sh` with different variables) for your environment.
Use `examples/podman/restricted/systemd/podman-restricted.env.example` as the full key reference.
If needed, also adjust `RESTRICTED_GATEWAY`, `DNSDIST_IP`, or `DNSDIST_CONFIG_PATH`.

Notes:

- `dnsdist` uses the pinned resolver list in `examples/podman/restricted/dnsdist/dnsdist.conf`.
- This separate-network design is intentional: it keeps public resolver access out of the FlareSolverr namespace.

## Verification

Inspect service state and network attachments:

```bash
sudo systemctl status flaresolverr-podman-networks.service
sudo systemctl status flaresolverr-podman-dnsdist.service
sudo systemctl status flaresolverr-podman-restricted.service
sudo podman inspect flaresolverr
sudo podman inspect flaresolverr-dnsdist
sudo podman network inspect flaresolverr_restricted
sudo podman network inspect flaresolverr_dns_uplink
```

Confirm FlareSolverr routes:

```bash
FS_PID=$(sudo podman inspect -f '{{.State.Pid}}' flaresolverr)
sudo nsenter -t "$FS_PID" -n ip route
```

Expected result:

- the default route is gone
- only the restricted subnet and allowed private routes remain

Check DNS wiring:

```bash
sudo podman exec flaresolverr cat /etc/resolv.conf
```

Expected result:

- `/etc/resolv.conf` points at `10.89.61.2`

Check allowed vs blocked destinations:

```bash
sudo podman exec flaresolverr python - <<'PY'
import socket
for host, port in [("192.168.50.10", 3128), ("1.1.1.1", 80)]:
    s = socket.socket()
    s.settimeout(3)
    try:
        s.connect((host, port))
        print(f"{host}:{port} -> allowed")
    except Exception as exc:
        print(f"{host}:{port} -> blocked ({exc})")
    finally:
        s.close()
PY
```

## Defense in depth

If leakage prevention matters, add host firewall rules as a second layer.
A good pattern is:

- allow the restricted subnet to reach the `dnsdist` sidecar on TCP/UDP `53`
- allow the restricted subnet to reach only the private proxy IPs you want
- reject everything else from the restricted subnet

Example nftables fragment:

```nft
#!/usr/sbin/nft -f

define fs_net = 10.89.60.0/24
define dns_uplink_net = 10.89.61.0/24
define dns_sidecar = 10.89.61.2
define proxy_hosts = { 192.168.50.10, 192.168.50.11 }

table inet flaresolverr {
  chain forward {
    type filter hook forward priority filter; policy accept;

    # FlareSolverr on restricted network -> DNS sidecar on uplink network
    ip saddr $fs_net udp dport 53 ip daddr $dns_sidecar accept
    ip saddr $fs_net tcp dport 53 ip daddr $dns_sidecar accept
    # FlareSolverr -> proxy hosts
    ip saddr $fs_net ip daddr $proxy_hosts accept
    # Block all other egress from restricted network
    ip saddr $fs_net counter reject with icmpx type admin-prohibited

    # DNS sidecar on uplink network -> public resolvers only
    ip saddr $dns_uplink_net ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 } udp dport 53 counter reject with icmpx type admin-prohibited
    ip saddr $dns_uplink_net ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 } tcp dport 53 counter reject with icmpx type admin-prohibited
    ip saddr $dns_uplink_net udp dport 53 accept
    ip saddr $dns_uplink_net tcp dport 53 accept
    ip saddr $dns_uplink_net counter reject with icmpx type admin-prohibited
  }
}
```

Load it with:

```bash
sudo nft -f /etc/nftables.d/flaresolverr.nft
sudo nft list ruleset
```

## Useful settings

Common environment variables:

- `LOG_LEVEL=info` or `debug`
- `LOG_FILE=/config/flaresolverr.log`
- `TZ=Europe/Berlin` or your timezone
- `HEADLESS=true`
- `DISABLE_MEDIA=true`
- `PROXY_URL=http://192.168.1.10:3128`
- `PROXY_USERNAME` and `PROXY_PASSWORD`
- `PROMETHEUS_ENABLED=true` and `PROMETHEUS_PORT=8192`
- `XVFB_WIDTH=1280`, `XVFB_HEIGHT=720`, and `XVFB_COLORDEPTH=24` (Xvfb virtual display settings)

## Rootless note

Rootless Podman is fine for convenience, but it is not the best fit for strict per-container egress control.
For the restricted design, use the rootful dedicated-network setup above.

## Updating

Standard service:

```bash
sudo podman pull ghcr.io/smeinecke/flaresolverr:latest
sudo systemctl restart flaresolverr-podman.service
```

Restricted service:

```bash
sudo podman pull ghcr.io/smeinecke/flaresolverr:latest
sudo systemctl restart flaresolverr-podman-dnsdist.service
sudo systemctl restart flaresolverr-podman-restricted.service
```

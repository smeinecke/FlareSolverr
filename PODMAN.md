# Running FlareSolverr with Podman

This document shows how to run FlareSolverr with Podman and how to harden the container so it can only open outbound connections to LAN addresses. The LAN-only setup is useful when FlareSolverr must talk only to local proxy servers and you want to reduce the chance of direct Internet traffic leaking out of the container.

## Image and runtime facts

The current container image in this repository:

- listens on `8191/tcp` for the API
- optionally listens on `8192/tcp` when `PROMETHEUS_ENABLED=true`
- stores persistent data in `/config`
- runs as the non-root user `flaresolverr`
- performs a startup browser smoke test by launching Chromium and reading the user agent

The published image is:

```bash
ghcr.io/smeinecke/flaresolverr:latest
```

## Startup test behavior

In the current codebase, FlareSolverr still performs a startup browser validation, but it does not use `TEST_URL`.

- there is currently no `TEST_URL` environment variable in use
- setting `TEST_URL` to an empty value does not disable anything
- the startup check is a local browser launch and user-agent retrieval, not an outbound HTTP request to a fixed test site

That matters for locked-down Podman deployments: the LAN-only egress rules in this document do not need a special exception for a startup URL fetch.

## Recommendation for secure deployments

For normal Podman usage, both rootless and rootful containers work.

For strict outbound traffic control, prefer a **rootful** Podman deployment with a dedicated bridge network. That gives you two useful controls:

1. you can create a network with **no default route**
2. you can add **only the LAN routes you want**

That is much easier to reason about than rootless user-mode networking when leakage prevention matters.

## Quick start

Create a persistent config directory:

```bash
sudo mkdir -p /srv/flaresolverr/config
sudo chown -R root:root /srv/flaresolverr
```

Run FlareSolverr with Podman:

```bash
sudo podman run -d \
  --name flaresolverr \
  --replace \
  -p 127.0.0.1:8191:8191 \
  -v /srv/flaresolverr/config:/config:Z \
  -e LOG_LEVEL=info \
  -e LOG_FILE=/config/flaresolverr.log \
  -e TZ=UTC \
  --restart unless-stopped \
  ghcr.io/smeinecke/flaresolverr:latest
```

Notes:

- `127.0.0.1:8191:8191` keeps the API bound to localhost on the host. That is usually safer than exposing it on every interface.
- On SELinux hosts, the `:Z` suffix is important so the container can write to `/config`.
- If you need metrics, also publish `8192` and set `PROMETHEUS_ENABLED=true`.

Check that the service is up:

```bash
curl http://127.0.0.1:8191/
curl http://127.0.0.1:8191/health
sudo podman logs flaresolverr
```

## Managing it with systemd

Podman works well with systemd. A Quadlet unit is the cleanest long-term setup.

Create `/etc/containers/systemd/flaresolverr.container`:

```ini
[Unit]
Description=FlareSolverr
After=network-online.target
Wants=network-online.target

[Container]
Image=ghcr.io/smeinecke/flaresolverr:latest
ContainerName=flaresolverr
PublishPort=127.0.0.1:8191:8191
Volume=/srv/flaresolverr/config:/config:Z
Environment=LOG_LEVEL=info
Environment=LOG_FILE=/config/flaresolverr.log
Environment=TZ=UTC

[Service]
Restart=always
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now flaresolverr.service
sudo systemctl status flaresolverr.service
```

Useful commands later:

```bash
sudo systemctl restart flaresolverr
sudo journalctl -u flaresolverr -f
sudo podman ps
```

## Environment variables you are likely to use

Common settings:

- `LOG_LEVEL=info` or `debug`
- `LOG_FILE=/config/flaresolverr.log`
- `TZ=Europe/Berlin` or your timezone
- `HEADLESS=true`
- `DISABLE_MEDIA=true` if you want to reduce bandwidth usage
- `PROXY_URL=http://192.168.1.10:3128` if every request should use the same proxy by default
- `PROXY_USERNAME` and `PROXY_PASSWORD` if your proxy requires authentication
- `PROMETHEUS_ENABLED=true` and `PROMETHEUS_PORT=8192` if you want metrics

## LAN-only egress: recommended design

If FlareSolverr must only connect to proxy servers on your LAN, the safest Podman design is:

- create a dedicated Podman bridge network for FlareSolverr
- give that network **no default route**
- add routes only for the LAN subnets or, better, only for the proxy subnet(s)
- keep the API bound to `127.0.0.1` unless other hosts truly need access
- do not enable IPv6 unless you also plan and filter IPv6 explicitly

### Why this works

A container normally gets a default route, so any destination can be attempted and host-side NAT decides where it goes.

With `no_default_route=1`, the container has no catch-all route. If you then add only the LAN routes you need, there is simply no route for public Internet addresses.

That is a strong first layer against leakage.

## Example: allow only one LAN subnet

This example allows FlareSolverr to reach only `192.168.50.0/24` through the host. Replace the subnets with your own LAN and proxy network.

Create a dedicated network:

```bash
sudo podman network create \
  --subnet 10.89.50.0/24 \
  --gateway 10.89.50.1 \
  --opt no_default_route=1 \
  --route 192.168.50.0/24,10.89.50.1 \
  flaresolverr_lanonly
```

Attach FlareSolverr to that network:

```bash
sudo podman run -d \
  --name flaresolverr \
  --replace \
  --network flaresolverr_lanonly \
  -p 127.0.0.1:8191:8191 \
  -v /srv/flaresolverr/config:/config:Z \
  -e LOG_LEVEL=info \
  -e LOG_FILE=/config/flaresolverr.log \
  -e TZ=UTC \
  --restart unless-stopped \
  ghcr.io/smeinecke/flaresolverr:latest
```

If your proxies live on several private subnets, add one `--route` per subnet when creating the network, for example:

```bash
sudo podman network create \
  --subnet 10.89.50.0/24 \
  --gateway 10.89.50.1 \
  --opt no_default_route=1 \
  --route 192.168.50.0/24,10.89.50.1 \
  --route 10.20.30.0/24,10.89.50.1 \
  --route 172.16.40.0/24,10.89.50.1 \
  flaresolverr_lanonly
```

### Better than allowing all RFC1918 ranges

If you know the exact proxy subnet, allow only that subnet.

This is better than allowing all of:

- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`

The smaller the allowed destination space is, the less room there is for accidental leakage.

## Using a fixed proxy with LAN-only egress

If FlareSolverr should always use one local proxy, set it directly on the container:

```bash
sudo podman run -d \
  --name flaresolverr \
  --replace \
  --network flaresolverr_lanonly \
  -p 127.0.0.1:8191:8191 \
  -v /srv/flaresolverr/config:/config:Z \
  -e LOG_LEVEL=info \
  -e LOG_FILE=/config/flaresolverr.log \
  -e TZ=UTC \
  -e PROXY_URL=http://192.168.50.10:3128 \
  --restart unless-stopped \
  ghcr.io/smeinecke/flaresolverr:latest
```

If you need per-request proxies instead, leave `PROXY_URL` unset and pass the `proxy` field in the API request. The LAN-only network still prevents direct connections outside the allowed LAN routes.

## DNS and leakage considerations

The safest option is to configure proxies by **IP address**, not by hostname. That avoids DNS becoming an extra outbound path.

If you must use a hostname for the proxy:

- point the container at a DNS server on your LAN
- allow routing only to that DNS server's subnet or address
- add host firewall rules so DNS can only go to the intended resolver

Example with an explicit DNS server on the LAN:

```bash
sudo podman run -d \
  --name flaresolverr \
  --replace \
  --network flaresolverr_lanonly \
  --dns 192.168.50.1 \
  -p 127.0.0.1:8191:8191 \
  -v /srv/flaresolverr/config:/config:Z \
  -e PROXY_URL=http://proxy.lan:3128 \
  --restart unless-stopped \
  ghcr.io/smeinecke/flaresolverr:latest
```

## Defense in depth: add host firewall rules too

Routing-only controls are already useful, but if leakage prevention is important, add host firewall rules as a second layer.

A good pattern is:

- allow the container subnet to talk only to the exact proxy IPs you want
- optionally allow DNS only to one LAN resolver
- reject everything else from the container subnet

### nftables example

This example assumes:

- Podman network subnet: `10.89.50.0/24`
- LAN DNS server: `192.168.50.1`
- allowed proxies: `192.168.50.10` and `192.168.50.11`

Create `/etc/nftables.d/flaresolverr.nft`:

```nft
#!/usr/sbin/nft -f

define fs_net = 10.89.50.0/24
define lan_dns = 192.168.50.1
define proxy_hosts = { 192.168.50.10, 192.168.50.11 }

table inet flaresolverr {
  chain forward {
    type filter hook forward priority filter; policy accept;

    ip saddr $fs_net udp dport 53 ip daddr $lan_dns accept
    ip saddr $fs_net tcp dport 53 ip daddr $lan_dns accept
    ip saddr $fs_net ip daddr $proxy_hosts accept

    ip saddr $fs_net counter reject with icmpx type admin-prohibited
  }
}
```

Load it:

```bash
sudo nft -f /etc/nftables.d/flaresolverr.nft
sudo nft list ruleset
```

If your distro uses `/etc/nftables.conf`, include the file there so it survives reboot.

### Why the firewall rule still matters

The `no_default_route` setup prevents normal routing to the public Internet.

The host firewall adds a second guarantee: even if the network definition changes later, traffic from the FlareSolverr subnet can still be restricted to your proxy IPs and LAN DNS only.

## Quadlet with the LAN-only network

Create the dedicated network once:

```bash
sudo podman network create \
  --subnet 10.89.50.0/24 \
  --gateway 10.89.50.1 \
  --opt no_default_route=1 \
  --route 192.168.50.0/24,10.89.50.1 \
  flaresolverr_lanonly
```

Then point the Quadlet unit at that pre-created network:

```ini
[Unit]
Description=FlareSolverr
After=network-online.target
Wants=network-online.target

[Container]
Image=ghcr.io/smeinecke/flaresolverr:latest
ContainerName=flaresolverr
Network=flaresolverr_lanonly
PublishPort=127.0.0.1:8191:8191
Volume=/srv/flaresolverr/config:/config:Z
Environment=LOG_LEVEL=info
Environment=LOG_FILE=/config/flaresolverr.log
Environment=TZ=UTC
Environment=PROXY_URL=http://192.168.50.10:3128

[Service]
Restart=always
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

If you prefer, you can also manage the network itself with a separate Quadlet `.network` unit, but pre-creating the network manually is often simpler when you need custom route planning.

## Verifying that leakage is blocked

Confirm the container is attached to the expected network:

```bash
sudo podman inspect flaresolverr
sudo podman network inspect flaresolverr_lanonly
```

Test an allowed destination and a disallowed one from inside the container:

```bash
sudo podman exec flaresolverr python - <<'PY'
import socket

tests = [
    ("192.168.50.10", 3128),
    ("1.1.1.1", 80),
]

for host, port in tests:
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

Expected result:

- the proxy IP on your LAN should connect successfully
- a public IP such as `1.1.1.1` should fail

If you added the nftables rule, also confirm it is loaded:

```bash
sudo nft list ruleset | sed -n '/table inet flaresolverr/,$p'
```

## Rootless Podman note

A rootless container is fine for convenience, but it is not the best choice when your main requirement is strict per-container egress control.

If you only want a simple rootless deployment, this works:

```bash
podman run -d \
  --name flaresolverr \
  --replace \
  -p 127.0.0.1:8191:8191 \
  -v "$HOME/.local/share/flaresolverr/config:/config:Z" \
  -e LOG_LEVEL=info \
  --restart unless-stopped \
  ghcr.io/smeinecke/flaresolverr:latest
```

For leakage prevention, use the rootful dedicated-network design above instead.

## Operational tips

- Do not use `--network host` if you care about containment.
- Do not publish the API on `0.0.0.0` unless another machine really needs it.
- Do not enable IPv6 unless you also intentionally route and filter IPv6 destinations.
- Prefer proxy IP addresses over proxy hostnames.
- Prefer allowing specific proxy IPs in nftables instead of entire LAN ranges.
- Keep `/config` persistent so logs and browser state survive restarts.

## Updating the container

Pull the new image and recreate the container:

```bash
sudo podman pull ghcr.io/smeinecke/flaresolverr:latest
sudo podman rm -f flaresolverr
```

Then run the same `podman run` command again, or restart the systemd-managed service.

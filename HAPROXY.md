# Running FlareSolverr in a Cluster with HAProxy

FlareSolverr stores browser sessions in local memory. When running multiple instances behind a load balancer, requests for the same session must always reach the instance that owns that session. This document explains how to achieve capacity-aware load balancing with HAProxy using a stick table for session affinity and agent-check weight reporting for distributing new sessions toward backends with more free capacity.

## Session Header Support

FlareSolverr accepts the session ID via the `X-FlareSolverr-Session` HTTP header in addition to the JSON body. This enables HAProxy (or any other reverse proxy) to inspect incoming traffic and route requests based on the session ID without parsing the request body.

- **Header name:** `X-FlareSolverr-Session`
- **Priority:** If the JSON body contains a `session` field, it takes precedence over the header.
- **Use case:** Load balancers can read the header to implement sticky sessions (source affinity).

### Critical: Pre-Generate the Session ID

Because HAProxy uses a stick table keyed on the session ID, **the client must pre-generate the session ID and send it via the `X-FlareSolverr-Session` header from the very first request** (including `sessions.create`). If you let the server assign a random UUID during `sessions.create`, the create request will be routed to some backend, but subsequent requests carrying that server-generated ID may not include the header — and without the header, HAProxy cannot look up the stick-table entry and may route to a different backend where the session does not exist.

Correct workflow:

1. Client generates its own session ID (e.g., a UUID).
2. Client sends `X-FlareSolverr-Session: <client-generated-id>` on **every** request, starting with `sessions.create`.
3. HAProxy creates a stick-table entry on the first request, pinning that session ID to the chosen backend.
4. All future requests with the same header value follow the stick-table entry to the same backend.

### Example Request with Header

```bash
# Create a session - header is present so HAProxy routes consistently from the start
curl -X POST http://flaresolverr-cluster:8191/v1 \
  -H "Content-Type: application/json" \
  -H "X-FlareSolverr-Session: my-session-id" \
  -d '{"cmd": "sessions.create"}'

# Reuse the session - same header hits the same backend
curl -X POST http://flaresolverr-cluster:8191/v1 \
  -H "Content-Type: application/json" \
  -H "X-FlareSolverr-Session: my-session-id" \
  -d '{"cmd": "request.get", "url": "https://example.com"}'
```

## HAProxy Configuration

Below is a complete HAProxy configuration that balances traffic across three FlareSolverr backends. New sessions are distributed with `balance random` (weighted by agent-check capacity), while a stick table keyed on `X-FlareSolverr-Session` ensures all subsequent requests for the same session hit the same backend.

### Requirements

- HAProxy 2.0+ (for `balance random` and stick-table support)
- All backends must be reachable from HAProxy
- `AGENT_CHECK_PORT` set on each FlareSolverr instance (for capacity-aware weighting)

### Configuration

```haproxy
global
    log /dev/log local0
    maxconn 4096

defaults
    mode http
    timeout connect 5s
    timeout client 30s
    timeout server 60s
    option httpchk GET /health

frontend flaresolverr_frontend
    bind *:8191
    default_backend flaresolverr_backend

backend flaresolverr_backend
    balance random
    stick-table type string len 64 size 1m expire 6h
    stick on req.hdr(X-FlareSolverr-Session)

    # Health checks
    option httpchk GET /health
    http-check expect status 200

    # Backend servers with agent-check for capacity-aware weighting
    server fs1 10.0.0.11:8191 check weight 100 agent-check agent-port 8085
    server fs2 10.0.0.12:8191 check weight 100 agent-check agent-port 8085
    server fs3 10.0.0.13:8191 check weight 100 agent-check agent-port 8085
```

### How It Works

- `balance random` distributes new sessions across backends with probability proportional to each backend's effective weight (agent-check percentage × configured `weight`).
- `stick-table` + `stick on req.hdr(X-FlareSolverr-Session)` pins each session ID to the backend that handled its first request. All follow-up requests with the same header value bypass the load balancer and go directly to the pinned backend.
- `agent-check` queries each backend's TCP agent-check port for a capacity weight. Backends with more free session slots get a higher percentage, so new sessions are routed toward less-loaded hosts.
- `option httpchk GET /health` ensures failed instances are removed from the pool automatically.
- Set `stick-table expire` to a value comfortably longer than your FlareSolverr session TTL (`SESSION_TTL_MINUTES`), so the stick-table entry outlives the session it routes for.

## Agent-Check Protocol

FlareSolverr exposes a TCP agent-check endpoint (enabled via `AGENT_CHECK_PORT` and `AGENT_CHECK_HOST`) that HAProxy queries to determine backend capacity. The response reflects **remaining session capacity** (`(SESSION_MAX_COUNT - sessionsCount) / SESSION_MAX_COUNT`) only; request concurrency is already limited by HAProxy's `maxconn`.

| State | Condition |
|-------|-----------|
| `up {weight}%` | Sessions below max capacity — weight reflects free slot percentage |
| `drain` | Sessions at max capacity — server stays up but receives no new sessions |

The `weight` percentage is scaled against the server's configured `weight` in HAProxy. For example, `up 50%` with `weight 100` yields an effective weight of 50. The minimum reported weight while `up` is `1%` (never `0%`); `0` free slots is handled by the `drain` branch.

Example: A backend with 4/16 sessions will return `up 75%`, signaling HAProxy to route 75% of the traffic it would otherwise send to a fully free backend. A backend with 16/16 sessions returns `drain`, which keeps the server up for existing sessions (stick-table hits) but stops new sessions from being assigned to it.

`drain` is the HAProxy-native way to say "up but no new sessions." It is equivalent to weight 0 and is more reliably supported than `up 0%` across HAProxy versions. Existing sessions in the stick table can still reach a drained backend because stick-table hits bypass the balancing algorithm entirely.

### Enabling

Set `AGENT_CHECK_PORT` (and optionally `AGENT_CHECK_HOST`) on each FlareSolverr instance:

```yaml
# docker-compose.yml
services:
  flaresolverr-1:
    image: ghcr.io/smeinecke/flaresolverr:latest
    environment:
      - AGENT_CHECK_PORT=8080
      - AGENT_CHECK_HOST=0.0.0.0
```

> **Note:** The agent-check listener usually binds to `127.0.0.1` by default. If HAProxy reaches the container from another host/container, set `AGENT_CHECK_HOST=0.0.0.0`.

### HAProxy Configuration with Agent-Check

```haproxy
global
    maxconn 4096

defaults
    mode http
    timeout connect 5s
    timeout client 30s
    timeout server 60s
    option httpchk GET /health

frontend flaresolverr_frontend
    bind *:8191
    default_backend flaresolverr

backend flaresolverr
    balance random
    stick-table type string len 64 size 1m expire 6h
    stick on req.hdr(X-FlareSolverr-Session)
    option forwardfor
    option httpchk GET /health
    http-check send meth GET uri /health
    http-check expect status 200

    server fs1 192.168.1.10:8191 check maxconn 8 weight 100 agent-check agent-port 8085
    server fs2 192.168.1.11:8191 check maxconn 8 weight 100 agent-check agent-port 8085
```

Key directives:
- `agent-check` — enables TCP agent polling for this server
- `agent-port 8085` — the TCP port where HAProxy connects for agent-check
- `maxconn 8` — optional limit on concurrent HTTP connections per backend

> **Note:** `maxconn` limits HAProxy's HTTP connections to a backend, while FlareSolverr's `MAX_PARALLEL_REQUESTS` limits the number of browser requests it processes in parallel. These operate at different layers, but they should ideally be aligned to your actual capacity. If HAProxy allows 8 connections but FlareSolverr is already at 8 parallel requests, the 9th connection will queue in HAProxy rather than being rejected with HTTP 429.

### Fallback for Missing Header

If a request does not contain the `X-FlareSolverr-Session` header, HAProxy cannot look up a stick-table entry and will route it via `balance random` to any available backend. Stateless requests (no session) will work on any instance. However, any request that targets a specific session **must** include the header, otherwise it may land on a backend that does not own the session.

Alternatively, configure clients to always send the session header.

## Docker Compose Example

```yaml
services:
  haproxy:
    image: haproxy:2.9-alpine
    ports:
      - "8191:8191"
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro

  flaresolverr-1:
    image: ghcr.io/smeinecke/flaresolverr:latest
    environment:
      - LOG_LEVEL=info

  flaresolverr-2:
    image: ghcr.io/smeinecke/flaresolverr:latest
    environment:
      - LOG_LEVEL=info

  flaresolverr-3:
    image: ghcr.io/smeinecke/flaresolverr:latest
    environment:
      - LOG_LEVEL=info
```

Corresponding `haproxy.cfg`:

```haproxy
global
    maxconn 4096

defaults
    mode http
    timeout connect 5s
    timeout client 30s
    timeout server 60s

frontend flaresolverr_frontend
    bind *:8191
    default_backend flaresolverr_backend

backend flaresolverr_backend
    balance random
    stick-table type string len 64 size 1m expire 6h
    stick on req.hdr(X-FlareSolverr-Session)
    option httpchk GET /health
    http-check expect status 200

    server fs1 flaresolverr-1:8191 check weight 100 agent-check agent-port 8085
    server fs2 flaresolverr-2:8191 check weight 100 agent-check agent-port 8085
    server fs3 flaresolverr-3:8191 check weight 100 agent-check agent-port 8085
```

## Client Integration

When using the FlareSolverr Python client in a clustered environment, `sessions.create()` **automatically generates a UUID** and sends it in the request body. This ensures HAProxy routes the create and all subsequent requests to the same backend consistently:

```python
from flaresolverr import FlareSolverrClient

client = FlareSolverrClient("http://haproxy:8191")

# Create a session - client auto-generates a UUID and sends it in the body
resp = client.sessions.create()
session_id = resp.session

# Subsequent requests with the same session ID will hit the same backend
resp = client.request.get(url="https://example.com", session=session_id)
```

If you need a predictable session ID, you can override it explicitly:

```python
resp = client.sessions.create(session_id="my-workflow-1")
```

For non-Python clients or when you want to guarantee routing before the body is parsed, send the `X-FlareSolverr-Session` header explicitly on **every** request (including `sessions.create`).

## Client Requirements

For session-aware load balancing to work correctly, clients **must**:

1. Pre-generate a session ID (UUID) before calling `sessions.create`.
2. Include `X-FlareSolverr-Session: <session-id>` on **every** request.
3. Include the same `session` value in the JSON body of `sessions.create`.
4. Call `sessions.destroy` when done to free capacity.

### URL Path Routing

FlareSolverr accepts commands via URL path: `POST /v1/<group>/<command>`. This allows HAProxy to route based on URL alone, without inspecting JSON bodies.

```bash
# sessions.create via URL path — HAProxy can route by path alone
curl -X POST http://flaresolverr-cluster:8191/v1/sessions/create \
  -H "Content-Type: application/json" \
  -H "X-FlareSolverr-Session: my-session-id" \
  -d '{"session": "my-session-id"}'

# sessions.destroy via URL path
curl -X POST http://flaresolverr-cluster:8191/v1/sessions/destroy \
  -H "Content-Type: application/json" \
  -H "X-FlareSolverr-Session: my-session-id" \
  -d '{"session": "my-session-id"}'
```

With URL path routing, HAProxy can use ACLs to distinguish command types and apply different policies. With a stick table, `sessions.create` and all later requests for that session go through the same `flaresolverr_backend` — the stick-table entry (not a header hash) is what pins the session after creation. There is no need for a separate `flaresolverr_create` backend.

```haproxy
frontend flaresolverr_frontend
    bind *:8191

    # All commands go through the same stick-table backend.
    # The stick table pins sessions after the first request.
    default_backend flaresolverr_backend

backend flaresolverr_backend
    balance random
    stick-table type string len 64 size 1m expire 6h
    stick on req.hdr(X-FlareSolverr-Session)
    option forwardfor
    option httpchk GET /health
    http-check send meth GET uri /health
    http-check expect status 200
    server fs1 192.168.1.10:8191 check maxconn 8 weight 100 agent-check agent-port 8085
    server fs2 192.168.1.11:8191 check maxconn 8 weight 100 agent-check agent-port 8085
```

**How it works:**

- **`sessions.create`** → `flaresolverr_backend` with `balance random`. The agent-check weight on each server determines which backend is more likely to receive the new session. The stick-table entry is created on the first request, pinning the session to that backend.
- **`sessions.destroy`** (via `DELETE /v1/sessions/<id>` or `POST /v1/sessions/destroy`) → `flaresolverr_backend` with stick-table lookup. `sessions.destroy` works on a drained backend because stick-table hits bypass the balancing algorithm entirely.
- **`request.get` / `request.post`** → `flaresolverr_backend` with stick-table lookup. The stick-table entry routes the request to the backend that owns the session. `agent-check` only affects new sessions (fresh stick-table entries), not existing ones.

**Capacity-aware distribution**

FlareSolverr's agent-check now returns `up {weight}%` based on remaining session capacity, so HAProxy's `balance random` distributes new sessions toward backends with more free Chrome session slots. This is capacity-aware distribution, not a strict per-request "least active" pick — `balance random` picks a backend with probability proportional to its effective weight (agent-check percentage × configured `weight`).

Backends that reach `SESSION_MAX_COUNT` report `drain`, which keeps them up in HAProxy but prevents new sessions from being routed to them. Existing sessions in the stick table can still reach them.

## Important Notes

- **Pre-generated session IDs are mandatory for clustering:** If you call `sessions.create` without a session ID, the server will generate a random UUID. The create request will be routed to some backend, but subsequent requests carrying that server-generated ID may not include the `X-FlareSolverr-Session` header — and without the header, HAProxy cannot look up the stick-table entry and may route to a different backend where the session does not exist. The Python client handles this automatically by generating a UUID client-side. For non-Python clients or direct API calls, always pre-generate and pass the session ID yourself.
- **Session durability:** Sessions exist only in memory on the instance that created them. If a backend crashes, its sessions are lost. Clients must handle `sessions.create` again when receiving a "session doesn't exist" error.
- **Concurrent access:** FlareSolverr already serializes access to the same session with an internal lock, so multiple requests for one session can safely be queued on the same backend.
- **Scaling:** Adding backends redistributes new sessions. Existing sessions remain pinned to their original backend via the stick table until the entry expires.
- **Health endpoint:** Use `/health` for load balancer health checks. It is lightweight and does not consume a browser instance.
- **Multiple HAProxy instances:** The stick table is local to each HAProxy process. If FlareSolverr is fronted by more than one HAProxy instance (e.g., multiple LB nodes), either pin clients to one LB instance upstream, or add a `peers` section to synchronize stick-table entries across HAProxy instances, or session stickiness will not hold across LB nodes.

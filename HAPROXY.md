# Running FlareSolverr in a Cluster with HAProxy

FlareSolverr stores browser sessions in local memory. When running multiple instances behind a load balancer, requests for the same session must always reach the instance that owns that session. This document explains how to achieve session-aware load balancing with HAProxy.

## Session Header Support

FlareSolverr accepts the session ID via the `X-FlareSolverr-Session` HTTP header in addition to the JSON body. This enables HAProxy (or any other reverse proxy) to inspect incoming traffic and route requests based on the session ID without parsing the request body.

- **Header name:** `X-FlareSolverr-Session`
- **Priority:** If the JSON body contains a `session` field, it takes precedence over the header.
- **Use case:** Load balancers can read the header to implement sticky sessions (source affinity).

### Critical: Pre-Generate the Session ID

Because HAProxy routes based on the session ID, **the client must pre-generate the session ID and send it via the `X-FlareSolverr-Session` header from the very first request** (including `sessions.create`). If you let the server assign a random UUID during `sessions.create`, the create request may land on backend A, but all subsequent requests carrying that server-generated ID may hash to backend B - where the session does not exist.

Correct workflow:

1. Client generates its own session ID (e.g., a UUID).
2. Client sends `X-FlareSolverr-Session: <client-generated-id>` on **every** request, starting with `sessions.create`.
3. HAProxy hashes the header value and consistently routes to the same backend.
4. The session lives on that backend, and all future requests for it hit the same instance.

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

Below is a complete HAProxy configuration that balances traffic across three FlareSolverr backends while ensuring session affinity via the `X-FlareSolverr-Session` header.

### Requirements

- HAProxy 2.0+ (for `hash` balance algorithm with `hdr` fetch method)
- All backends must be reachable from HAProxy

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
    balance hdr(X-FlareSolverr-Session)
    hash-type consistent

    # Health checks
    option httpchk GET /health
    http-check expect status 200

    # Backend servers
    server fs1 10.0.0.11:8191 check
    server fs2 10.0.0.12:8191 check
    server fs3 10.0.0.13:8191 check
```

### How It Works

- `balance hdr(X-FlareSolverr-Session)` routes every request with the same header value to the same backend server.
- `hash-type consistent` minimizes redistribution when backends are added or removed.
- `option httpchk GET /health` ensures failed instances are removed from the pool automatically.

## Agent-Check Protocol

FlareSolverr exposes a TCP agent-check endpoint (enabled via `AGENT_CHECK_PORT` and `AGENT_CHECK_HOST`) that HAProxy queries to determine backend health. The response is based on **both**:

1. **Request load**: `active_requests / MAX_PARALLEL_REQUESTS`
2. **Session saturation**: `sessionsCount / SESSION_MAX_COUNT`

The backend returns the **more restrictive** of the two states:

| State | Condition |
|-------|-----------|
| `ready` | Both requests < 75% capacity AND sessions < 75% capacity |
| `50%` | Either requests >= 75% capacity OR sessions >= 75% capacity |
| `drain` | Either requests at max capacity OR sessions at max capacity |

Example: A backend with 0 active requests but 16/16 sessions will return `drain`, signaling HAProxy to stop sending new connections.

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
    balance hdr(X-FlareSolverr-Session)
    hash-type consistent
    option forwardfor
    option httpchk GET /health
    http-check send meth GET uri /health
    http-check expect status 200

    server fs1 192.168.1.10:8191 check maxconn 8 agent-check agent-port 8085
    server fs2 192.168.1.11:8191 check maxconn 8 agent-check agent-port 8085
```

Key directives:
- `agent-check` — enables TCP agent polling for this server
- `agent-port 8085` — the TCP port where HAProxy connects for agent-check
- `maxconn 8` — optional limit on concurrent HTTP connections per backend

> **Note:** `maxconn` limits HAProxy's HTTP connections to a backend, while FlareSolverr's `MAX_PARALLEL_REQUESTS` limits the number of browser requests it processes in parallel. These operate at different layers, but they should ideally be aligned to your actual capacity. If HAProxy allows 8 connections but FlareSolverr is already at 8 parallel requests, the 9th connection will queue in HAProxy rather than being rejected with HTTP 429.

### Fallback for Missing Header

If a request does not contain the `X-FlareSolverr-Session` header, HAProxy falls back to distributing it across backends. Stateless requests (no session) will work on any instance. If you prefer a different fallback behavior, you can combine the header hash with a secondary algorithm:

```haproxy
backend flaresolverr_backend
    balance hdr(X-FlareSolverr-Session)
    hash-type consistent
    # Fallback: use source IP hashing for requests without the session header
    # (This requires HAProxy 2.4+ or a more complex config)
```

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
    balance hdr(X-FlareSolverr-Session)
    hash-type consistent
    option httpchk GET /health
    http-check expect status 200

    server fs1 flaresolverr-1:8191 check
    server fs2 flaresolverr-2:8191 check
    server fs3 flaresolverr-3:8191 check
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

### Session Creation Routing

The Python client sends an additional `X-FlareSolverr-Create: true` header on `sessions.create` requests. This allows HAProxy to route session creation round-robin to the backend with the most capacity, while all subsequent requests for that session stick to the same backend via `X-FlareSolverr-Session` hashing.

```bash
# sessions.create — routed round-robin to the backend with capacity
# (X-FlareSolverr-Create header present)
curl -X POST http://flaresolverr-cluster:8191/v1 \
  -H "Content-Type: application/json" \
  -H "X-FlareSolverr-Session: my-session-id" \
  -H "X-FlareSolverr-Create: true" \
  -d '{"cmd": "sessions.create", "session": "my-session-id"}'

# All other requests — stick to the same backend via hash
# (only X-FlareSolverr-Session header present)
curl -X POST http://flaresolverr-cluster:8191/v1 \
  -H "Content-Type: application/json" \
  -H "X-FlareSolverr-Session: my-session-id" \
  -d '{"cmd": "request.get", "url": "https://example.com", "session": "my-session-id"}'
```

#### URL Path Routing (Alternative to Headers)

FlareSolverr also accepts commands via URL path: `POST /v1/<group>/<command>`. This allows HAProxy to route based on URL alone, without inspecting JSON bodies or relying on the `X-FlareSolverr-Create` header.

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

With URL path routing, HAProxy can use ACLs to distinguish command types and apply different balancing rules:

```haproxy
frontend flaresolverr_frontend
    bind *:8191

    # Route session creation round-robin (bypass agent-check drain)
    acl is_session_create path_beg /v1/sessions/create
    use_backend flaresolverr_create if is_session_create

    # Route session destruction to main backend with session hash
    # (DELETE /v1/sessions/<id> or POST /v1/sessions/destroy)
    acl is_session_destroy path_beg /v1/sessions/
    use_backend flaresolverr_backend if is_session_destroy

    # Everything else (request.get, request.post, etc.) respects agent-check
    default_backend flaresolverr_backend

backend flaresolverr_create
    balance roundrobin
    option httpchk GET /health
    # Servers WITHOUT agent-check so drain doesn't block creates
    server fs1 192.168.1.10:8191 check maxconn 80
    server fs2 192.168.1.11:8191 check maxconn 80

backend flaresolverr_backend
    balance hdr(X-FlareSolverr-Session)
    hash-type consistent
    option forwardfor
    option httpchk GET /health
    # Servers WITH agent-check for request.* and session management commands
    server fs1 192.168.1.10:8191 check maxconn 8 weight 100 agent-check agent-port 8085
    server fs2 192.168.1.11:8191 check maxconn 8 weight 100 agent-check agent-port 8085
```

**How it works:**

- **`sessions.create`** → `flaresolverr_create` backend with `balance roundrobin`. No `agent-check`, so backends always accept new sessions regardless of load. This prevents a saturated backend from rejecting `sessions.create` with HTTP 503.
- **`sessions.destroy`** (via `DELETE /v1/sessions/<id>` or `POST /v1/sessions/destroy`) → `flaresolverr_backend` with session hash. No `agent-check` on the backend definition either, so destroy always works even when the backend is in `drain` state. The session ID from the URL or header routes to the correct backend.
- **`request.get` / `request.post`** → `flaresolverr_backend` with session hash. Uses `agent-check` so HAProxy dynamically reduces traffic to overloaded backends (`50%` or `drain`).

Without the `X-FlareSolverr-Session` header, HAProxy cannot maintain session affinity and all requests (including `sessions.create`) may land on the same backend, causing `Maximum session count reached` errors even when other backends have capacity.

## Important Notes

- **Pre-generated session IDs are mandatory for clustering:** If you call `sessions.create` without a session ID, the server will generate a random UUID. The create request will be routed to some backend, but subsequent requests carrying that server-generated ID may hash to a different backend where the session does not exist. The Python client handles this automatically by generating a UUID client-side. For non-Python clients or direct API calls, always pre-generate and pass the session ID yourself.
- **Session durability:** Sessions exist only in memory on the instance that created them. If a backend crashes, its sessions are lost. Clients must handle `sessions.create` again when receiving a "session doesn't exist" error.
- **Concurrent access:** FlareSolverr already serializes access to the same session with an internal lock, so multiple requests for one session can safely be queued on the same backend.
- **Scaling:** Adding backends redistributes some sessions. Existing sessions that move to a new backend will be recreated on first access (if `sessions.create` or `request.get` with the session ID is called).
- **Health endpoint:** Use `/health` for load balancer health checks. It is lightweight and does not consume a browser instance.

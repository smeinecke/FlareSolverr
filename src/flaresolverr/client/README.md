# FlareSolverr Python Client

A Python client library for interacting with the FlareSolverr API, a proxy server for bypassing Cloudflare and DDoS-GUARD protection.

## Installation

The client is included with FlareSolverr. Install the main package:

```bash
pip install flaresolverr
```

## Quick Start

```python
from flaresolverr.client import FlareSolverrClient

# Create client
client = FlareSolverrClient("http://localhost:8191")

# Simple GET request
response = client.request.get("https://example.com")
print(response.solution.response)
```

## Features

- **Session Management** - Persistent browser sessions with cookie retention
- **Action Queue** - Fluent API for browser automation (fill forms, click buttons, wait for elements)
- **Full Type Safety** - Dataclass models with type hints throughout
- **Error Handling** - Custom exceptions with detailed error information

## API Reference

### FlareSolverrClient

```python
from flaresolverr.client import FlareSolverrClient

client = FlareSolverrClient(base_url="http://localhost:8191", timeout=120.0)
```

#### Methods

- `health()` - Check API health status
- `index()` - Get service information (version, user agent)

#### Sub-managers

- `client.sessions` - Session management
- `client.request` - HTTP requests (GET/POST)

### Sessions

```python
# Create a persistent session
response = client.sessions.create(session_id="my_session", stealth_mode="standard", user_agent="Mozilla/5.0 ...")
session_id = response.session  # Auto-generated if not provided

# Use session for requests
response = client.request.get("https://example.com", session=session_id)

# List active sessions
response = client.sessions.list()
print(response.sessions)  # ["session_1", "session_2"]

# Destroy session
client.sessions.destroy(session_id)
```

### Requests

#### GET Request

```python
response = client.request.get(
    url="https://example.com",
    session="my_session",           # Optional: reuse session
    max_timeout=60000,              # Max wait time in ms (default: 60000)
    return_only_cookies=False,      # Only return cookies
    return_screenshot=False,        # Include base64 screenshot
    disable_media=False,            # Block images/CSS/fonts
    stealth_mode="standard",        # Optional stealth mode: off|standard|csp-safe
    user_agent="Mozilla/5.0 ...",   # Optional per-request user-agent override
    wait_in_seconds=2,              # Wait after page load
    proxy=ProxyConfig(url="http://proxy:8080"),
    cookies=[Cookie(name="session", value="abc", domain=".example.com", path="/")],
    headers=[Header(name="User-Agent", value="Custom/1.0")],
)

print(response.solution.status)      # HTTP status code
print(response.solution.response)    # HTML content
print(response.solution.cookies)    # List of Cookie objects
print(response.solution.userAgent)  # Browser user agent
```

#### POST Request

```python
response = client.request.post(
    url="https://example.com/login",
    post_data="username=user&password=secret",
    stealth_mode="standard",  # Same options as GET
    user_agent="Mozilla/5.0 ...",
)
```

### ActionQueue

Build browser action chains for form filling, clicking, and waiting:

```python
from flaresolverr.client import ActionQueue

actions = (
    ActionQueue()
    .wait(2)                                           # Wait 2 seconds
    .fill("//input[@id='email']", "user@example.com")  # Type in field
    .fill("//input[@id='password']", "secret123")
    .click("//button[@type='submit']")                # Click button
    .wait_for("//div[@id='dashboard']")                # Wait for element
    .build()
)

response = client.request.get("https://example.com/login", actions=actions)
```

#### Action Types

- `wait(seconds)` - Sleep for N seconds (useful for interaction trackers)
- `fill(selector, value)` - Type value into field (uses XPath)
- `click(selector, human_like=False)` - Click element
- `wait_for(selector)` - Wait until element is visible

### Models

```python
from flaresolverr.client import (
    ProxyConfig,
    Cookie,
    Header,
    V1Response,
    ChallengeSolution,
    FlareSolverrError,
)

# Proxy configuration
proxy = ProxyConfig(
    url="http://proxy.example.com:8080",
    username="user",      # Optional
    password="pass",      # Optional
)

# Cookie from response
response = client.request.get("https://example.com")
for cookie in response.solution.cookies:
    print(f"{cookie.name}={cookie.value} (domain: {cookie.domain})")
```

## Error Handling

```python
from flaresolverr.client import FlareSolverrError

try:
    response = client.request.get("https://example.com")
except FlareSolverrError as e:
    print(f"API error: {e}")
    if e.response:
        print(f"Status: {e.response.status}")
        print(f"Message: {e.response.message}")
```

## Advanced Example

Complete login flow with session reuse:

```python
from flaresolverr.client import FlareSolverrClient, ActionQueue, ProxyConfig

client = FlareSolverrClient("http://localhost:8191")

# Create session
session = client.sessions.create()
session_id = session.session

try:
    # Login with actions
    actions = (
        ActionQueue()
        .wait(1)
        .fill("//input[@name='username']", "myuser")
        .fill("//input[@name='password']", "mypass")
        .click("//button[@type='submit']")
        .wait_for("//div[@class='logged-in']")
        .build()
    )

    login_response = client.request.post(
        "https://example.com/login",
        post_data="username=myuser&password=mypass",
        session=session_id,
        actions=actions,
    )

    # Use same session for authenticated requests
    profile = client.request.get(
        "https://example.com/profile",
        session=session_id,
    )
    print(profile.solution.response)

finally:
    # Clean up
    client.sessions.destroy(session_id)
```

## License

MIT License - same as FlareSolverr.

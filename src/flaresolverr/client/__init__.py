"""FlareSolverr Python Client Library.

This package provides a Pythonic client for interacting with the FlareSolverr API,
a proxy server for bypassing Cloudflare and DDoS-GUARD protection.

Basic Usage:
    >>> from flaresolverr.client import FlareSolverrClient, ActionQueue
    >>>
    >>> # Create client
    >>> client = FlareSolverrClient("http://localhost:8191")
    >>>
    >>> # Simple GET request
    >>> response = client.request.get("https://example.com")
    >>> print(response.solution.response)

Session Management:
    >>> # Create a session (persists cookies and browser state)
    >>> session = client.sessions.create(
    ...     "my_session_id",
    ...     enabled_services=["cloudflare", "ddos_guard"],  # Optional: override which challenge services are active
    ... )
    >>>
    >>> # Use the session for multiple requests
    >>> response1 = client.request.get("https://example.com", session="my_session_id")
    >>> response2 = client.request.get("https://example.com/profile", session="my_session_id")
    >>>
    >>> # Interact with an existing session without re-navigating
    >>> # Get current page info (URL, title, cookies, source)
    >>> info = client.sessions.get("my_session_id")
    >>> print(info.solution.url, info.solution.title)
    >>>
    >>> # Execute JavaScript in the session
    >>> js_result = client.sessions.eval("my_session_id", "return document.title")
    >>> print(js_result.solution.evalResult)
    >>>
    >>> # Capture DevTools network logs
    >>> net = client.sessions.network("my_session_id")
    >>> print(f"Captured {len(net.solution.networkLogs)} events")
    >>>
    >>> # Click an element by XPath
    >>> client.sessions.click("my_session_id", "//button[contains(.,'Verify')]")
    >>>
    >>> # Execute multiple actions (fill, click, wait, wait_for)
    >>> client.sessions.action("my_session_id", [
    ...     {"type": "wait", "seconds": 2},
    ...     {"type": "click", "selector": "//button", "humanLike": True},
    ...     {"type": "wait_for", "selector": "//div[@id='success']"},
    ... ])
    >>>
    >>> # Capture a screenshot
    >>> screenshot = client.sessions.screenshot("my_session_id")
    >>> print(screenshot.solution.screenshot[:50])  # base64 PNG
    >>>
    >>> # Clear session context without closing the browser
    >>> client.sessions.clear("my_session_id")
    >>>
    >>> # Clean up when done
    >>> client.sessions.destroy("my_session_id")

Browser Actions (Form Filling):
    >>> from flaresolverr.client import ActionQueue
    >>>
    >>> # Build action chain
    >>> actions = (
    ...     ActionQueue()
    ...     .wait(2)  # Wait for page interaction trackers
    ...     .fill("//input[@id='email']", "user@example.com")
    ...     .fill("//input[@id='password']", "secret123")
    ...     .click("//button[@type='submit']")
    ...     .wait_for("//div[@id='dashboard']")
    ...     .build()
    ... )
    >>>
    >>> response = client.request.get("https://example.com/login", actions=actions)

POST Requests:
    >>> # Send a POST request with form data
    >>> post_data = "username=user&password=secret"
    >>> response = client.request.post("https://example.com/login", post_data)

Health Check:
    >>> health = client.health()
    >>> print(health.status)  # "ok" if service is healthy

Models:
    >>> from flaresolverr.client import ProxyConfig, Cookie, Header
    >>>
    >>> # Configure a proxy
    >>> proxy = ProxyConfig(url="http://proxy.example.com:8080")
    >>>
    >>> # Use cookies from a previous response
    >>> response = client.request.get("https://example.com")
    >>> cookies = response.solution.cookies
    >>>
    >>> # Send those cookies in a new request
    >>> response2 = client.request.get("https://example.com", cookies=cookies)

Error Handling:
    >>> from flaresolverr.client import FlareSolverrError
    >>>
    >>> try:
    ...     response = client.request.get("https://example.com")
    ... except FlareSolverrError as e:
    ...     print(f"API error: {e}")
    ...     print(f"Response status: {e.response.status}")
"""

from .actions import ActionQueue
from .client import FlareSolverrClient, FlareSolverrError
from .models import (
    Action,
    ChallengeSolution,
    Cookie,
    HealthResponse,
    Header,
    IndexResponse,
    ProxyConfig,
    V1Response,
)

__all__ = [
    # Client
    "FlareSolverrClient",
    "FlareSolverrError",
    # Actions
    "ActionQueue",
    # Models
    "Action",
    "ChallengeSolution",
    "Cookie",
    "HealthResponse",
    "Header",
    "IndexResponse",
    "ProxyConfig",
    "V1Response",
]

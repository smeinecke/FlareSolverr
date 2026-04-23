"""FlareSolverrClient for interacting with the FlareSolverr API."""

from __future__ import annotations

import logging
from typing import Any

import requests

from flaresolverr.client.models import (
    Cookie,
    Header,
    HealthResponse,
    IndexResponse,
    ProxyConfig,
    V1Response,
)

logger = logging.getLogger(__name__)


class FlareSolverrError(Exception):
    """Exception raised for FlareSolverr API errors."""

    def __init__(self, message: str, response: V1Response | None = None):
        super().__init__(message)
        self.response = response


class _SessionManager:
    """Internal class for session management API calls."""

    def __init__(self, client: FlareSolverrClient):
        self._client = client

    def create(self, session_id: str | None = None, proxy: ProxyConfig | None = None) -> V1Response:
        """Create a new browser session.

        Sessions retain cookies and persist browser state until destroyed.
        Using sessions speeds up requests since it avoids launching a new
        browser instance for every request.

        Args:
            session_id: Optional custom session ID. If not provided, a random UUID is assigned.
            proxy: Optional proxy configuration for this session.

        Returns:
            V1Response containing the session ID on success.

        Raises:
            FlareSolverrError: If the session cannot be created.
        """
        payload: dict[str, Any] = {"cmd": "sessions.create"}
        if session_id is not None:
            payload["session"] = session_id
        if proxy is not None:
            payload["proxy"] = proxy.to_dict()

        return self._client._post_v1(payload)

    def list(self) -> V1Response:
        """List all active sessions.

        Returns:
            V1Response containing the list of session IDs.
        """
        payload: dict[str, Any] = {"cmd": "sessions.list"}
        return self._client._post_v1(payload)

    def destroy(self, session_id: str) -> V1Response:
        """Destroy a browser session.

        Properly shuts down the browser instance and frees up resources.
        Always destroy sessions when you're done using them.

        Args:
            session_id: The session ID to destroy.

        Returns:
            V1Response confirming the session was removed.

        Raises:
            FlareSolverrError: If the session doesn't exist.
        """
        payload: dict[str, Any] = {"cmd": "sessions.destroy", "session": session_id}
        return self._client._post_v1(payload)


class _RequestManager:
    """Internal class for request API calls (GET and POST)."""

    def __init__(self, client: FlareSolverrClient):
        self._client = client

    def get(
        self,
        url: str,
        *,
        session: str | None = None,
        session_ttl_minutes: int | None = None,
        max_timeout: int = 60000,
        cookies: list[Cookie] | None = None,
        headers: list[Header] | None = None,
        return_only_cookies: bool = False,
        return_screenshot: bool = False,
        proxy: ProxyConfig | None = None,
        wait_in_seconds: int | None = None,
        disable_media: bool = False,
        tabs_till_verify: int | None = None,
        actions: list[dict] | None = None,
        captcha_solver: str | None = None,
    ) -> V1Response:
        """Send a GET request through FlareSolverr.

        Args:
            url: The URL to request (mandatory).
            session: Optional session ID for persistent browser state.
            session_ttl_minutes: Optional TTL for automatic session rotation.
            max_timeout: Maximum time in ms to wait for challenge resolution (default: 60000).
            cookies: Optional cookies to send with the request.
            headers: Optional custom HTTP headers.
            return_only_cookies: If True, only return cookies (no HTML, headers, etc.).
            return_screenshot: If True, capture a screenshot as base64 PNG.
            proxy: Optional proxy configuration.
            wait_in_seconds: Optional wait after solving challenge before returning.
            disable_media: If True, block images/CSS/fonts to speed up loading.
            tabs_till_verify: Number of Tab presses needed for turnstile captcha.
            actions: Optional list of browser actions to perform after page load.
            captcha_solver: Optional captcha solver name (default: "default").

        Returns:
            V1Response containing the solution.

        Raises:
            FlareSolverrError: If the request fails or times out.
        """
        payload = self._build_payload(
            cmd="request.get",
            url=url,
            session=session,
            session_ttl_minutes=session_ttl_minutes,
            max_timeout=max_timeout,
            cookies=cookies,
            headers=headers,
            return_only_cookies=return_only_cookies,
            return_screenshot=return_screenshot,
            proxy=proxy,
            wait_in_seconds=wait_in_seconds,
            disable_media=disable_media,
            tabs_till_verify=tabs_till_verify,
            actions=actions,
            captcha_solver=captcha_solver,
        )
        return self._client._post_v1(payload)

    def post(
        self,
        url: str,
        post_data: str,
        *,
        session: str | None = None,
        session_ttl_minutes: int | None = None,
        max_timeout: int = 60000,
        cookies: list[Cookie] | None = None,
        headers: list[Header] | None = None,
        return_only_cookies: bool = False,
        return_screenshot: bool = False,
        proxy: ProxyConfig | None = None,
        wait_in_seconds: int | None = None,
        disable_media: bool = False,
        tabs_till_verify: int | None = None,
        actions: list[dict] | None = None,
        captcha_solver: str | None = None,
    ) -> V1Response:
        """Send a POST request through FlareSolverr.

        Args:
            url: The URL to request (mandatory).
            post_data: Form data as application/x-www-form-urlencoded string (e.g., "a=b&c=d").
            session: Optional session ID for persistent browser state.
            session_ttl_minutes: Optional TTL for automatic session rotation.
            max_timeout: Maximum time in ms to wait for challenge resolution (default: 60000).
            cookies: Optional cookies to send with the request.
            headers: Optional custom HTTP headers.
            return_only_cookies: If True, only return cookies (no HTML, headers, etc.).
            return_screenshot: If True, capture a screenshot as base64 PNG.
            proxy: Optional proxy configuration.
            wait_in_seconds: Optional wait after solving challenge before returning.
            disable_media: If True, block images/CSS/fonts to speed up loading.
            actions: Optional list of browser actions to perform after page load.
            captcha_solver: Optional captcha solver name (default: "default").

        Returns:
            V1Response containing the solution.

        Raises:
            FlareSolverrError: If the request fails or times out.
        """
        payload = self._build_payload(
            cmd="request.post",
            url=url,
            post_data=post_data,
            session=session,
            session_ttl_minutes=session_ttl_minutes,
            max_timeout=max_timeout,
            cookies=cookies,
            headers=headers,
            return_only_cookies=return_only_cookies,
            return_screenshot=return_screenshot,
            proxy=proxy,
            wait_in_seconds=wait_in_seconds,
            disable_media=disable_media,
            tabs_till_verify=tabs_till_verify,
            actions=actions,
            captcha_solver=captcha_solver,
        )
        return self._client._post_v1(payload)

    def _build_payload(
        self,
        *,
        cmd: str,
        url: str,
        post_data: str | None = None,
        session: str | None = None,
        session_ttl_minutes: int | None = None,
        max_timeout: int = 60000,
        cookies: list[Cookie] | None = None,
        headers: list[Header] | None = None,
        return_only_cookies: bool = False,
        return_screenshot: bool = False,
        proxy: ProxyConfig | None = None,
        wait_in_seconds: int | None = None,
        disable_media: bool = False,
        tabs_till_verify: int | None = None,
        actions: list[dict] | None = None,
        captcha_solver: str | None = None,
    ) -> dict[str, Any]:
        """Build the API request payload."""
        payload: dict[str, Any] = {
            "cmd": cmd,
            "url": url,
            "maxTimeout": max_timeout,
        }

        if post_data is not None:
            payload["postData"] = post_data
        if session is not None:
            payload["session"] = session
        if session_ttl_minutes is not None:
            payload["session_ttl_minutes"] = session_ttl_minutes
        if cookies is not None:
            payload["cookies"] = [{"name": c.name, "value": c.value} for c in cookies]
        if headers is not None:
            payload["headers"] = [h.to_dict() for h in headers]
        if return_only_cookies:
            payload["returnOnlyCookies"] = True
        if return_screenshot:
            payload["returnScreenshot"] = True
        if proxy is not None:
            payload["proxy"] = proxy.to_dict()
        if wait_in_seconds is not None:
            payload["waitInSeconds"] = wait_in_seconds
        if disable_media:
            payload["disableMedia"] = True
        if tabs_till_verify is not None:
            payload["tabs_till_verify"] = tabs_till_verify
        if actions is not None:
            payload["actions"] = actions
        if captcha_solver is not None:
            payload["captchaSolver"] = captcha_solver

        return payload


class FlareSolverrClient:
    """Client for interacting with the FlareSolverr API.

    This client provides a Pythonic interface to all FlareSolverr API endpoints,
    including session management, GET/POST requests, and health checks.

    Attributes:
        base_url: The base URL of the FlareSolverr service.
        timeout: HTTP timeout for API requests in seconds.

    Example:
        >>> client = FlareSolverrClient("http://localhost:8191")
        >>> response = client.request.get("https://example.com")
        >>> print(response.solution.response)
    """

    def __init__(self, base_url: str = "http://localhost:8191", timeout: float = 120.0):
        """Initialize the FlareSolverr client.

        Args:
            base_url: The base URL of the FlareSolverr service (default: http://localhost:8191).
            timeout: HTTP timeout for API requests in seconds (default: 120).
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.sessions = _SessionManager(self)
        self.request = _RequestManager(self)

    def health(self) -> HealthResponse:  # noqa
        """Check the health status of the FlareSolverr service.

        Returns:
            HealthResponse with status "ok" if the service is healthy.

        Raises:
            requests.RequestException: If the health check fails.
        """
        url = f"{self.base_url}/health"
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        return HealthResponse.from_dict(response.json())

    def index(self) -> IndexResponse:  # noqa
        """Get the FlareSolverr service information.

        Returns:
            IndexResponse containing the version and user agent string.

        Raises:
            requests.RequestException: If the request fails.
        """
        url = f"{self.base_url}/"
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        return IndexResponse.from_dict(response.json())

    def _post_v1(self, payload: dict[str, Any]) -> V1Response:
        """Internal method to POST to the v1 API endpoint.

        Args:
            payload: The JSON payload to send.

        Returns:
            Parsed V1Response.

        Raises:
            FlareSolverrError: If the API returns an error status.
            requests.RequestException: If the HTTP request fails.
        """
        url = f"{self.base_url}/v1"
        headers = {"Content-Type": "application/json"}

        logger.debug(f"POST {url} with payload: {payload}")
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()

        data = response.json()
        v1_response = V1Response.from_dict(data)

        if not v1_response.is_ok:
            raise FlareSolverrError(v1_response.message or "Unknown API error", v1_response)

        return v1_response

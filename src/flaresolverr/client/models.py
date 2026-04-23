"""Dataclass models for FlareSolverr API types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ProxyConfig:
    """Proxy configuration for requests and sessions."""

    url: str
    username: str | None = None
    password: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dictionary."""
        result: dict[str, Any] = {"url": self.url}
        if self.username is not None:
            result["username"] = self.username
        if self.password is not None:
            result["password"] = self.password
        return result


@dataclass
class Cookie:
    """Cookie representation returned by FlareSolverr."""

    name: str
    value: str
    domain: str
    path: str
    expires: float | None = None  # noqa
    size: int | None = None
    httpOnly: bool = False  # noqa
    secure: bool = False  # noqa
    session: bool = False
    sameSite: str | None = None  # noqa

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Cookie:
        """Create a Cookie from a dictionary."""
        return cls(
            name=data.get("name", ""),
            value=data.get("value", ""),
            domain=data.get("domain", ""),
            path=data.get("path", "/"),
            expires=data.get("expires"),
            size=data.get("size"),
            httpOnly=data.get("httpOnly", False),
            secure=data.get("secure", False),
            session=data.get("session", False),
            sameSite=data.get("sameSite"),
        )


@dataclass
class Header:
    """HTTP header for requests."""

    name: str
    value: str

    def to_dict(self) -> dict[str, str]:
        """Convert to API-compatible dictionary."""
        return {"name": self.name, "value": self.value}


@dataclass
class Action:
    """Browser action to perform during a request."""

    type: Literal["fill", "click", "wait_for", "wait"]
    selector: str | None = None
    value: str | None = None
    seconds: float | None = None
    humanLike: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-compatible dictionary."""
        result: dict[str, Any] = {"type": self.type}
        if self.selector is not None:
            result["selector"] = self.selector
        if self.value is not None:
            result["value"] = self.value
        if self.seconds is not None:
            result["seconds"] = self.seconds
        if self.humanLike:
            result["humanLike"] = True
        return result


@dataclass
class ChallengeSolution:
    """Solution result from a challenge resolution request."""

    url: str | None = None
    status: int | None = None
    headers: dict[str, Any] = field(default_factory=dict)
    response: str | None = None
    cookies: list[Cookie] = field(default_factory=list)
    userAgent: str | None = None
    screenshot: str | None = None  # noqa
    turnstile_token: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ChallengeSolution | None:
        """Create a ChallengeSolution from a dictionary."""
        if data is None:
            return None
        cookies = [Cookie.from_dict(c) for c in data.get("cookies", [])]
        return cls(
            url=data.get("url"),
            status=data.get("status"),
            headers=data.get("headers", {}),
            response=data.get("response"),
            cookies=cookies,
            userAgent=data.get("userAgent"),
            screenshot=data.get("screenshot"),
            turnstile_token=data.get("turnstile_token"),
        )


@dataclass
class V1Response:
    """Full response from the FlareSolverr API v1 endpoint."""

    status: str
    message: str
    solution: ChallengeSolution | None = None
    session: str | None = None
    sessions: list[str] | None = None
    startTimestamp: int | None = None
    endTimestamp: int | None = None
    version: str | None = None  # noqa

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> V1Response:
        """Create a V1Response from a dictionary."""
        solution_data = data.get("solution")
        return cls(
            status=data.get("status", ""),
            message=data.get("message", ""),
            solution=ChallengeSolution.from_dict(solution_data) if solution_data else None,
            session=data.get("session"),
            sessions=data.get("sessions"),
            startTimestamp=data.get("startTimestamp"),
            endTimestamp=data.get("endTimestamp"),
            version=data.get("version"),
        )

    @property
    def is_ok(self) -> bool:
        """Check if the response status is 'ok'."""
        return self.status == "ok"


@dataclass
class HealthResponse:
    """Response from the health endpoint."""

    status: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthResponse:
        """Create a HealthResponse from a dictionary."""
        return cls(status=data.get("status", ""))


@dataclass
class IndexResponse:
    """Response from the index endpoint."""

    msg: str  # noqa
    version: str  # noqa
    userAgent: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexResponse:
        """Create an IndexResponse from a dictionary."""
        return cls(
            msg=data.get("msg", ""),
            version=data.get("version", ""),
            userAgent=data.get("userAgent", ""),
        )

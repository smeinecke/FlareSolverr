from typing import Any

STATUS_OK = "ok"
STATUS_ERROR = "error"


class ChallengeResolutionResultT:
    url: str | None = None
    status: int | None = None
    headers: list[Any] | dict[str, Any] | None = None
    response: str | None = None
    cookies: list[dict[str, Any]] | None = None
    userAgent: str | None = None
    screenshot: str | None = None  # noqa
    turnstile_token: str | None = None
    isBinary: bool | None = None
    # Session interaction results
    evalResult: Any | None = None
    networkLogs: list[dict[str, Any]] | None = None
    title: str | None = None

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)


class ChallengeResolutionT:
    status: str | None = None
    message: str | None = None
    result: ChallengeResolutionResultT | None = None

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)
        if isinstance(self.result, dict):
            self.result = ChallengeResolutionResultT(self.result)


class V1RequestBase(object):
    # V1RequestBase
    cmd: str | None = None
    cookies: list[dict[str, Any]] | None = None
    maxTimeout: int | None = None
    proxy: dict[str, Any] | None = None
    session: str | None = None
    session_ttl_minutes: int | None = None
    sessionMaxRuntime: int | None = None  # Optional per-session max lifetime in seconds
    sessionIdleTimeout: int | None = None  # Optional per-session idle timeout in seconds
    headers: list[Any] | None = None  # custom headers to send with requests
    userAgent: str | None = None  # Optional per-request/session user agent override
    acceptLanguage: str | None = None  # Optional per-request/session accept-language override
    stealth: bool | None = None  # Optional per-request/session stealth mode override
    stealthMode: str | None = None  # Optional stealth mode enum override: off|standard|csp-safe

    # V1Request
    url: str | None = None
    postData: str | None = None
    postDataRaw: str | None = None
    postDataContentType: str | None = None
    returnOnlyCookies: bool | None = None
    returnScreenshot: bool | None = None
    download: bool | None = None
    returnRawHtml: bool | None = None  # deprecated v2.0.0, not used
    waitInSeconds: int | None = None
    # Session interaction commands
    script: str | None = None  # JS script to execute (sessions.eval)
    selector: str | None = None  # Element selector for click/wait actions
    # Optional resource blocking flag (blocks images, CSS, and fonts)
    disableMedia: bool | None = None
    # Optional when you've got a turnstile captcha that needs to be clicked after X number of Tab presses
    tabs_till_verify: int | None = None
    # Optional list of browser actions to perform after the page loads (before capturing the result).
    # Supported action types:
    #   {"type": "fill",           "selector": "//input[@id='id']", "value": "text"} - clear and type into a field
    #   {"type": "click",          "selector": "//button", "humanLike": false} - click; set humanLike=true for bezier-curve mouse movement
    #   {"type": "wait_for",       "selector": "//div[@id='result']"}    - wait until selector is visible
    #   {"type": "wait",           "seconds": 2}                         - sleep N seconds
    #   {"type": "eval",           "script": "return document.title"}      - execute JS and capture result
    #   {"type": "eval",           "script": "return document.title", "returnResult": false} - execute JS without capturing
    actions: list[dict[str, Any]] | None = None
    captchaSolver: str | None = None  # Optional per-request solver override
    enabledServices: list[str] | None = None  # Optional per-request/session enabled challenge services
    # CDP command execution (sessions.cdp)
    cdp: dict[str, Any] | None = None
    # JavaScript injection (issue #38).
    # NOTE: Raw JS execution is already supported via:
    #   - sessions.eval command (driver.execute_script)
    #   - "eval" action type in the actions chain
    # scriptInject adds *declarative* injection at page lifecycle points
    # (document_start, document_end, document_idle) controlled by the
    # JS_INJECTION_ENABLED environment variable.
    # Each entry is {"script": "...", "point": "document_start|document_end|document_idle"}.
    # When point is omitted, it defaults to document_idle.
    scriptInject: list[dict[str, Any]] | None = None  # noqa

    def __init__(self, _dict: dict[str, Any]):
        # Explicit allowlist to prevent arbitrary attribute injection from JSON input
        known_attrs = {
            "cmd",
            "cookies",
            "maxTimeout",
            "proxy",
            "session",
            "session_ttl_minutes",
            "sessionMaxRuntime",
            "sessionIdleTimeout",
            "headers",
            "userAgent",
            "acceptLanguage",
            "stealth",
            "stealthMode",
            "url",
            "postData",
            "postDataRaw",
            "postDataContentType",
            "returnOnlyCookies",
            "returnScreenshot",
            "download",
            "returnRawHtml",
            "waitInSeconds",
            "script",
            "selector",
            "disableMedia",
            "tabs_till_verify",
            "actions",
            "captchaSolver",
            "enabledServices",
            "cdp",
            "scriptInject",
        }
        for key, value in _dict.items():
            if key in known_attrs:
                setattr(self, key, value)


class ChallengeError(Exception):
    """Exception that carries optional debug details for challenge failures."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details


class V1ResponseBase(object):
    # V1ResponseBase
    status: str | None = None
    message: str | None = None
    session: str | None = None
    sessions: list[str] | None = None
    startTimestamp: int | None = None
    endTimestamp: int | None = None
    version: str | None = None  # noqa

    # V1ResponseSolution
    solution: ChallengeResolutionResultT | None = None

    # Optional debug details for error responses (e.g. Brave challenge timeout info)
    details: dict[str, Any] | None = None

    # hidden vars
    __error_500__: bool = False
    __error_429__: bool = False

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)
        if isinstance(self.solution, dict):
            self.solution = ChallengeResolutionResultT(self.solution)


class IndexResponse(object):
    msg: str | None = None  # noqa
    version: str | None = None  # noqa
    userAgent: str | None = None

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)


class HealthResponse(object):
    status: str | None = None
    sessionsCount: int | None = None  # noqa
    activeParallelRequests: int | None = None  # noqa
    maxParallelRequests: int | None = None  # noqa
    maxSessionCount: int | None = None  # noqa
    sessionMaxRuntime: int | None = None  # noqa
    sessionIdleTimeout: int | None = None  # noqa
    version: str | None = None  # noqa
    config: dict[str, Any] | None = None
    activeRequests: list[dict[str, Any]] | None = None  # only when details=true
    sessions: list[dict[str, Any]] | None = None  # only when details=true

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)

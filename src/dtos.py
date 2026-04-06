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
    screenshot: str | None = None
    turnstile_token: str | None = None

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
    headers: list[Any] | None = None  # custom headers to send with requests
    userAgent: str | None = None  # deprecated v2.0.0, not used

    # V1Request
    url: str | None = None
    postData: str | None = None
    returnOnlyCookies: bool | None = None
    returnScreenshot: bool | None = None
    download: bool | None = None  # deprecated v2.0.0, not used
    returnRawHtml: bool | None = None  # deprecated v2.0.0, not used
    waitInSeconds: int | None = None
    # Optional resource blocking flag (blocks images, CSS, and fonts)
    disableMedia: bool | None = None
    # Optional when you've got a turnstile captcha that needs to be clicked after X number of Tab presses
    tabs_till_verify: int | None = None
    # Optional list of browser actions to perform after the page loads (before capturing the result).
    # Supported action types:
    #   {"type": "fill",           "selector": "//input[@id='id']", "value": "text"} — clear and type into a field
    #   {"type": "click",          "selector": "//button", "humanLike": false} — click; set humanLike=true for bezier-curve mouse movement
    #   {"type": "wait_for",       "selector": "//div[@id='result']"}    — wait until selector is visible
    #   {"type": "wait",           "seconds": 2}                         — sleep N seconds
    actions: list[dict[str, Any]] | None = None

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)


class V1ResponseBase(object):
    # V1ResponseBase
    status: str | None = None
    message: str | None = None
    session: str | None = None
    sessions: list[str] | None = None
    startTimestamp: int | None = None
    endTimestamp: int | None = None
    version: str | None = None

    # V1ResponseSolution
    solution: ChallengeResolutionResultT | None = None

    # hidden vars
    __error_500__: bool = False

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)
        if isinstance(self.solution, dict):
            self.solution = ChallengeResolutionResultT(self.solution)


class IndexResponse(object):
    msg: str | None = None
    version: str | None = None
    userAgent: str | None = None

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)


class HealthResponse(object):
    status: str | None = None

    def __init__(self, _dict: dict[str, Any]):
        self.__dict__.update(_dict)

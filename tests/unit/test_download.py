from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("func_timeout")
from flaresolverr.dtos import ChallengeResolutionResultT, V1RequestBase
from flaresolverr.flaresolverr_service import _build_challenge_result, _get_download_content


class FakeDriver:
    def __init__(self, current_url="https://example.com/image.jpg", page_source="<html></html>"):
        self._current_url = current_url
        self._page_source = page_source
        self._cookies = [{"name": "test", "value": "cookie"}]
        self._screenshot = "base64screenshot"
        self._calls = []

    @property
    def current_url(self):
        return self._current_url

    @property
    def page_source(self):
        return self._page_source

    def get_cookies(self):
        return self._cookies

    def get_screenshot_as_base64(self):
        return self._screenshot

    def execute_cdp_cmd(self, cmd, params=None):
        self._calls.append(("execute_cdp_cmd", cmd, params))
        return {}

    def execute_script(self, script, *args):
        self._calls.append(("execute_script", script, args))
        return {}


def _make_req(download=False, return_only_cookies=False):
    req = V1RequestBase({"cmd": "request.get", "url": "https://example.com/image.jpg"})
    req.download = download
    req.returnOnlyCookies = return_only_cookies
    req.actions = None
    req.waitInSeconds = None
    req.returnScreenshot = False
    return req


def test_build_challenge_result_without_download_uses_page_source(monkeypatch):
    driver = FakeDriver(page_source="<html><body>hello</body></html>")
    req = _make_req(download=False)

    monkeypatch.setattr(
        "flaresolverr.flaresolverr_service.utils.get_user_agent",
        lambda _driver: "TestUA",
    )

    result = _build_challenge_result(req, driver, None)

    assert isinstance(result, ChallengeResolutionResultT)
    assert result.response == "<html><body>hello</body></html>"
    assert result.isBinary is None
    assert result.url == "https://example.com/image.jpg"
    assert len(driver._calls) == 0


def test_build_challenge_result_with_download_cdp_base64(monkeypatch):
    driver = FakeDriver()

    def fake_execute_cdp_cmd(cmd, params=None):
        driver._calls.append(("execute_cdp_cmd", cmd, params))
        if cmd == "Page.enable":
            return {}
        if cmd == "Page.getResourceContent":
            return {"content": "aGVsbG8=", "base64Encoded": True}
        return {}

    driver.execute_cdp_cmd = fake_execute_cdp_cmd
    req = _make_req(download=True)

    monkeypatch.setattr(
        "flaresolverr.flaresolverr_service.utils.get_user_agent",
        lambda _driver: "TestUA",
    )

    result = _build_challenge_result(req, driver, None)

    assert result.response == "aGVsbG8="
    assert result.isBinary is True
    assert any(c[1] == "Page.getResourceContent" for c in driver._calls)


def test_build_challenge_result_with_download_cdp_text(monkeypatch):
    driver = FakeDriver()

    def fake_execute_cdp_cmd(cmd, params=None):
        driver._calls.append(("execute_cdp_cmd", cmd, params))
        if cmd == "Page.enable":
            return {}
        if cmd == "Page.getResourceContent":
            return {"content": "plain text", "base64Encoded": False}
        return {}

    driver.execute_cdp_cmd = fake_execute_cdp_cmd
    req = _make_req(download=True)

    monkeypatch.setattr(
        "flaresolverr.flaresolverr_service.utils.get_user_agent",
        lambda _driver: "TestUA",
    )

    result = _build_challenge_result(req, driver, None)

    assert result.response == "plain text"
    assert result.isBinary is False


def test_build_challenge_result_with_download_js_fallback(monkeypatch):
    driver = FakeDriver()

    def fake_execute_cdp_cmd(cmd, params=None):
        driver._calls.append(("execute_cdp_cmd", cmd, params))
        if cmd == "Page.enable":
            return {}
        raise Exception("CDP not available")

    def fake_execute_script(script, *args):
        driver._calls.append(("execute_script", script, args))
        return {
            "dataUrl": "data:image/jpeg;base64,/9j/4AAQ...",
            "type": "image/jpeg",
            "size": 12345,
        }

    driver.execute_cdp_cmd = fake_execute_cdp_cmd
    driver.execute_script = fake_execute_script
    req = _make_req(download=True)

    monkeypatch.setattr(
        "flaresolverr.flaresolverr_service.utils.get_user_agent",
        lambda _driver: "TestUA",
    )

    result = _build_challenge_result(req, driver, None)

    assert result.response == "/9j/4AAQ..."
    assert result.isBinary is True
    assert result.headers == {"Content-Type": "image/jpeg", "Content-Length": "12345"}


def test_build_challenge_result_with_download_fallback_to_page_source(monkeypatch):
    driver = FakeDriver(page_source="<html><body>fallback</body></html>")

    def fake_execute_cdp_cmd(cmd, params=None):
        raise Exception("CDP not available")

    def fake_execute_script(script, *args):
        raise Exception("JS fetch failed")

    driver.execute_cdp_cmd = fake_execute_cdp_cmd
    driver.execute_script = fake_execute_script
    req = _make_req(download=True)

    monkeypatch.setattr(
        "flaresolverr.flaresolverr_service.utils.get_user_agent",
        lambda _driver: "TestUA",
    )

    result = _build_challenge_result(req, driver, None)

    assert result.response == "<html><body>fallback</body></html>"
    assert result.isBinary is False


def test_build_challenge_result_return_only_cookies_skips_response(monkeypatch):
    driver = FakeDriver()
    req = _make_req(download=True, return_only_cookies=True)

    monkeypatch.setattr(
        "flaresolverr.flaresolverr_service.utils.get_user_agent",
        lambda _driver: "TestUA",
    )

    result = _build_challenge_result(req, driver, None)

    assert result.response is None
    assert result.cookies == [{"name": "test", "value": "cookie"}]
    assert len(driver._calls) == 0


def test_get_download_content_cdp_text():
    driver = FakeDriver()

    def fake_execute_cdp_cmd(cmd, params=None):
        driver._calls.append(("execute_cdp_cmd", cmd, params))
        if cmd == "Page.enable":
            return {}
        if cmd == "Page.getResourceContent":
            return {"content": "hello world", "base64Encoded": False}
        return {}

    driver.execute_cdp_cmd = fake_execute_cdp_cmd
    content, is_binary, headers = _get_download_content(driver, "https://example.com")

    assert content == "hello world"
    assert is_binary is False
    assert headers is None


def test_get_download_content_js_fetch_text():
    driver = FakeDriver()

    def fake_execute_cdp_cmd(cmd, params=None):
        raise Exception("CDP not available")

    def fake_execute_script(script, *args):
        return {
            "dataUrl": "data:text/plain;base64,aGVsbG8=",
            "type": "text/plain",
            "size": 5,
        }

    driver.execute_cdp_cmd = fake_execute_cdp_cmd
    driver.execute_script = fake_execute_script
    content, is_binary, headers = _get_download_content(driver, "https://example.com")

    assert content == "aGVsbG8="
    assert is_binary is False
    assert headers == {"Content-Type": "text/plain", "Content-Length": "5"}


def test_get_download_content_page_source_fallback():
    driver = FakeDriver(page_source="<html></html>")

    def fake_execute_cdp_cmd(cmd, params=None):
        raise Exception("CDP not available")

    def fake_execute_script(script, *args):
        raise Exception("JS fetch failed")

    driver.execute_cdp_cmd = fake_execute_cdp_cmd
    driver.execute_script = fake_execute_script
    content, is_binary, headers = _get_download_content(driver, "https://example.com")

    assert content == "<html></html>"
    assert is_binary is False
    assert headers is None

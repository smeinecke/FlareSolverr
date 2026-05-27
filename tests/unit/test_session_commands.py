"""Unit tests for session interaction command handlers in flaresolverr_service."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from flaresolverr.dtos import V1RequestBase
from flaresolverr import sessions
from flaresolverr import flaresolverr_service as svc


class _FakeSession:
    """Minimal fake session for command handler tests."""

    def __init__(self, driver):
        self.driver = driver
        self.session_id = "fake-id"
        self.created_at = datetime.now()
        self.stealth_mode = "off"
        self.enabled_services = ["cloudflare"]
        self.request_count = 0
        self.lock = MagicMock()
        self.last_used_at = datetime.now()
        self.max_runtime = None
        self.idle_timeout = sessions.utils.get_config_session_idle_timeout()


@pytest.fixture(autouse=True)
def _patch_sessions_storage(monkeypatch):
    """Replace the global SESSIONS_STORAGE with a fresh in-memory storage."""
    fresh = sessions.SessionsStorage()
    monkeypatch.setattr(svc, "SESSIONS_STORAGE", fresh)
    return fresh


class TestSessionsGet:
    def test_get_returns_url_title_cookies(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.current_url = "https://example.com"
        driver.title = "Test Page"
        driver.page_source = "<html><body>hi</body></html>"
        driver.get_cookies.return_value = [{"name": "x", "value": "y"}]
        driver.execute_script.return_value = "Mozilla/5.0"

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.get", "session": "s1"})
        res = svc._cmd_sessions_get(req)

        assert res.status == "ok"
        assert res.message == "Session info retrieved successfully."
        assert res.solution.url == "https://example.com"
        assert res.solution.title == "Test Page"
        assert res.solution.response == "<html><body>hi</body></html>"
        assert res.solution.cookies == [{"name": "x", "value": "y"}]
        assert res.solution.userAgent == "Mozilla/5.0"

    def test_get_missing_session_raises(self):
        req = V1RequestBase({"cmd": "sessions.get", "session": "missing"})
        with pytest.raises(Exception, match="doesn't exist"):
            svc._cmd_sessions_get(req)

    def test_get_no_session_param_raises(self):
        req = V1RequestBase({"cmd": "sessions.get"})
        with pytest.raises(Exception, match="'session' is mandatory"):
            svc._cmd_sessions_get(req)

    def test_get_gracefully_handles_page_source_exception(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.current_url = "https://example.com"
        driver.title = "Title"
        driver.page_source = "<html></html>"
        driver.get_cookies.return_value = []
        driver.execute_script.side_effect = Exception("boom")

        _patch_sessions_storage.sessions["s2"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.get", "session": "s2"})
        res = svc._cmd_sessions_get(req)

        assert res.status == "ok"
        assert res.solution.userAgent is None


class TestSessionsEval:
    def test_eval_executes_script(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_script.return_value = "script result"
        driver.current_url = "https://example.com"
        driver.get_cookies.return_value = []

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.eval", "session": "s1", "script": "return 42"})
        res = svc._cmd_sessions_eval(req)

        assert res.status == "ok"
        assert res.message == "Script executed successfully."
        assert res.solution.evalResult == "script result"
        driver.execute_script.assert_called_once_with("return 42")

    def test_eval_missing_script_raises(self, _patch_sessions_storage):
        driver = MagicMock()
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.eval", "session": "s1"})
        with pytest.raises(Exception, match="'script' is mandatory"):
            svc._cmd_sessions_eval(req)

    def test_eval_script_error_raises(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_script.side_effect = Exception("JS error")
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.eval", "session": "s1", "script": "bad"})
        with pytest.raises(Exception, match="Error executing script"):
            svc._cmd_sessions_eval(req)


class TestSessionsNetwork:
    def test_network_returns_logs(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.get_log.return_value = [
            {"message": '{"message": {"method": "Network.requestWillBeSent", "params": {}}}'},
            {"message": '{"message": {"method": "Network.responseReceived", "params": {}}}'},
        ]
        driver.current_url = "https://example.com"

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.network", "session": "s1"})
        res = svc._cmd_sessions_network(req)

        assert res.status == "ok"
        assert "2" in res.message
        assert isinstance(res.solution.networkLogs, list)
        assert len(res.solution.networkLogs) == 2
        assert res.solution.networkLogs[0]["method"] == "Network.requestWillBeSent"

    def test_network_missing_session_raises(self):
        req = V1RequestBase({"cmd": "sessions.network", "session": "missing"})
        with pytest.raises(Exception, match="doesn't exist"):
            svc._cmd_sessions_network(req)


class TestSessionsClick:
    def test_click_element(self, _patch_sessions_storage):
        element = MagicMock()
        element.is_displayed.return_value = True
        element.get_attribute.return_value = None

        driver = MagicMock()
        driver.find_element.return_value = element
        driver.current_url = "https://example.com"
        driver.get_cookies.return_value = []

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        with patch.object(svc, "_human_like_click") as mock_hlc:
            req = V1RequestBase({"cmd": "sessions.click", "session": "s1", "selector": "//button"})
            res = svc._cmd_sessions_click(req)

        assert res.status == "ok"
        assert res.message == "Element clicked successfully."
        mock_hlc.assert_called_once_with(driver, element)

    def test_click_not_displayed_raises(self, _patch_sessions_storage):
        element = MagicMock()
        element.is_displayed.return_value = False

        driver = MagicMock()
        driver.find_element.return_value = element
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.click", "session": "s1", "selector": "//button"})
        with pytest.raises(Exception, match="not displayed"):
            svc._cmd_sessions_click(req)

    def test_click_disabled_raises(self, _patch_sessions_storage):
        element = MagicMock()
        element.is_displayed.return_value = True
        element.get_attribute.return_value = "disabled"

        driver = MagicMock()
        driver.find_element.return_value = element
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.click", "session": "s1", "selector": "//button"})
        with pytest.raises(Exception, match="disabled"):
            svc._cmd_sessions_click(req)

    def test_click_missing_selector_raises(self, _patch_sessions_storage):
        driver = MagicMock()
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.click", "session": "s1"})
        with pytest.raises(Exception, match="'selector' is mandatory"):
            svc._cmd_sessions_click(req)


class TestSessionsAction:
    def test_action_executes_actions(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.current_url = "https://example.com"
        driver.title = "Action Page"
        driver.get_cookies.return_value = []

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        actions = [{"type": "wait", "seconds": 0.5}]
        with patch.object(svc, "_execute_actions") as mock_exec:
            req = V1RequestBase({"cmd": "sessions.action", "session": "s1", "actions": actions})
            res = svc._cmd_sessions_action(req)

        assert res.status == "ok"
        assert res.message == "Actions executed successfully."
        mock_exec.assert_called_once_with(driver, actions)

    def test_action_missing_actions_raises(self, _patch_sessions_storage):
        driver = MagicMock()
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.action", "session": "s1"})
        with pytest.raises(Exception, match="'actions' is mandatory"):
            svc._cmd_sessions_action(req)

    def test_action_eval_returns_result(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_script.return_value = "token123"
        driver.current_url = "https://example.com"
        driver.title = "Page"
        driver.get_cookies.return_value = []

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        actions = [{"type": "eval", "script": "return localStorage.getItem('key')"}]
        req = V1RequestBase({"cmd": "sessions.action", "session": "s1", "actions": actions})
        res = svc._cmd_sessions_action(req)

        assert res.status == "ok"
        assert res.solution.evalResult == "token123"
        driver.execute_script.assert_called_once_with("return localStorage.getItem('key')")

    def test_action_eval_multiple_returns_list(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_script.side_effect = ["a", "b"]
        driver.current_url = "https://example.com"
        driver.title = "Page"
        driver.get_cookies.return_value = []

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        actions = [
            {"type": "eval", "script": "return 1"},
            {"type": "wait", "seconds": 0.1},
            {"type": "eval", "script": "return 2"},
        ]
        req = V1RequestBase({"cmd": "sessions.action", "session": "s1", "actions": actions})
        res = svc._cmd_sessions_action(req)

        assert res.status == "ok"
        assert res.solution.evalResult == ["a", "b"]

    def test_action_eval_error_raises(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_script.side_effect = Exception("JS error")
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        actions = [{"type": "eval", "script": "bad"}]
        req = V1RequestBase({"cmd": "sessions.action", "session": "s1", "actions": actions})
        with pytest.raises(Exception, match="Error executing eval action"):
            svc._cmd_sessions_action(req)


class TestSessionsScreenshot:
    def test_screenshot_returns_base64(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.get_screenshot_as_base64.return_value = "aGVsbG8="
        driver.current_url = "https://example.com"
        driver.title = "Page"

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.screenshot", "session": "s1"})
        res = svc._cmd_sessions_screenshot(req)

        assert res.status == "ok"
        assert res.message == "Screenshot captured successfully."
        assert res.solution.screenshot == "aGVsbG8="
        assert res.solution.url == "https://example.com"

    def test_screenshot_missing_session_raises(self):
        req = V1RequestBase({"cmd": "sessions.screenshot", "session": "missing"})
        with pytest.raises(Exception, match="doesn't exist"):
            svc._cmd_sessions_screenshot(req)

    def test_screenshot_error_raises(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.get_screenshot_as_base64.side_effect = Exception("screenshot failed")
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.screenshot", "session": "s1"})
        with pytest.raises(Exception, match="Error capturing screenshot"):
            svc._cmd_sessions_screenshot(req)


class TestSessionsCdp:
    def test_cdp_executes_command(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_cdp_cmd.return_value = {"result": {"value": "ok"}}
        driver.current_url = "https://example.com"

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({
            "cmd": "sessions.cdp",
            "session": "s1",
            "cdp_cmd": "Runtime.evaluate",
            "cdp_params": {"expression": "1+1"},
        })
        res = svc._cmd_sessions_cdp(req)

        assert res.status == "ok"
        assert res.message == "CDP command executed successfully."
        assert res.solution.evalResult == {"result": {"value": "ok"}}
        driver.execute_cdp_cmd.assert_called_once_with("Runtime.evaluate", {"expression": "1+1"})

    def test_cdp_without_params(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_cdp_cmd.return_value = {}
        driver.current_url = "https://example.com"

        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.cdp", "session": "s1", "cdp_cmd": "Runtime.enable"})
        res = svc._cmd_sessions_cdp(req)

        assert res.status == "ok"
        driver.execute_cdp_cmd.assert_called_once_with("Runtime.enable", {})

    def test_cdp_missing_session_raises(self):
        req = V1RequestBase({"cmd": "sessions.cdp", "session": "missing", "cdp_cmd": "Runtime.enable"})
        with pytest.raises(Exception, match="doesn't exist"):
            svc._cmd_sessions_cdp(req)

    def test_cdp_missing_cmd_raises(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_cdp_cmd.side_effect = Exception("invalid command name")
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.cdp", "session": "s1"})
        with pytest.raises(Exception, match="Error executing CDP command"):
            svc._cmd_sessions_cdp(req)

    def test_cdp_command_error_raises(self, _patch_sessions_storage):
        driver = MagicMock()
        driver.execute_cdp_cmd.side_effect = Exception("invalid command")
        _patch_sessions_storage.sessions["s1"] = _FakeSession(driver)

        req = V1RequestBase({"cmd": "sessions.cdp", "session": "s1", "cdp_cmd": "Bad.command"})
        with pytest.raises(Exception, match="Error executing CDP command"):
            svc._cmd_sessions_cdp(req)

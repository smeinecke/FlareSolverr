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


def _make_session_driver(return_values=None, **kwargs):
    """Create a MagicMock driver with common session-test defaults."""
    driver = MagicMock()
    driver.current_url = "https://example.com"
    for k, v in kwargs.items():
        setattr(driver, k, v)
    if return_values:
        for method, ret in return_values.items():
            getattr(driver, method).return_value = ret
    return driver


def _register_session(storage, driver, sid="s1"):
    """Register a fake session with the given driver in storage."""
    storage.sessions[sid] = _FakeSession(driver)


@pytest.fixture(autouse=True)
def _patch_sessions_storage(monkeypatch):
    """Replace the global SESSIONS_STORAGE with a fresh in-memory storage."""
    fresh = sessions.SessionsStorage()
    monkeypatch.setattr(svc, "SESSIONS_STORAGE", fresh)
    return fresh


class TestSessionsGet:
    def test_get_returns_url_title_cookies(self, _patch_sessions_storage):
        driver = _make_session_driver(
            title="Test Page",
            page_source="<html><body>hi</body></html>",
            return_values={"get_cookies": [{"name": "x", "value": "y"}], "execute_script": "Mozilla/5.0"},
        )
        _register_session(_patch_sessions_storage, driver)

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
        driver = _make_session_driver(
            title="Title",
            page_source="<html></html>",
            return_values={"get_cookies": []},
            execute_script=Exception("boom"),
        )
        _register_session(_patch_sessions_storage, driver, "s2")

        req = V1RequestBase({"cmd": "sessions.get", "session": "s2"})
        res = svc._cmd_sessions_get(req)

        assert res.status == "ok"
        assert res.solution.userAgent is None


class TestSessionsEval:
    def test_eval_executes_script(self, _patch_sessions_storage):
        driver = _make_session_driver(
            return_values={"execute_script": "script result", "get_cookies": []},
        )
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.eval", "session": "s1", "script": "return 42"})
        res = svc._cmd_sessions_eval(req)

        assert res.status == "ok"
        assert res.message == "Script executed successfully."
        assert res.solution.evalResult == "script result"
        driver.execute_script.assert_called_once_with("return 42")

    def test_eval_missing_script_raises(self, _patch_sessions_storage):
        driver = _make_session_driver()
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.eval", "session": "s1"})
        with pytest.raises(Exception, match="'script' is mandatory"):
            svc._cmd_sessions_eval(req)

    def test_eval_script_error_raises(self, _patch_sessions_storage):
        driver = _make_session_driver(execute_script=Exception("JS error"))
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.eval", "session": "s1", "script": "bad"})
        with pytest.raises(Exception, match="Error executing script"):
            svc._cmd_sessions_eval(req)


class TestSessionsNetwork:
    def test_network_returns_logs(self, _patch_sessions_storage):
        driver = _make_session_driver(
            return_values={"get_log": [
                {"message": '{"message": {"method": "Network.requestWillBeSent", "params": {}}}'},
                {"message": '{"message": {"method": "Network.responseReceived", "params": {}}}'},
            ]},
        )
        _register_session(_patch_sessions_storage, driver)

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

        driver = _make_session_driver(return_values={"find_element": element, "get_cookies": []})
        _register_session(_patch_sessions_storage, driver)

        with patch.object(svc, "_human_like_click") as mock_hlc:
            req = V1RequestBase({"cmd": "sessions.click", "session": "s1", "selector": "//button"})
            res = svc._cmd_sessions_click(req)

        assert res.status == "ok"
        assert res.message == "Element clicked successfully."
        mock_hlc.assert_called_once_with(driver, element)

    def test_click_not_displayed_raises(self, _patch_sessions_storage):
        element = MagicMock()
        element.is_displayed.return_value = False

        driver = _make_session_driver(return_values={"find_element": element})
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.click", "session": "s1", "selector": "//button"})
        with pytest.raises(Exception, match="not displayed"):
            svc._cmd_sessions_click(req)

    def test_click_disabled_raises(self, _patch_sessions_storage):
        element = MagicMock()
        element.is_displayed.return_value = True
        element.get_attribute.return_value = "disabled"

        driver = _make_session_driver(return_values={"find_element": element})
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.click", "session": "s1", "selector": "//button"})
        with pytest.raises(Exception, match="disabled"):
            svc._cmd_sessions_click(req)

    def test_click_missing_selector_raises(self, _patch_sessions_storage):
        driver = _make_session_driver()
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.click", "session": "s1"})
        with pytest.raises(Exception, match="'selector' is mandatory"):
            svc._cmd_sessions_click(req)


class TestSessionsClear:
    def test_clear_success(self, _patch_sessions_storage):
        driver = _make_session_driver(
            title="Blank",
            return_values={"get_cookies": []},
        )
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.clear", "session": "s1"})
        with patch.object(svc, "_clear_session_context") as mock_clear:
            res = svc._cmd_sessions_clear(req)

        assert res.status == "ok"
        assert res.message == "Session context cleared successfully."
        mock_clear.assert_called_once_with(driver)

    def test_clear_missing_session_raises(self):
        req = V1RequestBase({"cmd": "sessions.clear", "session": "missing"})
        with pytest.raises(Exception, match="doesn't exist"):
            svc._cmd_sessions_clear(req)

    def test_clear_no_session_param_raises(self):
        req = V1RequestBase({"cmd": "sessions.clear"})
        with pytest.raises(Exception, match="'session' is mandatory"):
            svc._cmd_sessions_clear(req)

    def test_clear_context_error_raises(self, _patch_sessions_storage):
        driver = _make_session_driver()
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.clear", "session": "s1"})
        with patch.object(svc, "_clear_session_context", side_effect=Exception("clear failed")):
            with pytest.raises(Exception, match="Error clearing session context"):
                svc._cmd_sessions_clear(req)


class TestSessionsAction:
    def test_action_executes_actions(self, _patch_sessions_storage):
        driver = _make_session_driver(
            title="Action Page",
            return_values={"get_cookies": []},
        )
        _register_session(_patch_sessions_storage, driver)

        actions = [{"type": "wait", "seconds": 0.5}]
        with patch.object(svc, "_execute_actions") as mock_exec:
            req = V1RequestBase({"cmd": "sessions.action", "session": "s1", "actions": actions})
            res = svc._cmd_sessions_action(req)

        assert res.status == "ok"
        assert res.message == "Actions executed successfully."
        mock_exec.assert_called_once_with(driver, actions)

    def test_action_missing_actions_raises(self, _patch_sessions_storage):
        driver = _make_session_driver()
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.action", "session": "s1"})
        with pytest.raises(Exception, match="'actions' is mandatory"):
            svc._cmd_sessions_action(req)

    def test_action_eval_returns_result(self, _patch_sessions_storage):
        driver = _make_session_driver(
            title="Page",
            return_values={"execute_script": "token123", "get_cookies": []},
        )
        _register_session(_patch_sessions_storage, driver)

        actions = [{"type": "eval", "script": "return localStorage.getItem('key')"}]
        req = V1RequestBase({"cmd": "sessions.action", "session": "s1", "actions": actions})
        res = svc._cmd_sessions_action(req)

        assert res.status == "ok"
        assert res.solution.evalResult == "token123"
        driver.execute_script.assert_called_once_with("return localStorage.getItem('key')")

    def test_action_eval_multiple_returns_list(self, _patch_sessions_storage):
        driver = _make_session_driver(
            title="Page",
            return_values={"get_cookies": [], "execute_script": ["a", "b"]},
        )
        driver.execute_script.side_effect = ["a", "b"]
        _register_session(_patch_sessions_storage, driver)

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
        driver = _make_session_driver(execute_script=Exception("JS error"))
        _register_session(_patch_sessions_storage, driver)

        actions = [{"type": "eval", "script": "bad"}]
        req = V1RequestBase({"cmd": "sessions.action", "session": "s1", "actions": actions})
        with pytest.raises(Exception, match="Error executing eval action"):
            svc._cmd_sessions_action(req)


class TestSessionsScreenshot:
    def test_screenshot_returns_base64(self, _patch_sessions_storage):
        driver = _make_session_driver(
            title="Page",
            return_values={"get_screenshot_as_base64": "aGVsbG8="},
        )
        _register_session(_patch_sessions_storage, driver)

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
        driver = _make_session_driver()
        driver.get_screenshot_as_base64.side_effect = Exception("screenshot failed")
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.screenshot", "session": "s1"})
        with pytest.raises(Exception, match="Error capturing screenshot"):
            svc._cmd_sessions_screenshot(req)


class TestSessionsCdp:
    def test_cdp_executes_command(self, _patch_sessions_storage):
        driver = _make_session_driver(
            return_values={"execute_cdp_cmd": {"result": {"value": "ok"}}},
        )
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({
            "cmd": "sessions.cdp",
            "session": "s1",
            "cdp": {
                "cmd": "Runtime.evaluate",
                "params": {"expression": "1+1"},
            },
        })
        res = svc._cmd_sessions_cdp(req)

        assert res.status == "ok"
        assert res.message == "CDP command executed successfully."
        assert res.solution.evalResult == {"result": {"value": "ok"}}
        driver.execute_cdp_cmd.assert_called_once_with("Runtime.evaluate", {"expression": "1+1"})

    def test_cdp_without_params(self, _patch_sessions_storage):
        driver = _make_session_driver(return_values={"execute_cdp_cmd": {}})
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.cdp", "session": "s1", "cdp": {"cmd": "Runtime.enable"}})
        res = svc._cmd_sessions_cdp(req)

        assert res.status == "ok"
        driver.execute_cdp_cmd.assert_called_once_with("Runtime.enable", {})

    def test_cdp_missing_session_raises(self):
        req = V1RequestBase({"cmd": "sessions.cdp", "session": "missing", "cdp": {"cmd": "Runtime.enable"}})
        with pytest.raises(Exception, match="doesn't exist"):
            svc._cmd_sessions_cdp(req)

    def test_cdp_missing_cmd_raises(self, _patch_sessions_storage):
        driver = _make_session_driver(execute_cdp_cmd=Exception("invalid command name"))
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.cdp", "session": "s1"})
        with pytest.raises(Exception, match="Error executing CDP command"):
            svc._cmd_sessions_cdp(req)

    def test_cdp_command_error_raises(self, _patch_sessions_storage):
        driver = _make_session_driver(execute_cdp_cmd=Exception("invalid command"))
        _register_session(_patch_sessions_storage, driver)

        req = V1RequestBase({"cmd": "sessions.cdp", "session": "s1", "cdp": {"cmd": "Bad.command"}})
        with pytest.raises(Exception, match="Error executing CDP command"):
            svc._cmd_sessions_cdp(req)

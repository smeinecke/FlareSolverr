"""Unit tests for the browser actions feature (_execute_actions).

Covers all four action types (fill, click, wait_for, wait), the humanLike
click flag, unknown-type handling, empty/None action lists, and the
integration point in _build_challenge_result.
"""

import logging
import time
from unittest.mock import MagicMock, call

import pytest

from flaresolverr import flaresolverr_service as svc
from flaresolverr.dtos import V1RequestBase
from selenium.webdriver.common.by import By


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_element(location=None, size=None):
    el = MagicMock()
    el.location = location or {"x": 100, "y": 200}
    el.size = size or {"width": 120, "height": 40}
    return el


def _make_driver():
    driver = MagicMock()
    driver.current_url = "https://example.com"
    driver.page_source = "<html></html>"
    driver.get_cookies.return_value = []
    driver.execute_script.return_value = None
    # innerWidth/innerHeight used by _human_like_click
    driver.execute_script.side_effect = lambda script, *_: (
        800 if "innerWidth" in script else
        600 if "innerHeight" in script else
        None
    )
    return driver


def _patch_wait(driver, monkeypatch, element=None):
    """Replace driver wait methods so they return immediately."""
    el = element or _make_element()
    driver.wait_for_presence.return_value = el
    driver.wait_for_visibility.return_value = el
    return el


# ── fill ──────────────────────────────────────────────────────────────────────

def _patch_action_chains(driver):
    """Attach a fluent MagicMock action_chain to the driver."""
    chains = MagicMock()
    chains.move_to_element.return_value = chains
    chains.move_to_element_with_offset.return_value = chains
    chains.move_by_offset.return_value = chains
    chains.pause.return_value = chains
    chains.click.return_value = chains
    chains.click_and_hold.return_value = chains
    chains.release.return_value = chains
    chains.perform.return_value = None
    driver.action_chain.return_value = chains
    return chains


class TestFillAction:
    def test_clears_and_types_value(self, monkeypatch):
        driver = _make_driver()
        el = _patch_wait(driver, monkeypatch)
        _patch_action_chains(driver)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)

        svc._execute_actions(driver, [
            {"type": "fill", "selector": "//input[@id='email']", "value": "hi@x.com"},
        ])

        el.clear.assert_called_once()
        typed = "".join(c for (c,) in (a.args for a in el.send_keys.call_args_list))
        assert typed == "hi@x.com"

    def test_types_each_char_individually(self, monkeypatch):
        driver = _make_driver()
        el = _patch_wait(driver, monkeypatch)
        _patch_action_chains(driver)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)

        svc._execute_actions(driver, [
            {"type": "fill", "selector": "//input", "value": "abc"},
        ])

        assert el.send_keys.call_count == 3
        assert el.send_keys.call_args_list == [call("a"), call("b"), call("c")]

    def test_empty_value_clears_without_typing(self, monkeypatch):
        driver = _make_driver()
        el = _patch_wait(driver, monkeypatch)
        _patch_action_chains(driver)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)

        svc._execute_actions(driver, [{"type": "fill", "selector": "//input", "value": ""}])

        el.clear.assert_called_once()
        el.send_keys.assert_not_called()

    def test_scrolls_into_view(self, monkeypatch):
        driver = _make_driver()
        _patch_wait(driver, monkeypatch)
        _patch_action_chains(driver)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        scripts = []
        driver.execute_script.side_effect = lambda s, *_: scripts.append(s)

        svc._execute_actions(driver, [{"type": "fill", "selector": "//input", "value": "x"}])

        assert any("scrollIntoView" in s for s in scripts)

    def test_uses_xpath_locator(self, monkeypatch):
        driver = _make_driver()
        el = _patch_wait(driver, monkeypatch)
        _patch_action_chains(driver)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        captured = []
        driver.wait_for_presence.side_effect = lambda by, value, timeout: captured.append((by, value)) or el

        svc._execute_actions(driver, [
            {"type": "fill", "selector": "//input[@name='q']", "value": "x"},
        ])

        assert captured[0][0] == By.XPATH
        assert captured[0][1] == "//input[@name='q']"


# ── click ─────────────────────────────────────────────────────────────────────

class TestClickAction:
    def test_default_uses_action_chains(self, monkeypatch):
        driver = _make_driver()
        _patch_wait(driver, monkeypatch)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        human_called = []
        monkeypatch.setattr(svc, "_human_like_click", lambda d, e: human_called.append(True))
        chains = _patch_action_chains(driver)

        svc._execute_actions(driver, [{"type": "click", "selector": "//button"}])

        assert not human_called
        # Now uses move_to_element_with_offset for non-center clicks
        chains.move_to_element_with_offset.assert_called_once()
        chains.click.assert_called_once()

    def test_human_like_true_calls_bezier(self, monkeypatch):
        driver = _make_driver()
        _patch_wait(driver, monkeypatch)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        human_called = []
        monkeypatch.setattr(svc, "_human_like_click", lambda d, e: human_called.append(True))

        svc._execute_actions(driver, [{"type": "click", "selector": "//button", "humanLike": True}])

        assert human_called == [True]

    def test_human_like_false_uses_action_chains(self, monkeypatch):
        driver = _make_driver()
        _patch_wait(driver, monkeypatch)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        human_called = []
        monkeypatch.setattr(svc, "_human_like_click", lambda d, e: human_called.append(True))
        chains = _patch_action_chains(driver)

        svc._execute_actions(driver, [{"type": "click", "selector": "//button", "humanLike": False}])

        assert not human_called
        chains.click.assert_called_once()

    def test_scrolls_into_view(self, monkeypatch):
        driver = _make_driver()
        _patch_wait(driver, monkeypatch)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        monkeypatch.setattr(svc, "_human_like_click", lambda d, e: None)
        scripts = []
        driver.execute_script.side_effect = lambda s, *_: scripts.append(s)

        svc._execute_actions(driver, [{"type": "click", "selector": "//button", "humanLike": True}])

        assert any("scrollIntoView" in s for s in scripts)

    def test_uses_xpath_locator(self, monkeypatch):
        driver = _make_driver()
        _patch_wait(driver, monkeypatch)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        captured = []
        driver.wait_for_presence.side_effect = lambda by, value, timeout: captured.append((by, value)) or _make_element()
        chains = _patch_action_chains(driver)

        svc._execute_actions(driver, [{"type": "click", "selector": "//form//button"}])

        assert captured[0][0] == By.XPATH
        assert captured[0][1] == "//form//button"


# ── wait_for ──────────────────────────────────────────────────────────────────

class TestWaitForAction:
    def test_waits_for_element_visibility(self, monkeypatch):
        driver = _make_driver()
        _patch_wait(driver, monkeypatch)
        called = []
        driver.wait_for_visibility.side_effect = lambda by, value, timeout: called.append((by, value))

        svc._execute_actions(driver, [{"type": "wait_for", "selector": "//div[@id='result']"}])

        assert called == [(By.XPATH, "//div[@id='result']")]

    def test_uses_xpath_locator(self, monkeypatch):
        driver = _make_driver()
        captured = []
        driver.wait_for_visibility.side_effect = lambda by, value, timeout: captured.append((by, value))

        svc._execute_actions(driver, [{"type": "wait_for", "selector": "//div[@id='done']"}])

        assert len(captured) == 1
        assert captured[0][0] == By.XPATH
        assert captured[0][1] == "//div[@id='done']"

    def test_uses_visibility_not_presence(self, monkeypatch):
        """wait_for must use wait_for_visibility, not wait_for_presence."""
        driver = _make_driver()
        called = []
        driver.wait_for_visibility.side_effect = lambda by, value, timeout: called.append((by, value))

        svc._execute_actions(driver, [{"type": "wait_for", "selector": "//span"}])

        assert called == [(By.XPATH, "//span")]


# ── wait ──────────────────────────────────────────────────────────────────────

class TestWaitAction:
    def test_sleeps_given_seconds(self, monkeypatch):
        slept = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: slept.append(s))

        svc._execute_actions(MagicMock(), [{"type": "wait", "seconds": 3}])

        assert slept == [3.0]

    def test_defaults_to_one_second(self, monkeypatch):
        slept = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: slept.append(s))

        svc._execute_actions(MagicMock(), [{"type": "wait"}])

        assert slept == [1.0]

    def test_accepts_float(self, monkeypatch):
        slept = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: slept.append(s))

        svc._execute_actions(MagicMock(), [{"type": "wait", "seconds": 0.5}])

        assert slept == [0.5]


# ── clear_context ───────────────────────────────────────────────────────────

class TestClearContextAction:
    def test_calls_clear_session_context(self, monkeypatch):
        driver = _make_driver()
        called = []
        monkeypatch.setattr(svc, "_clear_session_context", lambda d: called.append(d))

        svc._execute_actions(driver, [{"type": "clear_context"}])

        assert called == [driver]

    def test_error_raises(self, monkeypatch):
        driver = _make_driver()
        monkeypatch.setattr(svc, "_clear_session_context", lambda d: (_ for _ in ()).throw(Exception("clear failed")))

        with pytest.raises(Exception, match="Error executing clear_context action"):
            svc._execute_actions(driver, [{"type": "clear_context"}])


# ── edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_unknown_type_logs_warning(self, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING):
            svc._execute_actions(MagicMock(), [{"type": "hover"}])

        assert "hover" in caplog.text

    def test_empty_list_is_noop(self, monkeypatch):
        driver = _make_driver()

        svc._execute_actions(driver, [])

        driver.execute_script.assert_not_called()

    def test_multiple_actions_execute_in_order(self, monkeypatch):
        slept = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: slept.append(s))

        svc._execute_actions(MagicMock(), [
            {"type": "wait", "seconds": 1},
            {"type": "wait", "seconds": 2},
        ])

        assert slept == [1.0, 2.0]


# ── _build_challenge_result integration ──────────────────────────────────────

class TestBuildChallengeResultIntegration:
    def test_actions_invoked_when_present(self, monkeypatch):
        driver = _make_driver()
        called_with = []

        def _fake_execute(d, a):
            called_with.append(a)
            return []

        monkeypatch.setattr(svc, "_execute_actions", _fake_execute)
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "Chrome/1")

        actions = [{"type": "wait", "seconds": 1}]
        req = V1RequestBase({"cmd": "request.get", "url": "https://x.com", "actions": actions})

        svc._build_challenge_result(req, driver, None)

        assert called_with == [actions]

    def test_actions_not_invoked_when_absent(self, monkeypatch):
        driver = _make_driver()
        called = []
        monkeypatch.setattr(svc, "_execute_actions", lambda d, a: called.append(True))
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "Chrome/1")

        req = V1RequestBase({"cmd": "request.get", "url": "https://x.com"})
        svc._build_challenge_result(req, driver, None)

        assert called == []

    def test_actions_not_invoked_with_return_only_cookies(self, monkeypatch):
        driver = _make_driver()
        called = []
        monkeypatch.setattr(svc, "_execute_actions", lambda d, a: called.append(True))
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "Chrome/1")

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "returnOnlyCookies": True,
            "actions": [{"type": "wait", "seconds": 1}],
        })
        svc._build_challenge_result(req, driver, None)

        assert called == []

    def test_actions_run_before_page_source_capture(self, monkeypatch):
        driver = _make_driver()
        sequence = []

        def fake_actions(d, a):
            sequence.append("actions")
            return []

        monkeypatch.setattr(svc, "_execute_actions", fake_actions)
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "Chrome/1")

        # Replace page_source property to record when it is read
        original_page_source = driver.page_source
        type(driver).page_source = property(
            lambda self: (sequence.append("page_source") or original_page_source)
        )

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "actions": [{"type": "wait", "seconds": 0}],
        })
        svc._build_challenge_result(req, driver, None)

        assert sequence.index("actions") < sequence.index("page_source")

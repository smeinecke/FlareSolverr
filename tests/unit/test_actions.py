"""Unit tests for the browser actions feature (_execute_actions).

Covers all four action types (fill, click, wait_for, wait), the humanLike
click flag, unknown-type handling, empty/None action lists, and the
integration point in _build_challenge_result.
"""

import time
from unittest.mock import MagicMock, call

from flaresolverr.dtos import V1RequestBase


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


def _make_context(driver=None):
    """Create a mock BrowserContext for unit tests."""
    ctx = MagicMock()
    mock_element = _make_element()

    ctx.current_url = "https://example.com"
    ctx.page_source = "<html></html>"
    ctx.title = "Example"
    ctx.get_cookies.return_value = []
    ctx.get_screenshot_as_base64.return_value = ""
    ctx.get_user_agent.return_value = "Chrome/1"

    # Wait methods return a mock element
    ctx.wait_for_presence.return_value = mock_element
    ctx.wait_for_visibility.return_value = mock_element
    ctx.wait_for_absence.return_value = True
    ctx.wait_for_title.return_value = True
    ctx.wait_for_title_not.return_value = True
    ctx.wait_for_staleness.return_value = True

    # Action chain returns a fluent mock
    chain = MagicMock()
    chain.move_to_element.return_value = chain
    chain.move_by_offset.return_value = chain
    chain.pause.return_value = chain
    chain.click.return_value = chain
    chain.click_and_hold.return_value = chain
    chain.release.return_value = chain
    chain.send_keys.return_value = chain
    ctx.action_chain.return_value = chain

    ctx.execute_script.return_value = None

    if driver is not None:
        # Proxy execute_script to the underlying driver for tests that inspect it
        ctx.execute_script.side_effect = lambda script, *args: driver.execute_script(script, *args)

    return ctx, mock_element, chain


def _patch_wait(monkeypatch, element=None):
    """No-op; waits are mocked via _make_context."""
    el = element or _make_element()
    return el, None


def _patch_action_chains(monkeypatch):
    """No-op; action chains are mocked via _make_context."""
    pass


# ── fill ──────────────────────────────────────────────────────────────────────

class TestFillAction:
    def test_clears_and_types_value(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        ctx, el, _ = _make_context()
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)

        svc._execute_actions(ctx, [
            {"type": "fill", "selector": "//input[@id='email']", "value": "hi@x.com"},
        ])

        el.clear.assert_called_once()
        typed = "".join(c for (c,) in (a.args for a in el.send_keys.call_args_list))
        assert typed == "hi@x.com"

    def test_types_each_char_individually(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        ctx, el, _ = _make_context()
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)

        svc._execute_actions(ctx, [
            {"type": "fill", "selector": "//input", "value": "abc"},
        ])

        assert el.send_keys.call_count == 3
        assert el.send_keys.call_args_list == [call("a"), call("b"), call("c")]

    def test_empty_value_clears_without_typing(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        ctx, el, _ = _make_context()
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)

        svc._execute_actions(ctx, [{"type": "fill", "selector": "//input", "value": ""}])

        el.clear.assert_called_once()
        el.send_keys.assert_not_called()

    def test_scrolls_into_view(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        driver = _make_driver()
        ctx, _, _ = _make_context(driver=driver)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        scripts = []
        driver.execute_script.side_effect = lambda s, *_: scripts.append(s)

        svc._execute_actions(ctx, [{"type": "fill", "selector": "//input", "value": "x"}])

        assert any("scrollIntoView" in s for s in scripts)

    def test_uses_xpath_locator(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc
        from selenium.webdriver.common.by import By

        ctx, _, _ = _make_context()
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)

        svc._execute_actions(ctx, [
            {"type": "fill", "selector": "//input[@name='q']", "value": "x"},
        ])

        # wait_for_presence is called with (by, value, timeout)
        assert ctx.wait_for_presence.call_args[0][0] == By.XPATH
        assert ctx.wait_for_presence.call_args[0][1] == "//input[@name='q']"


# ── click ─────────────────────────────────────────────────────────────────────

class TestClickAction:
    def test_default_uses_action_chains(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        ctx, _, chains = _make_context()
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        human_called = []
        monkeypatch.setattr(svc, "_human_like_click", lambda c, e: human_called.append(True))

        svc._execute_actions(ctx, [{"type": "click", "selector": "//button"}])

        assert not human_called
        chains.move_to_element.assert_called_once()
        chains.click.assert_called_once()

    def test_human_like_true_calls_bezier(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        ctx, el, _ = _make_context()
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        human_called = []
        monkeypatch.setattr(svc, "_human_like_click", lambda c, e: human_called.append(True))

        svc._execute_actions(ctx, [{"type": "click", "selector": "//button", "humanLike": True}])

        assert human_called == [True]

    def test_human_like_false_uses_action_chains(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        ctx, _, chains = _make_context()
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        human_called = []
        monkeypatch.setattr(svc, "_human_like_click", lambda c, e: human_called.append(True))

        svc._execute_actions(ctx, [{"type": "click", "selector": "//button", "humanLike": False}])

        assert not human_called
        chains.click.assert_called_once()

    def test_scrolls_into_view(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        driver = _make_driver()
        ctx, _, _ = _make_context(driver=driver)
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)
        monkeypatch.setattr(svc, "_human_like_click", lambda c, e: None)
        scripts = []
        driver.execute_script.side_effect = lambda s, *_: scripts.append(s)

        svc._execute_actions(ctx, [{"type": "click", "selector": "//button", "humanLike": True}])

        assert any("scrollIntoView" in s for s in scripts)

    def test_uses_xpath_locator(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc
        from selenium.webdriver.common.by import By

        ctx, _, chains = _make_context()
        monkeypatch.setattr(svc.time, "sleep", lambda _: None)

        svc._execute_actions(ctx, [{"type": "click", "selector": "//form//button"}])

        assert ctx.wait_for_presence.call_args[0][0] == By.XPATH
        assert ctx.wait_for_presence.call_args[0][1] == "//form//button"


# ── wait_for ──────────────────────────────────────────────────────────────────

class TestWaitForAction:
    def test_waits_for_element_visibility(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        ctx, _, _ = _make_context()

        svc._execute_actions(ctx, [{"type": "wait_for", "selector": "//div[@id='result']"}])

        ctx.wait_for_visibility.assert_called_once()

    def test_uses_xpath_locator(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc
        from selenium.webdriver.common.by import By

        ctx, _, _ = _make_context()

        svc._execute_actions(ctx, [{"type": "wait_for", "selector": "//div[@id='done']"}])

        assert ctx.wait_for_visibility.call_args[0][0] == By.XPATH
        assert ctx.wait_for_visibility.call_args[0][1] == "//div[@id='done']"

    def test_uses_visibility_not_presence(self, monkeypatch):
        """wait_for must use wait_for_visibility, not wait_for_presence."""
        from flaresolverr import flaresolverr_service as svc

        ctx, _, _ = _make_context()

        svc._execute_actions(ctx, [{"type": "wait_for", "selector": "//span"}])

        ctx.wait_for_visibility.assert_called_once()
        ctx.wait_for_presence.assert_not_called()


# ── wait ──────────────────────────────────────────────────────────────────────

class TestWaitAction:
    def test_sleeps_given_seconds(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        slept = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: slept.append(s))

        svc._execute_actions(MagicMock(), [{"type": "wait", "seconds": 3}])

        assert slept == [3.0]

    def test_defaults_to_one_second(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        slept = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: slept.append(s))

        svc._execute_actions(MagicMock(), [{"type": "wait"}])

        assert slept == [1.0]

    def test_accepts_float(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        slept = []
        monkeypatch.setattr(svc.time, "sleep", lambda s: slept.append(s))

        svc._execute_actions(MagicMock(), [{"type": "wait", "seconds": 0.5}])

        assert slept == [0.5]


# ── edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_unknown_type_logs_warning(self, monkeypatch, caplog):
        from flaresolverr import flaresolverr_service as svc
        import logging

        with caplog.at_level(logging.WARNING):
            svc._execute_actions(MagicMock(), [{"type": "hover"}])

        assert "hover" in caplog.text

    def test_empty_list_is_noop(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        ctx, _, _ = _make_context()

        svc._execute_actions(ctx, [])

        ctx.execute_script.assert_not_called()

    def test_multiple_actions_execute_in_order(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

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
        from flaresolverr import flaresolverr_service as svc

        driver = _make_driver()
        ctx = svc.get_browser_context(driver)
        called_with = []
        monkeypatch.setattr(svc, "_execute_actions", lambda c, a: called_with.append(a))
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "Chrome/1")

        actions = [{"type": "wait", "seconds": 1}]
        req = V1RequestBase({"cmd": "request.get", "url": "https://x.com", "actions": actions})

        svc._build_challenge_result(req, ctx, None)

        assert called_with == [actions]

    def test_actions_not_invoked_when_absent(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        driver = _make_driver()
        ctx = svc.get_browser_context(driver)
        called = []
        monkeypatch.setattr(svc, "_execute_actions", lambda c, a: called.append(True))
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "Chrome/1")

        req = V1RequestBase({"cmd": "request.get", "url": "https://x.com"})
        svc._build_challenge_result(req, ctx, None)

        assert called == []

    def test_actions_not_invoked_with_return_only_cookies(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        driver = _make_driver()
        ctx = svc.get_browser_context(driver)
        called = []
        monkeypatch.setattr(svc, "_execute_actions", lambda c, a: called.append(True))
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "Chrome/1")

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "returnOnlyCookies": True,
            "actions": [{"type": "wait", "seconds": 1}],
        })
        svc._build_challenge_result(req, ctx, None)

        assert called == []

    def test_actions_run_before_page_source_capture(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        driver = _make_driver()
        ctx = svc.get_browser_context(driver)
        sequence = []

        def fake_actions(c, a):
            sequence.append("actions")

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
        svc._build_challenge_result(req, ctx, None)

        assert sequence.index("actions") < sequence.index("page_source")

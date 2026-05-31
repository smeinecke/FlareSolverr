"""Unit tests for JavaScript injection features (issue #38).

Covers the _apply_js_injection helper and the extended eval action
(returnResult flag).
"""

from unittest.mock import MagicMock

from flaresolverr import flaresolverr_service as svc
from flaresolverr.dtos import V1RequestBase


# ── _apply_js_injection ─────────────────────────────────────────────────────


class TestApplyJsInjection:
    def test_disabled_by_default_warns_when_fields_present(self, monkeypatch, caplog):
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: False)
        driver = MagicMock()
        req = V1RequestBase({"cmd": "request.get", "url": "https://x.com", "scriptInject": [{"script": "1+1"}]})

        import logging

        with caplog.at_level(logging.WARNING):
            svc._apply_js_injection(req, driver, "document_start")

        assert "JS_INJECTION_ENABLED" in caplog.text
        driver.execute_cdp_cmd.assert_not_called()
        driver.execute_script.assert_not_called()

    def test_empty_script_is_noop(self, monkeypatch):
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: True)
        driver = MagicMock()
        req = V1RequestBase({"cmd": "request.get", "url": "https://x.com"})

        svc._apply_js_injection(req, driver, "document_start")
        driver.execute_cdp_cmd.assert_not_called()

    def test_document_start_uses_cdp(self, monkeypatch):
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: True)
        driver = MagicMock()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "scriptInject": [{"script": "window.foo = 1;", "point": "document_start"}],
        })

        svc._apply_js_injection(req, driver, "document_start")
        driver.execute_cdp_cmd.assert_called_once_with(
            "Page.addScriptToEvaluateOnNewDocument", {"source": "window.foo = 1;"}
        )
        driver.execute_script.assert_not_called()

    def test_document_end_uses_execute_script(self, monkeypatch):
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: True)
        driver = MagicMock()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "scriptInject": [{"script": "window.foo = 2;", "point": "document_end"}],
        })

        svc._apply_js_injection(req, driver, "document_end")
        driver.execute_script.assert_called_once_with("window.foo = 2;")
        driver.execute_cdp_cmd.assert_not_called()

    def test_document_idle_uses_execute_script(self, monkeypatch):
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: True)
        driver = MagicMock()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "scriptInject": [{"script": "window.foo = 3;"}],  # default point is document_idle
        })

        svc._apply_js_injection(req, driver, "document_idle")
        driver.execute_script.assert_called_once_with("window.foo = 3;")

    def test_wrong_point_is_noop(self, monkeypatch):
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: True)
        driver = MagicMock()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "scriptInject": [{"script": "window.foo = 1;", "point": "document_idle"}],
        })

        svc._apply_js_injection(req, driver, "document_start")
        driver.execute_cdp_cmd.assert_not_called()
        driver.execute_script.assert_not_called()

    def test_cdp_failure_is_logged_not_fatal(self, monkeypatch, caplog):
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: True)
        driver = MagicMock()
        driver.execute_cdp_cmd.side_effect = RuntimeError("cdp err")
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "scriptInject": [{"script": "1", "point": "document_start"}],
        })

        import logging

        with caplog.at_level(logging.WARNING):
            svc._apply_js_injection(req, driver, "document_start")

        assert "cdp err" in caplog.text

    def test_multiple_injections_same_point(self, monkeypatch):
        """Multiple scripts for the same point are injected in order."""
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: True)
        driver = MagicMock()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "scriptInject": [
                {"script": "window.a = 1;", "point": "document_idle"},
                {"script": "window.b = 2;", "point": "document_idle"},
            ],
        })

        svc._apply_js_injection(req, driver, "document_idle")
        assert driver.execute_script.call_count == 2
        assert driver.execute_script.call_args_list == [
            (("window.a = 1;",),),
            (("window.b = 2;",),),
        ]

    def test_multiple_injections_different_points(self, monkeypatch):
        """Only scripts matching the current point are injected."""
        monkeypatch.setattr(svc.utils, "get_config_js_injection_enabled", lambda: True)
        driver = MagicMock()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "scriptInject": [
                {"script": "window.start = 1;", "point": "document_start"},
                {"script": "window.idle = 2;", "point": "document_idle"},
            ],
        })

        svc._apply_js_injection(req, driver, "document_start")
        driver.execute_cdp_cmd.assert_called_once()
        driver.execute_script.assert_not_called()

        driver.reset_mock()
        svc._apply_js_injection(req, driver, "document_idle")
        driver.execute_script.assert_called_once_with("window.idle = 2;")
        driver.execute_cdp_cmd.assert_not_called()


# ── eval action with returnResult ────────────────────────────────────────────


class TestEvalReturnResult:
    def test_default_captures_result(self, monkeypatch):
        driver = MagicMock()
        driver.execute_script.return_value = "captured"
        results = svc._execute_actions(driver, [{"type": "eval", "script": "return 1"}])
        assert results == ["captured"]

    def test_return_result_false_appends_none(self, monkeypatch):
        driver = MagicMock()
        driver.execute_script.return_value = "ignored"
        results = svc._execute_actions(driver, [{"type": "eval", "script": "return 1", "returnResult": False}])
        assert results == [None]

    def test_return_result_true_captures_result(self, monkeypatch):
        driver = MagicMock()
        driver.execute_script.return_value = "captured"
        results = svc._execute_actions(driver, [{"type": "eval", "script": "return 1", "returnResult": True}])
        assert results == ["captured"]


# ── client library ───────────────────────────────────────────────────────────


class TestClientJsInjectionParams:
    def test_build_payload_includes_script_inject(self):
        from flaresolverr.client.client import _RequestManager, FlareSolverrClient

        mgr = _RequestManager(FlareSolverrClient())
        payload = mgr._build_payload(
            cmd="request.get",
            url="https://x.com",
            script_inject=[{"script": "window.x = 1;", "point": "document_start"}],
        )
        assert payload["scriptInject"] == [{"script": "window.x = 1;", "point": "document_start"}]

    def test_build_payload_omits_when_none(self):
        from flaresolverr.client.client import _RequestManager, FlareSolverrClient

        mgr = _RequestManager(FlareSolverrClient())
        payload = mgr._build_payload(cmd="request.get", url="https://x.com")
        assert "scriptInject" not in payload


class TestClientEvalAction:
    def test_eval_action_with_return_result_false(self):
        from flaresolverr.client.actions import ActionQueue

        actions = ActionQueue().eval("return 1", return_result=False).build()
        assert actions == [{"type": "eval", "script": "return 1", "returnResult": False}]

    def test_eval_action_default_does_not_emit_returnResult(self):
        from flaresolverr.client.actions import ActionQueue

        actions = ActionQueue().eval("return 1").build()
        assert actions == [{"type": "eval", "script": "return 1"}]


# ── integration with _build_challenge_result ─────────────────────────────────


class TestBuildChallengeResultEvalIntegration:
    def test_eval_with_returnResult_false_skips_from_evalResult(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc
        from flaresolverr.dtos import V1RequestBase

        driver = MagicMock()
        driver.page_source = "<html></html>"
        driver.get_cookies.return_value = []
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "UA")

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "actions": [{"type": "eval", "script": "return 42", "returnResult": False}],
        })
        result = svc._build_challenge_result(req, driver, None)
        # evalResult should be absent because the only eval returned None
        assert not hasattr(result, "evalResult") or result.evalResult is None

    def test_eval_with_returnResult_true_includes_in_evalResult(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc
        from flaresolverr.dtos import V1RequestBase

        driver = MagicMock()
        driver.page_source = "<html></html>"
        driver.get_cookies.return_value = []
        driver.execute_script.return_value = 42
        monkeypatch.setattr(svc.utils, "get_user_agent", lambda _: "UA")

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://x.com",
            "actions": [{"type": "eval", "script": "return 42", "returnResult": True}],
        })
        result = svc._build_challenge_result(req, driver, None)
        assert result.evalResult == 42


# ── evil_logic injection point integration ───────────────────────────────────


class TestEvilLogicInjectionPoints:
    def test_document_start_called_before_navigate(self, monkeypatch):
        from flaresolverr import flaresolverr_service as svc

        injected_points = []
        orig_apply = svc._apply_js_injection

        def _capture(req, driver, point):
            injected_points.append(point)

        monkeypatch.setattr(svc, "_apply_js_injection", _capture)
        monkeypatch.setattr(svc, "_configure_blocked_media", lambda _req, _d: None)
        monkeypatch.setattr(svc, "_set_custom_headers", lambda _req, _d: None)
        monkeypatch.setattr(svc, "_navigate_request", lambda _req, _d, _m, _u: None)
        monkeypatch.setattr(svc, "_set_request_cookies", lambda _req, _d, _m, _u: None)
        monkeypatch.setattr(svc.utils, "get_config_log_html", lambda: False)
        monkeypatch.setattr(svc, "_raise_if_navigation_error", lambda _d: None)
        monkeypatch.setattr(svc, "_raise_if_access_denied", lambda _d, _t: None)
        monkeypatch.setattr(svc.SERVICE_MANAGER, "detect", lambda _d, _s: None)
        monkeypatch.setattr(svc, "_build_challenge_result", lambda _req, _d, _t: MagicMock())

        req = V1RequestBase({"cmd": "request.get", "url": "https://x.com"})
        svc._evil_logic(req, MagicMock(), "GET", ["cloudflare"])

        assert injected_points == ["document_start", "document_end", "document_idle"]

    def test_document_end_after_page_title(self, monkeypatch):
        # Verify that _apply_js_injection("document_end") is called after driver.title
        from flaresolverr import flaresolverr_service as svc

        sequence = []
        orig_title = MagicMock()
        orig_title.return_value = "test"

        class TrackedDriver(MagicMock):
            @property
            def title(self):
                sequence.append("title")
                return "test"

        driver = TrackedDriver()
        monkeypatch.setattr(svc, "_apply_js_injection", lambda _req, _d, point: sequence.append(point))
        monkeypatch.setattr(svc, "_configure_blocked_media", lambda _req, _d: None)
        monkeypatch.setattr(svc, "_set_custom_headers", lambda _req, _d: None)
        monkeypatch.setattr(svc, "_navigate_request", lambda _req, _d, _m, _u: None)
        monkeypatch.setattr(svc, "_set_request_cookies", lambda _req, _d, _m, _u: None)
        monkeypatch.setattr(svc.utils, "get_config_log_html", lambda: False)
        monkeypatch.setattr(svc, "_raise_if_navigation_error", lambda _d: None)
        monkeypatch.setattr(svc, "_raise_if_access_denied", lambda _d, _t: None)
        monkeypatch.setattr(svc.SERVICE_MANAGER, "detect", lambda _d, _s: None)
        monkeypatch.setattr(svc, "_build_challenge_result", lambda _req, _d, _t: MagicMock())

        req = V1RequestBase({"cmd": "request.get", "url": "https://x.com"})
        svc._evil_logic(req, driver, "GET", ["cloudflare"])

        assert sequence.index("title") < sequence.index("document_end")
        assert sequence.index("document_end") < sequence.index("document_idle")

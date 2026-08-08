"""Integration tests for JavaScript injection features (issue #38).

These tests require a running FlareSolverr instance.
Tests that actually verify injection behaviour are skipped when
JS_INJECTION_ENABLED is not set to true on the server.
"""

import os
import unittest

import pytest
import requests

from flaresolverr.dtos import V1ResponseBase, STATUS_OK, STATUS_ERROR

import time

pytestmark = pytest.mark.integration


class TestJsInjection(unittest.TestCase):
    base_url = None
    httpbin_url = os.environ.get("HTTPBIN_URL", "http://127.0.0.1:8080")
    _js_injection_enabled = None  # cached server-side capability

    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191")
        for i in range(30):
            try:
                requests.get(f"{cls.base_url}/", timeout=5)
                break
            except requests.exceptions.ConnectionError:
                if i == 29:
                    raise
                time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        try:
            res = requests.post(f"{cls.base_url}/v1", json={"cmd": "sessions.list"}, timeout=10)
            body = res.json()
            for sid in body.get("sessions", []):
                requests.post(f"{cls.base_url}/v1", json={"cmd": "sessions.destroy", "session": sid}, timeout=10)
        except Exception:
            pass

    def _request(self, payload, status=None, timeout=60):
        res = requests.post(f"{self.base_url}/v1", json=payload, timeout=timeout)
        if status is not None:
            self.assertEqual(res.status_code, status)
        return res

    def _is_js_injection_enabled(self):
        """Probe the server to find out whether JS injection is enabled."""
        if self.__class__._js_injection_enabled is not None:
            return self.__class__._js_injection_enabled

        res = requests.post(
            f"{self.base_url}/v1",
            json={
                "cmd": "request.get",
                "url": f"{self.httpbin_url}/html",
                "scriptInject": [{"script": "window.__fs_probe = 'enabled';"}],
                "actions": [{"type": "eval", "script": "return window.__fs_probe"}],
            },
            timeout=60,
        )
        if res.status_code != 200:
            self.__class__._js_injection_enabled = False
            return False

        body = res.json()
        eval_result = body.get("solution", {}).get("evalResult")
        enabled = eval_result == "enabled"
        self.__class__._js_injection_enabled = enabled
        return enabled

    # ── eval action extensions ──────────────────────────────────────────────

    def test_eval_action_return_result_true(self):
        """eval action with returnResult:true (default) captures result."""
        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "actions": [{"type": "eval", "script": "return document.title", "returnResult": True}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertIsNotNone(body.solution.evalResult)
        self.assertIsInstance(body.solution.evalResult, str)

    def test_eval_action_return_result_false(self):
        """eval action with returnResult:false does not capture result."""
        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "actions": [{"type": "eval", "script": "return 'should-not-appear'", "returnResult": False}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        # When all eval actions return None, evalResult should be absent
        eval_result = getattr(body.solution, "evalResult", None)
        self.assertIsNone(eval_result)

    def test_eval_action_default_returns_result(self):
        """eval action without explicit returnResult defaults to capturing."""
        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "actions": [{"type": "eval", "script": "return 'captured'"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual(body.solution.evalResult, "captured")

    # ── jsInjection disabled by default ─────────────────────────────────────

    def test_js_injection_disabled_ignored_fields(self):
        """When JS_INJECTION_ENABLED is false, scriptInject fields are ignored."""
        if self._is_js_injection_enabled():
            self.skipTest("JS injection is enabled on this server; cannot test disabled behaviour.")

        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "scriptInject": [{"script": "document.title = 'HACKED';"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertNotIn("HACKED", body.solution.title or "")

    # ── jsInjection lifecycle points (enabled) ─────────────────────────────

    def test_js_injection_document_idle(self):
        """document_idle injection runs after challenge resolution."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "scriptInject": [{"script": "window.__fs_idle = 'idle-ok';", "point": "document_idle"}],
            "actions": [{"type": "eval", "script": "return window.__fs_idle"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual(body.solution.evalResult, "idle-ok")

    def test_js_injection_document_end(self):
        """document_end injection runs after DOM ready, before challenge detection."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "scriptInject": [{"script": "window.__fs_end = 'end-ok';", "point": "document_end"}],
            "actions": [{"type": "eval", "script": "return window.__fs_end"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual(body.solution.evalResult, "end-ok")

    def test_js_injection_document_start(self):
        """document_start injection runs before page load via CDP."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "scriptInject": [{"script": "window.__fs_start = 'start-ok';", "point": "document_start"}],
            "actions": [{"type": "eval", "script": "return window.__fs_start"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual(body.solution.evalResult, "start-ok")

    def test_js_injection_default_point_is_idle(self):
        """When point is omitted, it defaults to document_idle."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "scriptInject": [{"script": "window.__fs_default = 'default-ok';"}],
            "actions": [{"type": "eval", "script": "return window.__fs_default"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual(body.solution.evalResult, "default-ok")

    def test_js_injection_with_session(self):
        """scriptInject works when using a persistent session."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        # Create session
        r1 = self._request({"cmd": "sessions.create", "session": "test_js_inject_session"})
        self.assertEqual(r1.status_code, 200)

        # First request with injection
        r2 = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "session": "test_js_inject_session",
            "scriptInject": [{"script": "window.__fs_sess = 'session-ok';", "point": "document_idle"}],
        })
        self.assertEqual(r2.status_code, 200)

        # Verify via sessions.eval
        r3 = self._request({
            "cmd": "sessions.eval",
            "session": "test_js_inject_session",
            "script": "return window.__fs_sess",
        })
        self.assertEqual(r3.status_code, 200)
        body = V1ResponseBase(r3.json())
        self.assertEqual(body.solution.evalResult, "session-ok")

    def test_js_injection_combined_with_actions(self):
        """scriptInject and actions can be used together in the same request."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "scriptInject": [{"script": "window.__fs_combo = 42;", "point": "document_idle"}],
            "actions": [
                {"type": "wait", "seconds": 1},
                {"type": "eval", "script": "return window.__fs_combo + 1"},
            ],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        # evalResult should be 43 (42 + 1)
        self.assertEqual(body.solution.evalResult, 43)

    def test_js_injection_does_not_break_on_challenge_pages(self):
        """scriptInject should not interfere with normal challenge resolution."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        # Use Google which has no challenge - just verify the request succeeds
        res = self._request({
            "cmd": "request.get",
            "url": "https://www.google.com",
            "scriptInject": [{"script": "window.__fs_google = 1;", "point": "document_idle"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn("Google", body.solution.title)

    def test_js_injection_empty_script_is_noop(self):
        """An empty scriptInject script should be a no-op."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "scriptInject": [{"script": "", "point": "document_idle"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)

    def test_js_injection_post_request(self):
        """scriptInject also works with request.post."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        res = self._request({
            "cmd": "request.post",
            "url": f"{self.httpbin_url}/post",
            "postData": "foo=bar",
            "scriptInject": [{"script": "window.__fs_post = 'post-ok';", "point": "document_idle"}],
            "actions": [{"type": "eval", "script": "return window.__fs_post"}],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual(body.solution.evalResult, "post-ok")

    def test_js_injection_multiple_points_one_request(self):
        """Multiple scripts at different points in a single request."""
        if not self._is_js_injection_enabled():
            self.skipTest("JS injection not enabled on this server.")

        res = self._request({
            "cmd": "request.get",
            "url": f"{self.httpbin_url}/html",
            "scriptInject": [
                {"script": "window.__fs_a = 'start';", "point": "document_start"},
                {"script": "window.__fs_b = 'idle';", "point": "document_idle"},
            ],
            "actions": [
                {"type": "eval", "script": "return [window.__fs_a, window.__fs_b]"},
            ],
        })
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        # Both injections should have run
        result = body.solution.evalResult
        self.assertIn("start", result)
        self.assertIn("idle", result)

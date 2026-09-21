"""Unit tests for failure-evidence capture and classification."""

import json

from flaresolverr import utils
from flaresolverr import flaresolverr_service as service


def _perf_entry(method: str, params: dict) -> dict:
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


class MockPerfDriver:
    def __init__(self, entries):
        self._entries = entries
        self.current_url = "https://example.com/page"
        self.title = "Just a moment..."

    def get_log(self, log_type):
        assert log_type == "performance"
        entries, self._entries = self._entries, []
        return entries

    def execute_script(self, script, *args):
        return 1

    def get_cookies(self):
        return [
            {"name": "cf_clearance", "value": "SECRET", "domain": ".example.com", "expiry": 999},
            {"name": "session", "value": "SECRET2", "domain": "example.com"},
        ]

    @property
    def capabilities(self):
        return {"browserName": "chrome", "browserVersion": "151.0.0.0", "chrome": {"chromedriverVersion": "151.0.0.0"}}

    def get_screenshot_as_base64(self):
        return "QUJD"


class TestDocumentResponseEvidence:
    def test_extracts_status_and_cf_headers(self):
        entries = [
            _perf_entry("Network.requestWillBeSent", {"requestId": "1", "type": "Document", "request": {"url": "https://example.com/page"}}),
            _perf_entry(
                "Network.responseReceived",
                {
                    "requestId": "1",
                    "type": "Document",
                    "response": {
                        "url": "https://example.com/page",
                        "status": 403,
                        "statusText": "Forbidden",
                        "mimeType": "text/html",
                        "protocol": "h2",
                        "headers": {"cf-mitigated": "challenge", "cf-ray": "abc123-FRA", "content-type": "text/html"},
                    },
                },
            ),
        ]
        evidence = utils.get_document_response_evidence(MockPerfDriver(entries))
        assert evidence["status"] == 403
        assert evidence["cfMitigated"] == "challenge"
        assert evidence["cfRay"] == "abc123-FRA"
        assert evidence["mimeType"] == "text/html"
        assert evidence["redirects"] == []

    def test_redirect_chain_tracked_on_same_request_id(self):
        entries = [
            _perf_entry("Network.requestWillBeSent", {"requestId": "1", "type": "Document", "request": {"url": "https://example.com/a"}}),
            _perf_entry(
                "Network.requestWillBeSent",
                {
                    "requestId": "1",
                    "type": "Document",
                    "request": {"url": "https://example.com/b"},
                    "redirectResponse": {"url": "https://example.com/a", "status": 301},
                },
            ),
            _perf_entry(
                "Network.responseReceived",
                {"requestId": "1", "type": "Document", "response": {"url": "https://example.com/b", "status": 200, "headers": {}}},
            ),
        ]
        evidence = utils.get_document_response_evidence(MockPerfDriver(entries))
        assert evidence["url"] == "https://example.com/b"
        assert evidence["status"] == 200
        assert evidence["redirects"] == [{"url": "https://example.com/a", "status": 301}]

    def test_last_document_wins_over_earlier_navigation(self):
        entries = [
            _perf_entry("Network.requestWillBeSent", {"requestId": "1", "type": "Document", "request": {"url": "https://example.com/"}}),
            _perf_entry("Network.responseReceived", {"requestId": "1", "response": {"url": "https://example.com/", "status": 200, "headers": {}}}),
            _perf_entry("Network.requestWillBeSent", {"requestId": "2", "type": "Document", "request": {"url": "https://example.com/api"}}),
            _perf_entry(
                "Network.responseReceived",
                {
                    "requestId": "2",
                    "response": {"url": "https://example.com/api", "status": 403, "headers": {"CF-Mitigated": "challenge"}},
                },
            ),
        ]
        evidence = utils.get_document_response_evidence(MockPerfDriver(entries))
        assert evidence["status"] == 403
        assert evidence["url"] == "https://example.com/api"
        # Header lookup is case-insensitive.
        assert evidence["cfMitigated"] == "challenge"

    def test_nav_error_and_failed_resources(self):
        entries = [
            _perf_entry("Network.requestWillBeSent", {"requestId": "1", "type": "Document", "request": {"url": "https://dead.example.com/"}}),
            _perf_entry("Network.loadingFailed", {"requestId": "1", "type": "Document", "errorText": "net::ERR_NAME_NOT_RESOLVED"}),
            _perf_entry("Network.requestWillBeSent", {"requestId": "2", "type": "Image", "request": {"url": "https://example.com/x.png"}}),
            _perf_entry("Network.loadingFailed", {"requestId": "2", "errorText": "net::ERR_ABORTED"}),
        ]
        evidence = utils.get_document_response_evidence(MockPerfDriver(entries))
        assert evidence["navError"] == "net::ERR_NAME_NOT_RESOLVED"
        assert {"url": "https://example.com/x.png", "error": "net::ERR_ABORTED"} in evidence["failedResources"]

    def test_no_entries_returns_empty(self):
        assert utils.get_document_response_evidence(MockPerfDriver([])) == {}


class TestCollectFailureEvidence:
    def test_redacts_cookie_values(self):
        evidence = utils.collect_failure_evidence(MockPerfDriver([]))
        assert evidence["cfClearancePresent"] is True
        names = {c["name"] for c in evidence["cookies"]}
        assert names == {"cf_clearance", "session"}
        for c in evidence["cookies"]:
            assert "value" not in c

    def test_captures_browser_and_config(self):
        evidence = utils.collect_failure_evidence(MockPerfDriver([]))
        assert evidence["browser"]["version"] == "151.0.0.0"
        assert evidence["browser"]["chromedriverVersion"] == "151.0.0.0"
        assert evidence["screenshotBase64"] == "QUJD"
        assert "stealthMode" in evidence["config"]
        assert "headless" in evidence["config"]


class TestClassifyFailure:
    def _evidence(self, **kwargs):
        base = {"response": {}, "currentUrl": "https://example.com"}
        base.update(kwargs)
        return base

    def test_browser_crash_when_driver_dead(self):
        class DeadDriver:
            def execute_script(self, *a):
                raise RuntimeError("disconnected")

        assert service._classify_failure(DeadDriver(), "cloudflare", {}) == "browser_crash"

    def test_nav_error(self):
        ev = self._evidence(response={"navError": "net::ERR_FAILED"})
        assert service._classify_failure(MockPerfDriver([]), None, ev) == "nav_error"

    def test_chrome_error_url(self):
        ev = self._evidence(currentUrl="chrome-error://chromewebdata/")
        assert service._classify_failure(MockPerfDriver([]), None, ev) == "nav_error"

    def test_challenge_denied_on_cf_mitigated(self):
        ev = self._evidence(response={"cfMitigated": "challenge"})
        assert service._classify_failure(MockPerfDriver([]), "cloudflare", ev) == "challenge_denied"

    def test_challenge_timeout_when_service_detected(self):
        assert service._classify_failure(MockPerfDriver([]), "cloudflare", self._evidence()) == "challenge_timeout"

    def test_solver_timeout_default(self):
        assert service._classify_failure(MockPerfDriver([]), None, self._evidence()) == "solver_timeout"


class TestRawPostHelpers:
    def test_parse_raw_headers(self):
        parsed = service._parse_raw_headers("content-type: text/html\r\ncf-mitigated: challenge\r\n")
        assert parsed == {"content-type": "text/html", "cf-mitigated": "challenge"}

    def test_parse_raw_headers_non_string(self):
        assert service._parse_raw_headers(None) == {}
        assert service._parse_raw_headers({}) == {}

    def test_looks_like_challenge_html(self):
        assert service._looks_like_challenge_html("<html>window._cf_chl_opt = {}</html>")
        assert service._looks_like_challenge_html("<title>Just a moment...</title>")
        assert not service._looks_like_challenge_html('{"ok": true}')
        assert not service._looks_like_challenge_html(None)

import json
import os
import re
import subprocess
import unittest
from typing import Optional

import pytest
import requests

from flaresolverr.dtos import IndexResponse, HealthResponse, V1ResponseBase, STATUS_OK, STATUS_ERROR
from flaresolverr import utils

import socket
import time
import urllib.parse

pytestmark = pytest.mark.integration


def _find_obj_by_key(key: str, value: str, _list: list) -> Optional[dict]:
    for obj in _list:
        if obj[key] == value:
            return obj
    return None


def _proxy_reachable(proxy_url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(proxy_url)
        if not parsed.hostname or not parsed.port:
            return False
        with socket.create_connection((parsed.hostname, parsed.port), timeout=2):
            return True
    except OSError:
        return False


class TestFlareSolverr(unittest.TestCase):
    # Proxy URLs for tests - can be overridden via env vars
    # *_check_url: host-side address used only to verify the proxy is up before testing
    # proxy_url / proxy_socks_url: address sent to FlareSolverr (may be a Docker service name)
    proxy_url = os.environ.get("PROXY_HTTP_URL", "http://proxy-http:8888")
    proxy_url_2 = os.environ.get("PROXY_HTTP_URL_2", "http://proxy-http-2:8888")
    proxy_socks_url = os.environ.get("PROXY_SOCKS_URL", "socks5://proxy-socks:1080")
    proxy_http_check_url = os.environ.get("PROXY_HTTP_CHECK_URL", "http://127.0.0.1:8888")
    proxy_http_check_url_2 = os.environ.get("PROXY_HTTP_CHECK_URL_2", "http://127.0.0.1:8889")
    proxy_socks_check_url = os.environ.get("PROXY_SOCKS_CHECK_URL", "socks5://127.0.0.1:1080")
    httpbin_url = os.environ.get("HTTPBIN_URL", "http://127.0.0.1:8080")
    google_url = "https://www.google.com"
    are_you_a_bot_url = "https://deviceandbrowserinfo.com/are_you_a_bot"
    are_you_a_bot_interactions_url = "https://deviceandbrowserinfo.com/are_you_a_bot_interactions"
    post_url = f"{httpbin_url}/post"
    cloudflare_url = "https://nowsecure.nl/"
    cloudflare_url_2 = "https://bt4gprx.com/search?q=2022"
    ddos_guard_url = "https://www.anime-loads.org/"
    scrapingcourse_cf_url = "https://www.scrapingcourse.com/cloudflare-challenge"
    scrapingcourse_turnstile_url = "https://www.scrapingcourse.com/login/cf-turnstile"
    scrapingcourse_csrf_url = "https://www.scrapingcourse.com/login/csrf"
    cloudflare_blocked_url = "https://www.cpasbiens3.fr/"
    turnstile_workers_url = "https://browser-compat.turnstile.workers.dev/"

    base_url = None

    # Docker container names for proxy log verification (set by docker-compose.integration.yml)
    proxy_http_container = "flaresolverr-proxy-http-1"
    proxy_http_2_container = "flaresolverr-proxy-http-2-1"

    @staticmethod
    def _get_docker_log_line_count(container: str) -> int:
        """Return current line count of docker logs for container."""
        try:
            result = subprocess.run(
                ["docker", "logs", container],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return len((result.stdout + result.stderr).splitlines())
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return 0

    @staticmethod
    def _get_docker_logs_after(container: str, line_count: int) -> str:
        """Return docker logs for container after a given line count."""
        try:
            result = subprocess.run(
                ["docker", "logs", container],
                capture_output=True,
                text=True,
                timeout=5,
            )
            logs = result.stdout + result.stderr
            lines = logs.splitlines()
            return "\n".join(lines[line_count:])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    @classmethod
    def _assert_request_routed_through_proxy(cls, container: str, line_count: int, hostname: str) -> None:
        """Assert that a request to hostname was routed through the given proxy container."""
        for _ in range(10):
            logs = cls._get_docker_logs_after(container, line_count)
            if hostname in logs:
                return
            time.sleep(0.5)
        logs = cls._get_docker_logs_after(container, line_count)
        assert hostname in logs, f"Expected request to {hostname} in {container} logs, got:\n{logs}"

    @classmethod
    def _assert_request_not_routed_through_proxy(cls, container: str, line_count: int, hostname: str) -> None:
        """Assert that a request to hostname was NOT routed through the given proxy container."""
        time.sleep(2)
        logs = cls._get_docker_logs_after(container, line_count)
        assert hostname not in logs, f"Expected NO request to {hostname} in {container} logs, but found:\n{logs}"

    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191")
        # wait until the server is ready
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
        # Destroy any lingering sessions so Chrome processes don't leak.
        try:
            res = requests.post(f"{cls.base_url}/v1", json={"cmd": "sessions.list"}, timeout=10)
            body = res.json()
            for sid in body.get("sessions", []):
                requests.post(f"{cls.base_url}/v1", json={"cmd": "sessions.destroy", "session": sid}, timeout=10)
        except Exception:
            pass

    def _request(self, method: str, path: str, json=None, status=None, timeout=180, params=None):
        url = f"{self.base_url}{path}"
        if method == "GET":
            res = requests.get(url, params=params, timeout=timeout)
        elif method == "POST":
            res = requests.post(url, json=json, timeout=timeout)
        else:
            raise ValueError(f"Unsupported method: {method}")
        if status is not None:
            self.assertEqual(res.status_code, status)
        return res

    def _get_json(self, res):
        return res.json()

    def _assert_challenge_status_ok(self, message: str):
        self.assertIn(message, {"Challenge solved!", "Challenge not detected!"})

    def test_wrong_endpoint(self):
        res = self._request("GET", "/wrong", status=404)
        self.assertEqual(res.status_code, 404)

        body = self._get_json(res)
        self.assertEqual("Not found: '/wrong'", body["error"])
        self.assertEqual(404, body["status_code"])

    def test_index_endpoint(self):
        res = self._request("GET", "/")
        self.assertEqual(res.status_code, 200)

        body = IndexResponse(self._get_json(res))
        self.assertEqual("FlareSolverr is ready!", body.msg)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)
        self.assertIn("Chrome/", body.userAgent)

    def test_health_endpoint(self):
        res = self._request("GET", "/health")
        self.assertEqual(res.status_code, 200)

        body = HealthResponse(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIsInstance(body.sessionsCount, int)
        self.assertIsInstance(body.activeParallelRequests, int)
        self.assertIsInstance(body.config, dict)
        self.assertIn("logLevel", body.config)
        self.assertIn("headless", body.config)
        self.assertIsNone(body.activeRequests)
        self.assertIsNone(body.sessions)

    def test_health_endpoint_with_details(self):
        res = self._request("GET", "/health", params={"details": "true"})
        self.assertEqual(res.status_code, 200)

        body = HealthResponse(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIsInstance(body.sessionsCount, int)
        self.assertIsInstance(body.activeParallelRequests, int)
        self.assertIsInstance(body.activeRequests, list)
        self.assertIsInstance(body.sessions, list)
        self.assertIsInstance(body.config, dict)

    def test_v1_endpoint_wrong_cmd(self):
        res = self._request("POST", "/v1", {"cmd": "request.bad", "url": self.google_url}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertEqual("Error: Request parameter 'cmd' = 'request.bad' is invalid.", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

    def test_v1_endpoint_request_get_no_cloudflare(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.google_url})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.google_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Google</title>", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    def test_v1_endpoint_request_get_are_you_a_bot_reports_result(self):
        res = self._request(
            "POST",
            "/v1",
            {"cmd": "request.get", "url": self.are_you_a_bot_url, "waitInSeconds": 3, "stealth": True},
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.are_you_a_bot_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Bot detection test: verify if your bot is detected</title>", solution.response)
        # Bot detection signals must all be clean
        self.assertRegex(solution.response, re.compile(r'"hasBotUserAgent"\s*:\s*false'))
        self.assertRegex(solution.response, re.compile(r'"isBot"\s*:\s*false'))
        self.assertRegex(solution.response, re.compile(r'"hasWebdriverTrue"\s*:\s*false'))
        self.assertRegex(solution.response, re.compile(r'"hasInconsistentWorkerValues"\s*:\s*false'))
        self.assertIn("You are human!", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    def test_v1_endpoint_request_get_are_you_a_bot_interactions_page_content(self):
        backend = os.environ.get("DRIVER_BACKEND", "undetected_chromedriver").strip().lower()
        if backend != "custom_chromium" and not utils._is_custom_chromium():
            self.skipTest(
                "Behavioral action detection requires patched Chromium; skipping on standard Chrome."
            )
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "url": self.are_you_a_bot_interactions_url,
                "stealth": True,
                "actions": [
                    {"type": "wait", "seconds": 2},
                    {"type": "fill", "selector": "//input[@id='email']", "value": "test@example.com"},
                    {"type": "fill", "selector": "//input[@id='password']", "value": "TestPass@123"},
                    {"type": "click", "selector": "//form[@id='loginForm']//button[@type='submit']"},
                    {"type": "wait_for", "selector": "//*[contains(text(),'You are human!') or contains(text(),'You are a bot!')]"},
                ],
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.are_you_a_bot_interactions_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Bot detection test: verify if your bot is detected</title>", solution.response)
        self.assertIn('id="loginForm"', solution.response)
        # Fingerprint signals should be clean
        self.assertRegex(solution.response, re.compile(r'"hasBotUserAgent"\s*:\s*false'))
        self.assertRegex(solution.response, re.compile(r'"hasWebdriverTrue"\s*:\s*false'))
        self.assertRegex(solution.response, re.compile(r'"hasInconsistentWorkerValues"\s*:\s*false'))
        # With --enable-trusted-synthetic-events C++ patch, CDP actions should not trigger behavioral detection
        self.assertRegex(solution.response, re.compile(r'"suspiciousClientSideBehavior"\s*:\s*false'))
        self.assertRegex(solution.response, re.compile(r'"isBot"\s*:\s*false'))
        self.assertIn("You are human!", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    def test_v1_endpoint_request_get_disable_resources(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.google_url, "disableMedia": True})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.google_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Google</title>", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    def test_v1_endpoint_request_get_cloudflare_js_1(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.cloudflare_url, "maxTimeout": 120000})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self._assert_challenge_status_ok(body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.cloudflare_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertRegex(solution.response, re.compile(r"<title>nowsecure\.nl</title>|<title>nowSecure</title>", re.IGNORECASE))
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

        cf_cookie = _find_obj_by_key("name", "cf_clearance", solution.cookies)
        self.assertIsNotNone(cf_cookie, "Cloudflare cookie not found")
        self.assertGreater(len(cf_cookie["value"]), 30)

    def test_v1_endpoint_request_get_cloudflare_js_2(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.cloudflare_url_2, "maxTimeout": 40000}, timeout=60)
        if res.status_code == 500:
            body = V1ResponseBase(self._get_json(res))
            if "Timeout after" in body.message:
                self.skipTest(f"Target site challenge timed out: {body.message}")
            if "Cloudflare hard block" in body.message:
                self.skipTest(f"Target site returned Cloudflare hard-block page: {body.message}")
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)

        # bt4gprx.com can return a Cloudflare hard-block page instead of a challenge
        if body.solution and "Incompatible browser extension or network configuration" in body.solution.response:
            self.skipTest("Target site returned Cloudflare hard-block page (site-specific anti-bot policy).")

        self._assert_challenge_status_ok(body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.cloudflare_url_2, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Download 2022 Torrents - BT4G</title>", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

        cf_cookie = _find_obj_by_key("name", "cf_clearance", solution.cookies)
        self.assertIsNotNone(cf_cookie, "Cloudflare cookie not found")
        self.assertGreater(len(cf_cookie["value"]), 30)

    def test_v1_endpoint_request_get_ddos_guard_js(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.ddos_guard_url})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self._assert_challenge_status_ok(body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.ddos_guard_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertRegex(solution.response, re.compile(r"ANIME-LOADS.ORG -", re.IGNORECASE))
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

        cf_cookie = _find_obj_by_key("name", "__ddg1_", solution.cookies)
        self.assertIsNotNone(cf_cookie, "DDOS-Guard cookie not found")
        self.assertGreater(len(cf_cookie["value"]), 10)

    def test_v1_endpoint_request_get_scrapingcourse_cf_challenge(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.scrapingcourse_cf_url, "maxTimeout": 120000}, timeout=190)
        if res.status_code == 500:
            body = V1ResponseBase(self._get_json(res))
            if "Timeout after" in body.message:
                self.skipTest(f"Target site challenge timed out: {body.message}")
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self._assert_challenge_status_ok(body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.scrapingcourse_cf_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("Cloudflare Challenge", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

        cf_cookie = _find_obj_by_key("name", "cf_clearance", solution.cookies)
        self.assertIsNotNone(cf_cookie, "Cloudflare cookie not found")
        self.assertGreater(len(cf_cookie["value"]), 30)

    def test_v1_endpoint_request_get_turnstile_challenge(self):
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "url": self.scrapingcourse_turnstile_url,
                "maxTimeout": 120000,
                "tabs_till_verify": 2,
                "actions": [
                    {"type": "wait", "seconds": 2},
                    {"type": "fill", "selector": "//input[@id='email']", "value": "admin@example.com"},
                    {"type": "fill", "selector": "//input[@id='password']", "value": "password"},
                    {"type": "click", "selector": "//button[@id='submit-button']"},
                    {"type": "wait", "seconds": 3},
                ],
            },
            timeout=190,
        )
        if res.status_code == 500:
            body = V1ResponseBase(self._get_json(res))
            if "Timeout after" in body.message:
                self.skipTest(f"Target site challenge timed out: {body.message}")
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self._assert_challenge_status_ok(body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.scrapingcourse_turnstile_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        # After successful login the page should show the success page, not 403
        self.assertNotIn("403", solution.response)
        self.assertNotIn("FORBIDDEN", solution.response)
        self.assertNotIn("Page Expired", solution.response)
        self.assertIn("Success Page", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

        # Turnstile token was solved by FlareSolverr before form submission
        self.assertTrue(solution.turnstile_token, "Turnstile token should be present after captcha solve")

    def test_v1_endpoint_request_get_turnstile_workers(self):
        # Create a session so we can evaluate JS on the loaded page and read
        # the structured testResults JSON instead of scraping HTML.
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_turnstile_workers"})

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "url": self.turnstile_workers_url,
                "maxTimeout": 120000,
                "session": "test_turnstile_workers",
            },
            timeout=190,
        )
        if res.status_code == 500:
            body = V1ResponseBase(self._get_json(res))
            if "Timeout after" in body.message:
                self.skipTest(f"Target site challenge timed out: {body.message}")
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self._assert_challenge_status_ok(body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.turnstile_workers_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)

        # Extract the page's internal testResults JSON via JS evaluation.
        # window.testResults is scoped inside an IIFE, so it is not directly
        # reachable.  However, window.copyFullResults is exposed and reads
        # testResults from its closure.  We monkey-patch
        # navigator.clipboard.writeText to capture the JSON string that the
        # "Copy full results" button would copy to the clipboard.
        eval_res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "sessions.eval",
                "session": "test_turnstile_workers",
                "script": (
                    "var captured = null;"
                    "navigator.clipboard.writeText = function(text) {"
                    "    captured = text;"
                    "    return Promise.resolve();"
                    "};"
                    "window.copyFullResults();"
                    "return captured;"
                ),
            },
        )
        self.assertEqual(eval_res.status_code, 200)
        eval_body = V1ResponseBase(self._get_json(eval_res))
        self.assertEqual(STATUS_OK, eval_body.status)
        self.assertEqual("Script executed successfully.", eval_body.message)
        self.assertIsNotNone(eval_body.solution.evalResult, "copyFullResults did not produce any output")

        test_results = json.loads(eval_body.solution.evalResult)

        # Assert on structured diagnostic data rather than scraping HTML.
        # criticalFailure is null when all checks pass;
        # in an automated browser it is "automated_browser".
        self.assertIsNone(
            test_results.get("testMetadata", {}).get("criticalFailure"),
            f"Turnstile troubleshooting page detected a critical failure: {test_results.get('testMetadata', {}).get('criticalFailure')}",
        )

        for test in test_results.get("tests", []):
            self.assertTrue(
                test.get("passed", False),
                f"Diagnostic test '{test.get('name')}' failed: {test.get('detail')}",
            )

        # Turnstile may or may not have completed depending on timing;
        # only assert token when a challenge was actively solved.
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)
        if body.message == "Challenge solved!":
            self.assertTrue(solution.turnstile_token, "Turnstile token should be present after captcha solve")

    def test_v1_endpoint_request_get_csrf_login(self):
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "url": self.scrapingcourse_csrf_url,
                "maxTimeout": 120000,
                "actions": [
                    {"type": "wait", "seconds": 2},
                    {"type": "fill", "selector": "//input[@id='email']", "value": "admin@example.com"},
                    {"type": "fill", "selector": "//input[@id='password']", "value": "password"},
                    {"type": "click", "selector": "//button[@id='submit-button']"},
                    {"type": "wait", "seconds": 3},
                ],
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self._assert_challenge_status_ok(body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        # Real form submission should not hit Laravel 419 Page Expired
        self.assertNotIn("Page Expired", solution.response)
        self.assertNotIn("419", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    # todo: test Cmd 'request.get' should return fail with Cloudflare CAPTCHA

    @unittest.skip("Blocked-site target cpasbiens3.fr no longer resolves; replace with a live Access denied target.")
    def test_v1_endpoint_request_get_cloudflare_blocked(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.cloudflare_blocked_url}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertEqual(
            "Error: Error solving the challenge. Cloudflare has blocked this request. Probably your IP is banned for this site, check in your web browser.",
            body.message,
        )
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

    def test_v1_endpoint_request_get_cookies_param(self):
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "url": self.google_url,
                "cookies": [{"name": "testcookie1", "value": "testvalue1"}, {"name": "testcookie2", "value": "testvalue2"}],
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.google_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Google</title>", solution.response)
        self.assertGreater(len(solution.cookies), 1)
        self.assertIn("Chrome/", solution.userAgent)

        user_cookie1 = _find_obj_by_key("name", "testcookie1", solution.cookies)
        self.assertIsNotNone(user_cookie1, "User cookie 1 not found")
        self.assertEqual("testvalue1", user_cookie1["value"])

        user_cookie2 = _find_obj_by_key("name", "testcookie2", solution.cookies)
        self.assertIsNotNone(user_cookie2, "User cookie 2 not found")
        self.assertEqual("testvalue2", user_cookie2["value"])

    def test_v1_endpoint_request_get_returnOnlyCookies_param(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.google_url, "returnOnlyCookies": True})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.google_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIsNone(solution.headers)
        self.assertIsNone(solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    def test_v1_endpoint_request_get_proxy_http_param(self):
        if not _proxy_reachable(self.proxy_http_check_url):
            self.skipTest(f"Proxy not reachable: {self.proxy_http_check_url}")
        """
        To configure TinyProxy in local:
           * sudo vim /etc/tinyproxy/tinyproxy.conf
              * edit => LogFile "/tmp/tinyproxy.log"
              * edit => Syslog Off
           * sudo tinyproxy -d
           * sudo tail -f /tmp/tinyproxy.log
        """
        hostname = urllib.parse.urlparse(self.google_url).hostname or self.google_url
        lines_before = self._get_docker_log_line_count(self.proxy_http_container)
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.google_url, "proxy": {"url": self.proxy_url}})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.google_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Google</title>", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)
        self._assert_request_routed_through_proxy(self.proxy_http_container, lines_before, hostname)

    def test_v1_endpoint_request_get_proxy_http_param_with_credentials(self):
        if not _proxy_reachable(self.proxy_http_check_url):
            self.skipTest(f"Proxy not reachable: {self.proxy_http_check_url}")
        """
        To configure TinyProxy in local:
           * sudo vim /etc/tinyproxy/tinyproxy.conf
              * edit => LogFile "/tmp/tinyproxy.log"
              * edit => Syslog Off
              * add => BasicAuth testuser testpass
           * sudo tinyproxy -d
           * sudo tail -f /tmp/tinyproxy.log
        """
        hostname = urllib.parse.urlparse(self.google_url).hostname or self.google_url
        lines_before = self._get_docker_log_line_count(self.proxy_http_container)
        res = self._request(
            "POST", "/v1", {"cmd": "request.get", "url": self.google_url, "proxy": {"url": self.proxy_url, "username": "testuser", "password": "testpass"}}
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.google_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Google</title>", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)
        self._assert_request_routed_through_proxy(self.proxy_http_container, lines_before, hostname)

    def test_v1_endpoint_request_get_proxy_socks_param(self):
        if not _proxy_reachable(self.proxy_socks_check_url):
            self.skipTest(f"Proxy not reachable: {self.proxy_socks_check_url}")
        """
        To configure Dante in local:
           * https://linuxhint.com/set-up-a-socks5-proxy-on-ubuntu-with-dante/
           * sudo vim /etc/sockd.conf
           * sudo systemctl restart sockd.service
           * curl --socks5 socks5://127.0.0.1:1080 https://www.google.com
        """
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.google_url, "proxy": {"url": self.proxy_socks_url}})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.google_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>Google</title>", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    def test_v1_endpoint_request_get_proxy_wrong_param(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.google_url, "proxy": {"url": "http://127.0.0.1:43210"}}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("Error: Error solving the challenge. Proxy 127.0.0.1:43210 is not reachable", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

    def test_v1_endpoint_request_get_fail_timeout(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.google_url, "maxTimeout": 10}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertEqual("Error: Error solving the challenge. Timeout after 0.01 seconds.", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

    def test_v1_endpoint_request_get_fail_bad_domain(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": "https://www.google.combad"}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("Message: unknown error: net::ERR_NAME_NOT_RESOLVED", body.message)

    def test_v1_endpoint_request_get_deprecated_param(self):
        res = self._request("POST", "/v1", {"cmd": "request.get", "url": self.google_url, "userAgent": "Test User-Agent"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)

    def test_v1_endpoint_request_post_no_cloudflare(self):
        res = self._request("POST", "/v1", {"cmd": "request.post", "url": self.post_url, "postData": "param1=value1&param2=value2"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.post_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn('"param1"', solution.response)
        self.assertIn('"value1"', solution.response)
        self.assertIn('"param2"', solution.response)
        self.assertIn('"value2"', solution.response)
        self.assertEqual(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    def test_v1_endpoint_request_post_cloudflare(self):
        res = self._request(
            "POST",
            "/v1",
            {"cmd": "request.post", "url": self.cloudflare_url, "postData": "param1=value1&param2=value2", "maxTimeout": 120000},
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self._assert_challenge_status_ok(body.message)
        self.assertGreater(body.startTimestamp, 10000)
        self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
        self.assertEqual(utils.get_flaresolverr_version(), body.version)

        solution = body.solution
        self.assertIn(self.cloudflare_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIs(len(solution.headers), 0)
        self.assertIn("<title>405 Not Allowed</title>", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

        cf_cookie = _find_obj_by_key("name", "cf_clearance", solution.cookies)
        self.assertIsNotNone(cf_cookie, "Cloudflare cookie not found")
        self.assertGreater(len(cf_cookie["value"]), 30)

    def test_v1_endpoint_request_post_fail_no_post_data(self):
        res = self._request("POST", "/v1", {"cmd": "request.post", "url": self.google_url}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("Request parameter 'postData' or 'postDataRaw' is mandatory in 'request.post' command", body.message)

    def test_v1_endpoint_request_post_deprecated_param(self):
        res = self._request(
            "POST", "/v1", {"cmd": "request.post", "url": self.google_url, "postData": "param1=value1&param2=value2", "userAgent": "Test User-Agent"}
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)

    def test_v1_endpoint_request_post_raw_json_no_cloudflare(self):
        raw_body = '{"key": "value", "num": 42}'
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.post",
                "url": self.post_url,
                "postDataRaw": raw_body,
                "postDataContentType": "application/json",
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)

        solution = body.solution
        self.assertIn(self.post_url, solution.url)
        self.assertEqual(solution.status, 200)
        self.assertIn('"key": "value"', solution.response)
        self.assertIn('"num": 42', solution.response)
        self.assertIn('"Content-Type":', solution.response)
        self.assertIn('"application/json"', solution.response)

    def test_v1_endpoint_request_post_raw_fail_no_body(self):
        res = self._request("POST", "/v1", {"cmd": "request.post", "url": self.google_url}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("Request parameter 'postData' or 'postDataRaw' is mandatory in 'request.post' command", body.message)

    def test_v1_endpoint_request_post_raw_fail_both_bodies(self):
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.post",
                "url": self.google_url,
                "postData": "a=b",
                "postDataRaw": "{}",
            },
            status=500,
        )
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("Cannot use both 'postData' and 'postDataRaw' in the same request", body.message)

    def test_v1_endpoint_sessions_create_without_session(self):
        res = self._request("POST", "/v1", {"cmd": "sessions.create"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Session created successfully.", body.message)
        self.assertIsNotNone(body.session)

    def test_v1_endpoint_sessions_create_with_session(self):
        res = self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_create_session"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Session created successfully.", body.message)
        self.assertEqual(body.session, "test_create_session")

    def test_v1_endpoint_sessions_create_proxy_http_param(self):
        if not _proxy_reachable(self.proxy_http_check_url):
            self.skipTest(f"Proxy not reachable: {self.proxy_http_check_url}")
        res = self._request("POST", "/v1", {"cmd": "sessions.create", "proxy": {"url": self.proxy_url}})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Session created successfully.", body.message)
        self.assertIsNotNone(body.session)

    def test_v1_endpoint_sessions_list(self):
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_list_sessions"})
        res = self._request("POST", "/v1", {"cmd": "sessions.list"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("", body.message)
        self.assertGreaterEqual(len(body.sessions), 1)
        self.assertIn("test_list_sessions", body.sessions)

    def test_v1_endpoint_sessions_destroy_existing_session(self):
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_destroy_sessions"})
        res = self._request("POST", "/v1", {"cmd": "sessions.destroy", "session": "test_destroy_sessions"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("The session has been removed.", body.message)

    def test_v1_endpoint_sessions_destroy_non_existing_session(self):
        res = self._request("POST", "/v1", {"cmd": "sessions.destroy", "session": "non_existing_session_name"}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertEqual("Error: The session doesn't exist.", body.message)

    def test_v1_endpoint_request_get_with_session(self):
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_request_sessions"})
        res = self._request("POST", "/v1", {"cmd": "request.get", "session": "test_request_sessions", "url": self.google_url})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)

    def test_v1_endpoint_sessions_cleanup_idle_timeout(self):
        self._request(
            "POST",
            "/v1",
            {"cmd": "sessions.create", "session": "test_cleanup_idle", "sessionIdleTimeout": 0},
        )
        res = self._request("POST", "/v1", {"cmd": "sessions.cleanup"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn("test_cleanup_idle", body.sessions)

        res = self._request("POST", "/v1", {"cmd": "sessions.list"})
        body = V1ResponseBase(self._get_json(res))
        self.assertNotIn("test_cleanup_idle", body.sessions)

    def test_v1_endpoint_sessions_cleanup_max_runtime(self):
        self._request(
            "POST",
            "/v1",
            {"cmd": "sessions.create", "session": "test_cleanup_runtime", "sessionMaxRuntime": 0},
        )
        res = self._request("POST", "/v1", {"cmd": "sessions.cleanup"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn("test_cleanup_runtime", body.sessions)

        res = self._request("POST", "/v1", {"cmd": "sessions.list"})
        body = V1ResponseBase(self._get_json(res))
        self.assertNotIn("test_cleanup_runtime", body.sessions)

    # ---- Session interaction commands ----

    def test_v1_endpoint_sessions_get(self):
        """sessions.get returns current URL, title, cookies, response, userAgent."""
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_get_session"})
        self._request("POST", "/v1", {"cmd": "request.get", "session": "test_get_session", "url": self.google_url})

        res = self._request("POST", "/v1", {"cmd": "sessions.get", "session": "test_get_session"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Session info retrieved successfully.", body.message)

        solution = body.solution
        self.assertIn(self.google_url, solution.url)
        self.assertIn("Google", solution.title)
        self.assertIn("<title>Google</title>", solution.response)
        self.assertGreater(len(solution.cookies), 0)
        self.assertIn("Chrome/", solution.userAgent)

    def test_v1_endpoint_sessions_get_missing_session(self):
        res = self._request("POST", "/v1", {"cmd": "sessions.get", "session": "missing_session"}, status=500)
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertEqual("Error: The session doesn't exist.", body.message)

    def test_v1_endpoint_sessions_eval(self):
        """sessions.eval executes JS and returns the result."""
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_eval_session"})
        self._request("POST", "/v1", {"cmd": "request.get", "session": "test_eval_session", "url": self.google_url})

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "sessions.eval",
                "session": "test_eval_session",
                "script": "return document.title",
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Script executed successfully.", body.message)
        self.assertIn("Google", body.solution.evalResult)
        self.assertGreater(len(body.solution.cookies), 0)

    def test_v1_endpoint_sessions_eval_missing_script(self):
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_eval_no_script"})
        res = self._request(
            "POST",
            "/v1",
            {"cmd": "sessions.eval", "session": "test_eval_no_script"},
            status=500,
        )
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("'script' is mandatory", body.message)

    def test_v1_endpoint_sessions_network(self):
        """sessions.network returns performance log entries."""
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_network_session"})
        self._request("POST", "/v1", {"cmd": "request.get", "session": "test_network_session", "url": self.google_url})

        res = self._request("POST", "/v1", {"cmd": "sessions.network", "session": "test_network_session"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn("network log entries", body.message)
        self.assertIsInstance(body.solution.networkLogs, list)
        self.assertGreater(len(body.solution.networkLogs), 0)
        # At least one Network.requestWillBeSent entry should exist
        methods = {e.get("method") for e in body.solution.networkLogs}
        self.assertIn("Network.requestWillBeSent", methods)

    def test_v1_endpoint_sessions_click(self):
        """sessions.click clicks an element by XPath."""
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_click_session"})
        self._request("POST", "/v1", {"cmd": "request.get", "session": "test_click_session", "url": self.google_url})

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "sessions.click",
                "session": "test_click_session",
                "selector": "//a[contains(text(),'Gmail')] | //a[@aria-label='Gmail']",
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Element clicked successfully.", body.message)
        self.assertIsNotNone(body.solution.url)

    def test_v1_endpoint_sessions_click_missing_element(self):
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_click_missing"})
        self._request("POST", "/v1", {"cmd": "request.get", "session": "test_click_missing", "url": self.google_url})

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "sessions.click",
                "session": "test_click_missing",
                "selector": "//span[@id='nonexistent-span-12345']",
            },
            status=500,
        )
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("Error clicking element", body.message)

    def test_v1_endpoint_sessions_action(self):
        """sessions.action executes a list of browser actions."""
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_action_session"})
        self._request("POST", "/v1", {"cmd": "request.get", "session": "test_action_session", "url": self.google_url})

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "sessions.action",
                "session": "test_action_session",
                "actions": [
                    {"type": "wait", "seconds": 1},
                    {"type": "click", "selector": "//a[contains(text(),'Gmail')] | //a[@aria-label='Gmail']"},
                    {"type": "wait", "seconds": 1},
                ],
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Actions executed successfully.", body.message)
        self.assertIsNotNone(body.solution.url)

    def test_v1_endpoint_sessions_action_missing_actions(self):
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_action_missing"})
        res = self._request(
            "POST",
            "/v1",
            {"cmd": "sessions.action", "session": "test_action_missing"},
            status=500,
        )
        self.assertEqual(res.status_code, 500)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("'actions' is mandatory", body.message)

    def test_v1_endpoint_sessions_action_eval(self):
        """sessions.action eval action returns JS result in evalResult."""
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_eval_session"})
        self._request("POST", "/v1", {"cmd": "request.get", "session": "test_eval_session", "url": self.google_url})

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "sessions.action",
                "session": "test_eval_session",
                "actions": [
                    {"type": "eval", "script": "return document.title"},
                ],
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn("Google", body.solution.evalResult)

    def test_v1_endpoint_sessions_screenshot(self):
        """sessions.screenshot returns a base64 PNG."""
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_screenshot_session"})
        self._request("POST", "/v1", {"cmd": "request.get", "session": "test_screenshot_session", "url": self.google_url})

        res = self._request("POST", "/v1", {"cmd": "sessions.screenshot", "session": "test_screenshot_session"})
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Screenshot captured successfully.", body.message)
        self.assertIsNotNone(body.solution.screenshot)
        self.assertGreater(len(body.solution.screenshot), 100)
        self.assertIn(self.google_url, body.solution.url)

    def test_v1_endpoint_session_dynamic_proxy_switch(self):
        """Dynamic proxy switching and clearing on a reused session."""
        if not _proxy_reachable(self.proxy_http_check_url):
            self.skipTest(f"Proxy not reachable: {self.proxy_http_check_url}")
        if not _proxy_reachable(self.proxy_http_check_url_2):
            self.skipTest(f"Proxy 2 not reachable: {self.proxy_http_check_url_2}")

        hostname = urllib.parse.urlparse(self.google_url).hostname or self.google_url

        # Create a session without any proxy
        self._request("POST", "/v1", {"cmd": "sessions.create", "session": "test_dynamic_proxy"})

        def assert_one_session():
            list_res = self._request("POST", "/v1", {"cmd": "sessions.list"})
            list_body = self._get_json(list_res)
            self.assertEqual(len(list_body["sessions"]), 1)

        assert_one_session()

        # Step 1: request through proxy A
        lines_a_1 = self._get_docker_log_line_count(self.proxy_http_container)
        lines_a_2 = self._get_docker_log_line_count(self.proxy_http_2_container)
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "session": "test_dynamic_proxy",
                "url": self.google_url,
                "proxy": {"url": self.proxy_url},
            },
        )
        self.assertEqual(res.status_code, 200)
        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn(self.google_url, body.solution.url)
        assert_one_session()
        self._assert_request_routed_through_proxy(self.proxy_http_container, lines_a_1, hostname)
        self._assert_request_not_routed_through_proxy(self.proxy_http_2_container, lines_a_2, hostname)

        # Step 2: switch to proxy B (different endpoint)
        lines_b_1 = self._get_docker_log_line_count(self.proxy_http_container)
        lines_b_2 = self._get_docker_log_line_count(self.proxy_http_2_container)
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "session": "test_dynamic_proxy",
                "url": self.google_url,
                "proxy": {"url": self.proxy_url_2},
            },
        )
        self.assertEqual(res.status_code, 200)
        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn(self.google_url, body.solution.url)
        assert_one_session()
        self._assert_request_routed_through_proxy(self.proxy_http_2_container, lines_b_2, hostname)
        self._assert_request_not_routed_through_proxy(self.proxy_http_container, lines_b_1, hostname)

        # Step 3: clear proxy (explicit empty) and request directly
        lines_c_1 = self._get_docker_log_line_count(self.proxy_http_container)
        lines_c_2 = self._get_docker_log_line_count(self.proxy_http_2_container)
        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "session": "test_dynamic_proxy",
                "url": self.google_url,
                "proxy": {"url": ""},
            },
        )
        self.assertEqual(res.status_code, 200)
        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn(self.google_url, body.solution.url)
        assert_one_session()
        self._assert_request_not_routed_through_proxy(self.proxy_http_container, lines_c_1, hostname)
        self._assert_request_not_routed_through_proxy(self.proxy_http_2_container, lines_c_2, hostname)

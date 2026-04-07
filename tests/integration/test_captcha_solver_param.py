"""Integration tests for the per-request captchaSolver parameter.

These tests exercise the new ``captchaSolver`` field added to V1RequestBase.
They run against a live FlareSolverr instance and cover:

- Invalid solver name  → 500 error with a clear message
- ``"default"`` solver → accepted, behaves like the built-in solver
- ``"hcaptcha-challenger"`` → accepted when library is installed in the image
- ``"recaptcha-challenger"`` → accepted when library is installed in the image

The hCaptcha / reCaptcha challenger tests are skipped automatically when the
respective solver is not registered in the running FlareSolverr instance (i.e.
the library is not installed there).  The GitHub Actions workflow for this test
file builds a custom image that *does* install both libraries.

Test URLs:
- hCaptcha demo : https://accounts.hcaptcha.com/demo
- reCAPTCHA demo: https://www.google.com/recaptcha/api2/demo
"""

import os
import unittest

import pytest
import requests

from dtos import V1ResponseBase, STATUS_OK, STATUS_ERROR
import utils

pytestmark = pytest.mark.integration

HCAPTCHA_DEMO_URL = "https://accounts.hcaptcha.com/demo"
RECAPTCHA_DEMO_URL = "https://www.google.com/recaptcha/api2/demo"
PLAIN_URL = "https://www.google.com"


class TestCaptchaSolverParam(unittest.TestCase):
    base_url = None

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
                import time
                time.sleep(1)

    def _post(self, payload, *, expected_status=None):
        res = requests.post(f"{self.base_url}/v1", json=payload, timeout=120)
        if expected_status is not None:
            self.assertEqual(res.status_code, expected_status)
        return res

    def _available_solvers(self):
        """Query the index endpoint and parse available solvers from logs isn't
        possible, so we probe with a known-bad solver to get the error message
        which lists available solvers — or just call /v1 with a harmless way.

        Simpler: attempt a request with each solver name using a fast URL and
        see if it is rejected.  We cache the result per test run.
        """
        if not hasattr(self.__class__, "_solvers_cache"):
            available = {"default"}
            for name in ("hcaptcha-challenger", "recaptcha-challenger"):
                probe = self._post({"cmd": "request.get", "url": PLAIN_URL, "captchaSolver": name, "maxTimeout": 500})
                if probe.status_code != 500 or "is invalid" not in probe.json().get("message", ""):
                    available.add(name)
            self.__class__._solvers_cache = available
        return self.__class__._solvers_cache

    # ------------------------------------------------------------------
    # Parameter validation
    # ------------------------------------------------------------------

    def test_invalid_captcha_solver_name_returns_error(self):
        res = self._post(
            {"cmd": "request.get", "url": PLAIN_URL, "captchaSolver": "nonexistent-solver"},
            expected_status=500,
        )
        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("nonexistent-solver", body.message)
        self.assertIn("is invalid", body.message)
        self.assertIn("default", body.message)

    def test_invalid_captcha_solver_name_on_post_returns_error(self):
        res = self._post(
            {"cmd": "request.post", "url": "https://httpbin.org/post", "postData": "a=b", "captchaSolver": "bad-solver"},
            expected_status=500,
        )
        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_ERROR, body.status)
        self.assertIn("bad-solver", body.message)
        self.assertIn("is invalid", body.message)

    # ------------------------------------------------------------------
    # Default solver (always available)
    # ------------------------------------------------------------------

    def test_explicit_default_solver_accepted(self):
        res = self._post(
            {"cmd": "request.get", "url": PLAIN_URL, "captchaSolver": "default"},
            expected_status=200,
        )
        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn(body.message, {"Challenge solved!", "Challenge not detected!"})
        self.assertEqual(utils.get_flaresolverr_version(), body.version)
        self.assertIn("Chrome/", body.solution.userAgent)

    # ------------------------------------------------------------------
    # hcaptcha-challenger (skipped when library not installed in container)
    # ------------------------------------------------------------------

    def test_hcaptcha_challenger_solver_accepted_on_hcaptcha_demo(self):
        if "hcaptcha-challenger" not in self._available_solvers():
            pytest.skip("hcaptcha-challenger not installed in FlareSolverr instance")

        res = self._post(
            {
                "cmd": "request.get",
                "url": HCAPTCHA_DEMO_URL,
                "captchaSolver": "hcaptcha-challenger",
                "maxTimeout": 90000,
            },
            expected_status=200,
        )
        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn(body.message, {"Challenge solved!", "Challenge not detected!"})
        self.assertEqual(utils.get_flaresolverr_version(), body.version)
        self.assertIsNotNone(body.solution)

    def test_hcaptcha_challenger_solver_accepted_on_plain_page(self):
        if "hcaptcha-challenger" not in self._available_solvers():
            pytest.skip("hcaptcha-challenger not installed in FlareSolverr instance")

        res = self._post(
            {
                "cmd": "request.get",
                "url": PLAIN_URL,
                "captchaSolver": "hcaptcha-challenger",
            },
            expected_status=200,
        )
        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)

    # ------------------------------------------------------------------
    # recaptcha-challenger (skipped when library not installed in container)
    # ------------------------------------------------------------------

    def test_recaptcha_challenger_solver_accepted_on_recaptcha_demo(self):
        if "recaptcha-challenger" not in self._available_solvers():
            pytest.skip("recaptcha-challenger not installed in FlareSolverr instance")

        res = self._post(
            {
                "cmd": "request.get",
                "url": RECAPTCHA_DEMO_URL,
                "captchaSolver": "recaptcha-challenger",
                "maxTimeout": 90000,
            },
            expected_status=200,
        )
        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertIn(body.message, {"Challenge solved!", "Challenge not detected!"})
        self.assertEqual(utils.get_flaresolverr_version(), body.version)
        self.assertIsNotNone(body.solution)

    def test_recaptcha_challenger_solver_accepted_on_plain_page(self):
        if "recaptcha-challenger" not in self._available_solvers():
            pytest.skip("recaptcha-challenger not installed in FlareSolverr instance")

        res = self._post(
            {
                "cmd": "request.get",
                "url": PLAIN_URL,
                "captchaSolver": "recaptcha-challenger",
            },
            expected_status=200,
        )
        body = V1ResponseBase(res.json())
        self.assertEqual(STATUS_OK, body.status)
        self.assertEqual("Challenge not detected!", body.message)

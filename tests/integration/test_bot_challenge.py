"""
Integration tests for bot detection challenge pages.

These tests verify that FlareSolverr can pass the bot detection challenge
without being detected as automation.

The challenge pages are hosted at: https://smeinecke.github.io/bot-web-challenge/
"""

import os
import sys
import re
import unittest
import time

import pytest
import requests

import html as html_module
import json

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

try:
    from flaresolverr.dtos import V1ResponseBase, STATUS_OK
    from flaresolverr import utils
except ImportError as e:
    # Allow test collection to work even if flaresolverr isn't installed
    V1ResponseBase = dict
    STATUS_OK = "ok"
    utils = type('utils', (), {'get_flaresolverr_version': lambda: 'test'})()

pytestmark = pytest.mark.integration


class TestBotChallenge(unittest.TestCase):
    """Test FlareSolverr against bot detection challenge pages."""

    base_url = None
    challenge_url = "https://smeinecke.github.io/bot-web-challenge"

    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191")

        # Wait until FlareSolverr server is ready
        for i in range(30):
            try:
                requests.get(f"{cls.base_url}/", timeout=5)
                break
            except requests.exceptions.ConnectionError:
                if i == 29:
                    raise
                time.sleep(1)

    def _request(self, method: str, path: str, json=None, status=None, timeout=180):
        url = f"{self.base_url}{path}"
        if method == "GET":
            res = requests.get(url, timeout=timeout)
        elif method == "POST":
            res = requests.post(url, json=json, timeout=timeout)
        else:
            raise ValueError(f"Unsupported method: {method}")
        if status is not None:
            self.assertEqual(res.status_code, status)
        return res

    def _get_json(self, res):
        return res.json()

    def _extract_challenge_results(self, html):
        """Extract JSON results from challenge page HTML output."""

        # Find JSON in <pre><code> block from showJSONOutput()
        match = re.search(r'<pre[^>]*><code[^>]*>(.*?)</code></pre>', html, re.DOTALL)
        if match:
            json_str = html_module.unescape(match.group(1))
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        return None

    def _assert_no_medium_or_higher_findings(self, summary, scored_artifacts):
        """Semantic check: only info/weak findings are acceptable."""
        self.assertEqual(summary.get("mediumFindings", 0), 0,
                         f"Unexpected medium findings: {scored_artifacts}")
        self.assertEqual(summary.get("strongFindings", 0), 0,
                         f"Unexpected strong findings: {scored_artifacts}")
        self.assertEqual(summary.get("hardFindings", 0), 0,
                         f"Unexpected hard findings: {scored_artifacts}")

    def _assert_summary_human(self, summary, scored_artifacts):
        """Semantic check: the page's own verdict must classify the browser as human."""
        self.assertEqual(summary.get("verdict"), "human",
                         f"Challenge verdict was not 'human': {scored_artifacts}")
        self.assertFalse(summary.get("botDetected"),
                         f"Challenge reports botDetected=true: {scored_artifacts}")
        self.assertIn(summary.get("risk", ""), ("low", "none"),
                      f"Challenge risk is not low/none: {scored_artifacts}")

    def _build_diagnostics(self, results):
        """Return an opinionated diagnostics dict for failed test output."""
        return {
            "summary": results.get("summary"),
            "scoredArtifacts": results.get("scoredArtifacts", []),
            "failedTests": {
                name: data for name, data in results.get("tests", {}).items()
                if not data.get("passed", False)
            },
        }

    def _print_diagnostics(self, diagnostics):
        """Pretty-print human-readable diagnostics to stdout."""
        print("\nBot challenge diagnostics:")
        for name, value in diagnostics.items():
            print(f"\n{name}:")
            print(json.dumps(value, indent=2, default=str))

    def test_static_challenge_basic_stealth(self):
        """
        Test that FlareSolverr basic stealth measures work against static challenge.

        Verifies critical stealth indicators via JSON output and the overall
        challenge verdict. Accepts only info/weak findings; a page-local
        console.log wrapper is the expected info-level runtime-API integrity
        finding.
        """
        static_url = f"{self.challenge_url}/static.html"

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "url": static_url,
                "stealth": True,
                "actions": [
                    {"type": "wait", "seconds": 8},
                    {"type": "click", "selector": "//button[@onclick='showJSONOutput()']"},
                    {"type": "wait_for", "selector": "//pre/code", "timeout": 5000},
                ],
            }
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)

        solution = body.solution
        self.assertEqual(solution.status, 200)

        results = self._extract_challenge_results(solution.response)
        self.assertIsNotNone(results, "Failed to extract JSON results from page")
        self.assertIn("tests", results, "JSON results should contain 'tests' key")
        self.assertIn("summary", results, "JSON results should contain 'summary' key")

        # Critical stealth checks - these MUST pass for any working stealth
        critical_tests = [
            "hasBotUserAgent",
            "hasWebdriverTrue",
            "hasWebdriverInFrameTrue",
            "isPlaywright",
        ]

        for test_name in critical_tests:
            with self.subTest(check=test_name):
                self.assertIn(test_name, results["tests"],
                            f"{test_name} should be present in test results")
                test_result = results["tests"][test_name]
                self.assertTrue(test_result.get("passed", False),
                              f"{test_name} should pass - critical stealth failure")

        summary = results["summary"]
        scored_artifacts = results.get("scoredArtifacts", [])
        diagnostics = self._build_diagnostics(results)

        self._assert_no_medium_or_higher_findings(summary, scored_artifacts)
        self._assert_summary_human(summary, scored_artifacts)

        # Persist and print diagnostics if the test reached this point.
        self._print_diagnostics(diagnostics)

    def test_interaction_challenge_form_submission(self):
        """
        Test that FlareSolverr can interact with the challenge form and produce results.

        This test verifies:
        - Form can be filled and submitted via FlareSolverr actions
        - Interaction tracking produces analysis results
        - superHumanSpeed is detected (expected with automated fill)

        Note: Automated interactions will trigger bot-like detection (straight mouse
        paths, fast timing) - this is expected behavior for CDP automation.
        """
        interactions_url = f"{self.challenge_url}/interactions.html"

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "url": interactions_url,
                "stealth": True,
                "actions": [
                    {"type": "wait", "seconds": 1},
                    {"type": "fill", "selector": "//input[@id='email']", "value": "test@example.com"},
                    {"type": "wait", "seconds": 0.5},
                    {"type": "fill", "selector": "//input[@id='password']", "value": "TestPass123"},
                    {"type": "wait", "seconds": 0.5},
                    {"type": "click", "selector": "//button[@type='submit']"},
                    {"type": "wait_for", "selector": "//*[@id='interaction-results']", "timeout": 5000},
                    {"type": "click", "selector": "//button[@onclick='showJSONOutput()']"},
                    {"type": "wait_for", "selector": "//pre/code", "timeout": 5000},
                ],
            },
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)

        solution = body.solution
        self.assertEqual(solution.status, 200)

        # Extract and parse JSON results
        results = self._extract_challenge_results(solution.response)
        self.assertIsNotNone(results, "Failed to extract JSON results from page")
        self.assertIn("tests", results, "JSON results should contain 'tests' key")

        # Verify interaction test results are present
        interaction_tests = [
            "suspiciousClientSideBehavior",
            "superHumanSpeed",
            "hasCDPMouseLeak",
        ]

        for test_name in interaction_tests:
            self.assertIn(test_name, results["tests"],
                        f"{test_name} should be present in interaction results")

        # Log all failed tests for analysis
        failed_tests = [name for name, data in results["tests"].items()
                       if not data.get("passed", False)]
        if failed_tests:
            print(f"\nDetected interaction bot indicators: {failed_tests}")

    def test_challenge_with_json_output(self):
        """
        Test that the JSON output endpoint works and shows passing results.

        This test enables programmatic verification of all test results.
        """
        static_url = f"{self.challenge_url}/static.html"

        res = self._request(
            "POST",
            "/v1",
            {
                "cmd": "request.get",
                "url": static_url,
                "stealth": True,
                "actions": [
                    {"type": "wait", "seconds": 8},
                    {"type": "click", "selector": "//button[@onclick='showJSONOutput()']"},
                    {"type": "wait_for", "selector": "//pre/code", "timeout": 5000},
                ],
            }
        )
        self.assertEqual(res.status_code, 200)

        body = V1ResponseBase(self._get_json(res))
        self.assertEqual(STATUS_OK, body.status)

        solution = body.solution

        # Extract JSON results and verify structure
        results = self._extract_challenge_results(solution.response)
        self.assertIsNotNone(results, "Failed to extract JSON results from page")
        self.assertIn("tests", results)
        self.assertIn("summary", results)
        self.assertIn("timestamp", results)
        self.assertIn("userAgent", results)

        # Verify summary structure (current challenge schema)
        summary = results["summary"]
        required_summary_fields = [
            "totalTests", "passed", "finding", "inconclusive",
            "infoFindings", "weakFindings", "mediumFindings", "strongFindings",
            "hardFindings", "score", "verdict", "botDetected", "suspicious",
            "coverage", "criticalChecksTotal", "criticalChecksCompleted",
            "criticalChecksInconclusive", "uniqueEvidenceCount",
            "independentCategoryCount", "verdictRule",
        ]
        for field in required_summary_fields:
            self.assertIn(field, summary, f"Summary should contain '{field}'")

        scored_artifacts = results.get("scoredArtifacts", [])
        diagnostics = self._build_diagnostics(results)

        self._assert_no_medium_or_higher_findings(summary, scored_artifacts)
        self._assert_summary_human(summary, scored_artifacts)

        # Persist full diagnostic JSON for post-run analysis.
        diag_path = os.environ.get("FLARESOLVERR_CHALLENGE_DIAG", "/tmp/flaresolverr_challenge_diag.json")
        try:
            with open(diag_path, "w") as f:
                json.dump(diagnostics, f, indent=2, default=str)
        except OSError:
            pass

        self._print_diagnostics(diagnostics)


if __name__ == "__main__":
    unittest.main()

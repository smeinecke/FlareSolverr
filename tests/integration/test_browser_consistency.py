"""Integration diagnostic for cross-realm browser consistency.

Runs the custom Chromium build and verifies that intrinsic identity values
propagate coherently through main Window, iframe, DedicatedWorker and
SharedWorker without per-realm JavaScript overrides.
"""

import http.server
import os
import socket
import sys
import threading
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from flaresolverr import diagnostics, utils

pytestmark = pytest.mark.integration


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>FlareSolverr consistency diagnostic</body></html>")

    def log_message(self, *args):
        pass


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestBrowserConsistency(unittest.TestCase):
    """Browser identity must be coherent across execution contexts."""

    def test_navigator_identity_is_coherent_across_realms(self):
        """Main, iframe, DedicatedWorker and SharedWorker share navigator state."""
        port = _find_free_port()
        server = http.server.HTTPServer(("127.0.0.1", port), _QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        driver = utils.get_webdriver()
        try:
            result = diagnostics.collect_browser_consistency(
                driver, page_url=f"http://127.0.0.1:{port}/"
            )

            main = result["main"]["navigator"]
            iframe = result["iframe"]["navigator"]
            dedicated = result["dedicated_worker"]["ok"]["navigator"]
            shared = result["shared_worker"]["ok"]["navigator"]

            for realm_name, nav in [
                ("main", main),
                ("iframe", iframe),
                ("dedicated_worker", dedicated),
                ("shared_worker", shared),
            ]:
                with self.subTest(realm=realm_name):
                    self.assertEqual(nav["typeof_webdriver"], "undefined")
                    self.assertEqual(nav["userAgent"], main["userAgent"])
                    self.assertEqual(nav["platform"], main["platform"])
                    self.assertEqual(nav["language"], main["language"])
                    self.assertEqual(nav["languages"], main["languages"])
                    self.assertEqual(nav["hardwareConcurrency"], main["hardwareConcurrency"])

            self.assertEqual(main["typeof_webdriver"], "undefined")
        finally:
            driver.quit()
            server.shutdown()

    def test_native_apis_are_not_overridden(self):
        """Selected APIs should be native (not own JS replacements)."""
        driver = utils.get_webdriver()
        try:
            result = diagnostics.collect_browser_consistency(driver)
            apis = result["main"]["apis"]

            # Worker constructor must not be wrapped.
            self.assertIsNone(apis["Worker"]["own"]["get"])

            # Navigator language getters must be prototype native accessors.
            self.assertIsNotNone(apis["navigator_language"]["language"])
            self.assertIsNotNone(apis["navigator_language"]["languages"])

            # navigator.permissions.query and mediaDevices.enumerateDevices must
            # not be own JS wrappers.
            self.assertIsNone(apis["permissions_query"]["own"])
            self.assertIsNone(apis["enumerateDevices"]["own"])

            # WebGL getParameter must be the native prototype method.
            self.assertIsNone(apis["webgl_getParameter"]["own"]["get"])
            self.assertIn("[native code]", apis["webgl_getParameter"]["native_string"])
        finally:
            driver.quit()

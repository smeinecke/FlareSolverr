"""Regression tests for Event.isTrusted semantics.

Verifies that JavaScript-dispatched synthetic events are untrusted and that
Chromium/WebDriver-generated native input events retain normal trusted
semantics. The global trusted-event patch must never be reintroduced.
"""

import os
import sys
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from flaresolverr import utils
from selenium.webdriver.common.action_chains import ActionChains

pytestmark = pytest.mark.integration


class TestEventIsTrusted(unittest.TestCase):
    """Regression coverage for Event.isTrusted."""

    def test_synthetic_event_is_untrusted(self):
        """A script-created and dispatched event must report isTrusted=false."""
        driver = utils.get_webdriver()
        try:
            driver.get("data:text/html,<html><body><div id=target></div></body></html>")
            driver.execute_script("""
                window.__syntheticIsTrusted = null;
                const target = document.getElementById('target');
                target.addEventListener('probe', (e) => {
                    window.__syntheticIsTrusted = e.isTrusted;
                });
                const e = new Event('probe', { bubbles: true });
                target.dispatchEvent(e);
            """)
            is_trusted = driver.execute_script("return window.__syntheticIsTrusted")
            self.assertFalse(is_trusted, "Synthetic script-dispatched event must be untrusted")
        finally:
            driver.quit()

    def test_native_click_event_is_trusted(self):
        """A WebDriver-generated click must report isTrusted=true."""
        driver = utils.get_webdriver()
        try:
            driver.get(
                "data:text/html,"
                "<html><body><button id=btn>Click</button></body></html>"
            )
            driver.execute_script("""
                window.__clickIsTrusted = null;
                const btn = document.getElementById('btn');
                btn.addEventListener('click', (e) => {
                    window.__clickIsTrusted = e.isTrusted;
                });
            """)
            btn = driver.find_element("id", "btn")
            ActionChains(driver).click(btn).perform()
            is_trusted = driver.execute_script("return window.__clickIsTrusted")
            self.assertTrue(is_trusted, "WebDriver-generated click must be trusted")
        finally:
            driver.quit()

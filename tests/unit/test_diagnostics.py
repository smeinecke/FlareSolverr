"""Unit tests for the browser consistency diagnostic module."""

import json
from unittest.mock import MagicMock

from flaresolverr import diagnostics


def test_collect_browser_consistency_executes_async_script():
    """It should load the diagnostic page and execute the async script."""
    driver = MagicMock()
    driver.current_url = "about:blank"
    driver.execute_async_script.return_value = {
        "main": {"navigator": {"webdriver": None}},
        "dedicated_worker": {"ok": {}},
        "shared_worker": {"ok": {}},
        "iframe": {"navigator": {}},
    }

    result = diagnostics.collect_browser_consistency(driver)

    driver.get.assert_called_once_with("data:text/html,<html><body></body></html>")
    assert driver.execute_async_script.call_count == 1
    assert result["main"]["navigator"]["webdriver"] is None


def test_collect_browser_consistency_parses_string_result():
    """It should parse a JSON string returned by the browser."""
    driver = MagicMock()
    driver.current_url = "about:blank"
    payload = {
        "main": {"navigator": {"webdriver": None}},
        "dedicated_worker": {"ok": {}},
        "shared_worker": {"ok": {}},
        "iframe": {"navigator": {}},
    }
    driver.execute_async_script.return_value = json.dumps(payload)

    result = diagnostics.collect_browser_consistency(driver)

    assert result["main"]["navigator"]["webdriver"] is None


def test_collect_browser_consistency_uses_provided_page_url():
    """It should load the caller-provided page URL when given."""
    driver = MagicMock()
    driver.execute_async_script.return_value = {
        "main": {"navigator": {}},
        "dedicated_worker": {"ok": {}},
        "shared_worker": {"ok": {}},
        "iframe": {"navigator": {}},
    }

    diagnostics.collect_browser_consistency(driver, page_url="http://127.0.0.1:9999/")

    driver.get.assert_called_once_with("http://127.0.0.1:9999/")

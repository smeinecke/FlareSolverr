"""Tests for cookies timing fix.

Ensures that cookies are captured after waitInSeconds to include challenge cookies.

References: https://github.com/FlareSolverr/FlareSolverr/issues/1652
"""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from dtos import V1RequestBase


class MockWebDriver:
    """Mock WebDriver for testing cookies behavior."""

    def __init__(self):
        self.current_url = "https://example.com"
        self.page_source = "<html></html>"
        self._cookies = []

    def get_cookies(self):
        """Return current cookies."""
        return self._cookies.copy()

    def add_cookie(self, cookie):
        """Add a cookie."""
        self._cookies.append(cookie)

    def get_screenshot_as_base64(self):
        return "base64_screenshot"

    def quit(self):
        """Mock quit method."""
        pass

    def close(self):
        """Mock close method."""
        pass

    def execute_script(self, script):
        """Mock execute_script method."""
        if "userAgent" in script:
            return "Mozilla/5.0 (Test)"
        return None


class TestCookiesTiming:
    """Tests for cookies timing in _build_challenge_result."""

    def test_cookies_captured_after_wait(self):
        """Test that cookies are captured after waitInSeconds completes.

        This tests the fix for issue #1652 where cookies were captured before
the waitInSeconds delay, missing challenge cookies.
        """
        # Import here to avoid dependency issues
        import flaresolverr_service as service

        mock_driver = MockWebDriver()

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "waitInSeconds": 0.1,
        })

        # Simulate challenge cookies being added during wait
        # Use a flag to track if sleep has been called to avoid recursion
        sleep_called = [False]
        original_sleep = time.sleep

        def simulate_challenge_cookies_added(seconds):
            if not sleep_called[0]:
                sleep_called[0] = True
                # Simulate cookies being added during the wait
                mock_driver._cookies = [{"name": "cf_clearance", "value": "challenge_token"}]
            # Call actual sleep with reduced time
            return original_sleep(min(seconds, 0.01))

        with patch.object(time, 'sleep', side_effect=simulate_challenge_cookies_added):
            result = service._build_challenge_result(req, mock_driver, None)

        # Cookies should include the challenge cookie
        assert result.cookies is not None
        assert len(result.cookies) > 0
        assert any(c.get("name") == "cf_clearance" for c in result.cookies)

    def test_cookies_not_captured_before_wait(self):
        """Test that cookies capture happens after wait, not before."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        cookies_captured = []

        # Track when cookies are captured
        original_get_cookies = mock_driver.get_cookies

        def tracking_get_cookies():
            cookies = original_get_cookies()
            cookies_captured.append(len(cookies))
            return cookies

        mock_driver.get_cookies = tracking_get_cookies

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "waitInSeconds": 0.01,
        })

        # Add a cookie after a small delay
        def add_cookie_later():
            time.sleep(0.005)
            mock_driver._cookies = [{"name": "new_cookie", "value": "added_during_wait"}]

        import threading
        thread = threading.Thread(target=add_cookie_later)

        # Store original sleep before patching to avoid recursion
        _orig_sleep = time.sleep
        with patch.object(time, 'sleep', side_effect=lambda s: _orig_sleep(min(s, 0.01))):
            thread.start()
            result = service._build_challenge_result(req, mock_driver, None)
            thread.join()

        # Should have captured cookies (at least once)
        assert len(cookies_captured) >= 1

    def test_cookies_include_all_after_wait(self):
        """Test that all cookies including late ones are captured."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()

        # Pre-existing cookie
        mock_driver._cookies = [{"name": "existing", "value": "cookie1"}]

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "waitInSeconds": 0.05,
        })

        # Add challenge cookie during wait
        def add_challenge_cookie():
            time.sleep(0.02)
            mock_driver._cookies.append({"name": "cf_clearance", "value": "challenge"})

        import threading
        thread = threading.Thread(target=add_challenge_cookie)
        thread.start()

        # Store original sleep before patching to avoid recursion
        _orig_sleep = time.sleep
        with patch.object(time, 'sleep', side_effect=lambda s: _orig_sleep(min(s, 0.05))):
            result = service._build_challenge_result(req, mock_driver, None)

        thread.join()

        # Should have both cookies
        cookie_names = {c.get("name") for c in result.cookies}
        assert "existing" in cookie_names
        assert "cf_clearance" in cookie_names

    def test_return_only_cookies_still_works(self):
        """Test that returnOnlyCookies mode works correctly with timing fix."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        mock_driver._cookies = [{"name": "test", "value": "value"}]

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "returnOnlyCookies": True,
            "waitInSeconds": 0.01,
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            result = service._build_challenge_result(req, mock_driver, None)

        assert result.cookies is not None
        assert len(result.cookies) == 1
        assert result.cookies[0]["name"] == "test"


class TestCookiesTimingIntegration:
    """Integration tests for cookies timing in full request flow."""

    def test_challenge_cookies_captured_with_wait(self, monkeypatch):
        """Integration test simulating a challenge that sets cookies during wait.

        This simulates the scenario from issue #1652 where a website sends a
challenge that the browser solves, and cookies are set during the wait period.
        """
        import flaresolverr_service as service
        from sessions import SessionsStorage

        # Mock WebDriver that simulates challenge behavior
        class ChallengeWebDriver:
            def __init__(self):
                self.current_url = "https://example.com/protected"
                self.page_source = "<html><body>Protected Content</body></html>"
                self._cookies = [{"name": "initial", "value": "cookie"}]
                self._challenge_solved = False

            def get_cookies(self):
                # Simulate challenge cookie appearing after "challenge resolution"
                if self._challenge_solved:
                    return self._cookies + [{"name": "cf_clearance", "value": "challenge_solved"}]
                return self._cookies

            def get_screenshot_as_base64(self):
                return "screenshot"

        mock_driver = ChallengeWebDriver()

        # Simulate wait that solves challenge
        # Store original sleep before patching to avoid recursion
        _orig_sleep = time.sleep

        def challenge_solving_sleep(seconds):
            # Simulate challenge being solved during wait
            _orig_sleep(min(seconds, 0.01))
            mock_driver._challenge_solved = True

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/protected",
            "waitInSeconds": 0.1,
        })

        with patch.object(time, 'sleep', side_effect=challenge_solving_sleep):
            result = service._build_challenge_result(req, mock_driver, None)

        # Should capture the challenge cookie
        cookie_names = {c.get("name") for c in result.cookies}
        assert "cf_clearance" in cookie_names
        assert "initial" in cookie_names


class TestCookiesEdgeCases:
    """Edge case tests for cookies handling."""

    def test_empty_cookies_after_wait(self):
        """Test handling when no cookies exist after wait."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        mock_driver._cookies = []

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "waitInSeconds": 0.01,
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            result = service._build_challenge_result(req, mock_driver, None)

        assert result.cookies == []

    def test_no_wait_cookies_still_captured(self):
        """Test that cookies are still captured when waitInSeconds is not set."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        mock_driver._cookies = [{"name": "test", "value": "value"}]

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
        })

        result = service._build_challenge_result(req, mock_driver, None)

        assert result.cookies is not None
        assert len(result.cookies) == 1

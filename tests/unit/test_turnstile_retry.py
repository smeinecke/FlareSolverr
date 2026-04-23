"""Tests for turnstile captcha retry fix.

Ensures that the focus reset helper properly cleans up old elements
when retrying turnstile captcha challenges.

References: https://github.com/FlareSolverr/FlareSolverr/issues/1678
Upstream PR: https://github.com/FlareSolverr/FlareSolverr/pull/1677
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from flaresolverr.dtos import V1RequestBase


class MockWebDriver:
    """Mock WebDriver for testing turnstile behavior."""

    def __init__(self):
        self.current_url = "https://example.com"
        self.page_source = '''
        <html>
            <body>
                <input name="cf-turnstile-response" value="">
                <div class="turnstile-container"></div>
            </body>
        </html>
        '''
        self._cookies = []
        self._executed_scripts = []
        self._token_value = ""
        self._find_attempts = 0
        self.switch_to = MagicMock()

    def find_element(self, by, value):
        """Simulate finding the turnstile token input."""
        if "cf-turnstile-response" in value:
            class MockElement:
                def __init__(self, driver):
                    self._driver = driver

                def get_attribute(self, name):
                    if name == "value":
                        # Simulate token appearing after some attempts
                        self._driver._find_attempts += 1
                        if self._driver._find_attempts >= 3:
                            return "valid_token_123"
                        return self._driver._token_value
                    return None
            return MockElement(self)
        raise Exception(f"Element not found: {value}")

    def find_elements(self, by, value):
        """Simulate finding elements."""
        if "turnstile" in value.lower():
            return [MagicMock()]
        return []

    def get_cookies(self):
        return self._cookies.copy()

    def execute_script(self, script):
        """Track executed scripts for verification."""
        self._executed_scripts.append(script)
        # Simulate successful script execution
        return None

    def get_screenshot_as_base64(self):
        return "base64_screenshot"

    def quit(self):
        pass

    def close(self):
        pass


class TestTurnstileRetryFix:
    """Tests for turnstile captcha retry fix."""

    def test_focus_helper_has_unique_id(self):
        """Test that focus helper script creates element with unique ID."""
        from flaresolverr import flaresolverr_service as service

        mock_driver = MockWebDriver()

        # Simulate a turnstile token request
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "tabs_till_verify": 3,
        })

        # Patch time.sleep to avoid delays
        with patch.object(time, 'sleep', side_effect=lambda s: None):
            # This should execute the focus reset script
            result = service._get_turnstile_token(mock_driver, 3)

        # Verify scripts were executed
        assert len(mock_driver._executed_scripts) > 0

        # Check that the focus helper script contains the unique ID
        focus_scripts = [s for s in mock_driver._executed_scripts
                        if "__focus_helper" in s]
        assert len(focus_scripts) > 0

        # Verify the script removes old element and creates new one with ID
        script = focus_scripts[0]
        assert "getElementById('__focus_helper')" in script
        assert "old.remove()" in script or "old.remove();" in script
        assert "el.id = '__focus_helper'" in script

    def test_focus_helper_has_proper_styling(self):
        """Test that focus helper has opacity and pointerEvents styling."""
        from flaresolverr import flaresolverr_service as service

        mock_driver = MockWebDriver()

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "tabs_till_verify": 2,
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            service._get_turnstile_token(mock_driver, 2)

        # Find the focus reset script
        focus_scripts = [s for s in mock_driver._executed_scripts
                        if "opacity" in s]
        assert len(focus_scripts) > 0

        script = focus_scripts[0]
        # Verify invisible styling
        assert "opacity" in script
        assert "pointerEvents" in script or "pointer-events" in script
        assert "fixed" in script.lower()

    def test_old_focus_helper_removed_on_retry(self):
        """Test that old focus helper elements are removed before creating new one."""
        from flaresolverr import flaresolverr_service as service

        mock_driver = MockWebDriver()

        # Simulate multiple retry attempts
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "tabs_till_verify": 3,
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            service._get_turnstile_token(mock_driver, 3)

        # Count how many times the focus reset script was executed
        focus_scripts = [s for s in mock_driver._executed_scripts
                        if "__focus_helper" in s]

        # Should have at least one execution
        assert len(focus_scripts) >= 1

        # Each execution should attempt to remove old element
        for script in focus_scripts:
            assert "getElementById('__focus_helper')" in script
            assert "old.remove()" in script or "old.remove();" in script

    def test_turnstile_eventually_succeeds(self):
        """Test that turnstile captcha eventually succeeds after retries."""
        from flaresolverr import flaresolverr_service as service

        mock_driver = MockWebDriver()

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            token = service._get_turnstile_token(mock_driver, tabs=3)

        # Should eventually get a valid token
        assert token is not None
        assert token == "valid_token_123"


class TestTurnstileIntegration:
    """Integration tests for turnstile captcha resolution."""

    def test_turnstile_detected_on_page(self):
        """Test that turnstile is detected correctly."""
        from flaresolverr.flaresolverr_service import _detect_captcha_type

        class TurnstileWebDriver:
            def __init__(self):
                self.page_source = '''
                <html>
                    <body>
                        <input name="cf-turnstile-response" value="">
                    </body>
                </html>
                '''

            def find_elements(self, by, value):
                if "cf-turnstile-response" in value:
                    return [MagicMock()]
                return []

        driver = TurnstileWebDriver()
        captcha_type = _detect_captcha_type(driver)

        assert captcha_type == "turnstile"

    def test_resolve_turnstile_with_tabs(self):
        """Test turnstile resolution with tabs_till_verify parameter."""
        from flaresolverr import flaresolverr_service as service

        class MockTurnstileDriver:
            def __init__(self):
                self.current_url = "https://example.com"
                self._token_value = ""
                self._attempts = 0
                self.switch_to = MagicMock()

            def get(self, url):
                self.current_url = url

            def find_elements(self, by, value):
                if "cf-turnstile-response" in value:
                    return [MagicMock()]
                return []

            def find_element(self, by, value):
                if "cf-turnstile-response" in value:
                    class MockInput:
                        def __init__(self, driver):
                            self._driver = driver

                        def get_attribute(self, name):
                            self._driver._attempts += 1
                            if self._driver._attempts >= 2:
                                return "token_abc123"
                            return ""
                    return MockInput(self)
                raise Exception("Not found")

            def execute_script(self, script):
                return None

        driver = MockTurnstileDriver()

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "tabs_till_verify": 3,
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            token = service._resolve_turnstile_captcha(req, driver)

        assert token is not None
        assert token == "token_abc123"


class TestTurnstileEdgeCases:
    """Edge case tests for turnstile handling."""

    def test_turnstile_not_found_returns_none(self):
        """Test that missing turnstile returns None."""
        from flaresolverr import flaresolverr_service as service

        class NoTurnstileDriver:
            def __init__(self):
                self.switch_to = MagicMock()

            def get(self, url):
                pass

            def find_elements(self, by, value):
                return []

        driver = NoTurnstileDriver()

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "tabs_till_verify": 3,
        })

        token = service._resolve_turnstile_captcha(req, driver)
        assert token is None

    def test_no_tabs_till_verify_skips_turnstile(self):
        """Test that turnstile resolution is skipped without tabs_till_verify."""
        from flaresolverr import flaresolverr_service as service

        class AnyDriver:
            def __init__(self):
                self.switch_to = MagicMock()

        driver = AnyDriver()

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
        })

        token = service._resolve_turnstile_captcha(req, driver)
        assert token is None

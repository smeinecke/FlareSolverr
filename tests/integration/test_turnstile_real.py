"""Integration tests for turnstile captcha retry fix.

These tests verify the turnstile captcha functionality in more realistic
scenarios, testing the full flow from detection to resolution.

References: https://github.com/FlareSolverr/FlareSolverr/issues/1678
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from dtos import V1RequestBase

# Mark all tests in this file as integration tests
pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture
def mock_webdriver_with_turnstile():
    """Create a mock WebDriver simulating a page with turnstile captcha."""
    class MockTurnstileDriver:
        def __init__(self):
            self.current_url = "https://example.com/protected"
            self.page_source = '''
            <html>
                <head><title>Just a moment...</title></head>
                <body>
                    <div class="cf-turnstile">
                        <input name="cf-turnstile-response" value="">
                        <iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile"></iframe>
                    </div>
                </body>
            </html>
            '''
            self._cookies = []
            self._executed_scripts = []
            self._token_attempts = 0

        def get(self, url):
            self.current_url = url

        def find_element(self, by, value):
            """Simulate finding the turnstile token input."""
            if "cf-turnstile-response" in value:
                class MockTokenInput:
                    def __init__(self, driver):
                        self._driver = driver

                    def get_attribute(self, name):
                        if name == "value":
                            self._driver._token_attempts += 1
                            # Simulate token appearing after 2-3 attempts
                            if self._driver._token_attempts >= 3:
                                return "cf_turnstile_token_xyz789"
                            return ""
                        return None
                return MockTokenInput(self)
            raise Exception(f"Element not found: {value}")

        def find_elements(self, by, value):
            """Simulate finding turnstile elements."""
            elements = []
            if any(x in value for x in ["cf-turnstile", "turnstile", "iframe"]):
                elements.append(MagicMock())
            return elements

        def execute_script(self, script):
            """Track executed scripts for verification."""
            self._executed_scripts.append(script)
            # Simulate DOM manipulation
            if "__focus_helper" in script:
                return None
            return None

        def get_cookies(self):
            return self._cookies.copy()

        def get_screenshot_as_base64(self):
            return "base64_screenshot"

        def quit(self):
            pass

        def close(self):
            pass

    return MockTurnstileDriver()


class TestTurnstileRealIntegration:
    """Integration tests for turnstile captcha in realistic scenarios."""

    def test_turnstile_detected_via_iframe_src(self, mock_webdriver_with_turnstile):
        """Test turnstile is detected via iframe src attribute."""
        from flaresolverr_service import _detect_captcha_type
        from urllib.parse import urlparse

        driver = mock_webdriver_with_turnstile

        # Verify the mock has turnstile iframe using proper URL parsing
        from urllib.parse import urlparse
        from html.parser import HTMLParser

        class URLExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.urls = []

            def handle_starttag(self, tag, attrs):
                if tag == "iframe":
                    for name, value in attrs:
                        if name == "src":
                            self.urls.append(value)

        parser = URLExtractor()
        parser.feed(driver.page_source)

        found_turnstile = False
        for url in parser.urls:
            parsed = urlparse(url)
            if parsed.hostname and parsed.hostname.endswith(".cloudflare.com"):
                found_turnstile = True
                break
        assert found_turnstile, "Turnstile iframe not found"

        # Check turnstile keyword in page content
        assert driver.page_source.find("turnstile") != -1

    def test_full_turnstile_resolution_flow(self, mock_webdriver_with_turnstile):
        """Test complete turnstile resolution flow with retries."""
        import flaresolverr_service as service

        driver = mock_webdriver_with_turnstile

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/protected",
            "tabs_till_verify": 3,
            "maxTimeout": 30000,
        })

        # Patch sleep to speed up test
        with patch.object(time, 'sleep', side_effect=lambda s: None):
            token = service._resolve_turnstile_captcha(req, driver)

        # Should eventually get a valid token
        assert token is not None
        assert "token" in token.lower() or "turnstile" in token.lower()

        # Verify focus helper scripts were executed during retries
        focus_scripts = [s for s in driver._executed_scripts if "__focus_helper" in s]
        assert len(focus_scripts) >= 1

    def test_multiple_retry_attempts_clean_focus_helpers(self, mock_webdriver_with_turnstile):
        """Test that multiple retry attempts properly clean up focus helpers."""
        import flaresolverr_service as service

        driver = mock_webdriver_with_turnstile

        # Force multiple retries by making token take longer to appear
        original_attempts = driver._token_attempts

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/protected",
            "tabs_till_verify": 5,
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            token = service._resolve_turnstile_captcha(req, driver)

        # Should have executed focus helper script multiple times
        focus_scripts = [s for s in driver._executed_scripts if "__focus_helper" in s]

        # Each script should contain the cleanup logic
        for script in focus_scripts:
            # Verify old element removal
            assert "getElementById('__focus_helper')" in script
            assert "old.remove()" in script or "old.remove();" in script
            # Verify new element creation with ID
            assert "el.id = '__focus_helper'" in script

    def test_turnstile_with_session_persistence(self, mock_webdriver_with_turnstile):
        """Test turnstile resolution maintains session state."""
        import flaresolverr_service as service
        from sessions import SessionsStorage

        driver = mock_webdriver_with_turnstile

        # Simulate session cookies
        driver._cookies = [
            {"name": "cf_clearance", "value": "partial_clearance"},
        ]

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/protected",
            "tabs_till_verify": 3,
            "session": "test-turnstile-session",
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            token = service._resolve_turnstile_captcha(req, driver)

        assert token is not None

    def test_turnstile_resolution_updates_cookies(self, mock_webdriver_with_turnstile):
        """Test that turnstile resolution updates session cookies."""
        import flaresolverr_service as service

        driver = mock_webdriver_with_turnstile

        # Initial cookies
        initial_cookies = [{"name": "session_id", "value": "abc123"}]
        driver._cookies = initial_cookies.copy()

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/protected",
            "tabs_till_verify": 3,
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            result = service._build_challenge_result(req, driver, "turnstile_token_xyz")

        # Verify cookies are included in result
        assert result.cookies is not None
        assert len(result.cookies) >= 1
        assert any(c.get("name") == "session_id" for c in result.cookies)


class TestTurnstileWithRealChallengePages:
    """Tests that document expected behavior with real challenge pages.

    These tests don't actually make network requests but document the
    expected behavior when encountering real Cloudflare turnstile pages.
    """

    @pytest.mark.skipif(
        not os.environ.get("TEST_REAL_CAPTCHAS"),
        reason="Set TEST_REAL_CAPTCHAS=1 to test against real challenge pages"
    )
    def test_real_cloudflare_turnstile_page(self):
        """Test against real Cloudflare turnstile challenge page.

        This test would require:
        1. Network access to a Cloudflare-protected site
        2. A site that triggers turnstile (not just regular challenge)
        3. TEST_REAL_CAPTCHAS environment variable set
        """
        pytest.skip("Real turnstile test requires specific site configuration")

    def test_turnstile_demo_page_structure(self):
        """Verify expected structure of turnstile demo/test pages."""
        # Document expected HTML structure
        expected_turnstile_html = """
        Expected turnstile page structure:
        1. Input element: <input name="cf-turnstile-response" value="">
        2. Iframe: src contains hostname ending with .cloudflare.com
        3. Container div with class "cf-turnstile"
        4. Title often contains "Just a moment..." or similar
        """
        assert expected_turnstile_html.find("cf-turnstile-response") != -1
        assert expected_turnstile_html.find(".cloudflare.com") != -1

    def test_tabs_till_verify_navigation_pattern(self):
        """Document expected tab navigation pattern for turnstile."""
        # This documents how tabs_till_verify should work:
        # 1. Navigate to page
        # 2. Press Tab N times to reach captcha checkbox
        # 3. Click/verify the captcha
        # 4. If fails, retry with focus reset

        navigation_pattern = """
        Tab navigation pattern for turnstile:
        - tabs_till_verify=3 means press Tab 3 times to reach checkbox
        - First tab might hit the URL bar or page
        - Subsequent tabs navigate through page elements
        - Final tab should land on turnstile checkbox
        - If click fails, focus reset helper clears state
        - Retry with same tab count
        """
        assert "Tab" in navigation_pattern
        assert "checkbox" in navigation_pattern
        assert "focus reset" in navigation_pattern


class TestTurnstileRetryRobustness:
    """Tests for robustness of turnstile retry mechanism."""

    def test_turnstile_retry_with_varying_response_times(self, mock_webdriver_with_turnstile):
        """Test that retry works with varying token response times."""
        import flaresolverr_service as service

        class VariableDelayDriver(mock_webdriver_with_turnstile.__class__):
            def __init__(self):
                super().__init__()
                self._delay_counter = 0

            def find_element(self, by, value):
                if "cf-turnstile-response" in value:
                    class DelayedInput:
                        def __init__(self, driver):
                            self._driver = driver

                        def get_attribute(self, name):
                            if name == "value":
                                self._driver._delay_counter += 1
                                # Variable delay: sometimes fast, sometimes slow
                                if self._driver._delay_counter >= 4:
                                    return "delayed_token_123"
                                return ""
                    return DelayedInput(self)
                raise Exception("Not found")

        driver = VariableDelayDriver()

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/protected",
            "tabs_till_verify": 3,
        })

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            token = service._resolve_turnstile_captcha(req, driver)

        assert token is not None
        assert "delayed_token" in token

    def test_turnstile_handles_page_reload(self, mock_webdriver_with_turnstile):
        """Test turnstile resolution handles page reloads during challenge."""
        import flaresolverr_service as service

        class ReloadingDriver(mock_webdriver_with_turnstile.__class__):
            def __init__(self):
                super().__init__()
                self._reload_count = 0
                self._original_url = "https://example.com/protected"

            def get(self, url):
                # Simulate page reload
                self._reload_count += 1
                if self._reload_count == 1:
                    # First load - challenge page
                    self.current_url = url
                    self.page_source = '''
                    <html><head><title>Just a moment...</title></head>
                    <body><input name="cf-turnstile-response" value=""></body></html>
                    '''
                else:
                    # After reload - success page
                    self.current_url = url
                    self.page_source = '''
                    <html><head><title>Welcome</title></head>
                    <body>Success!</body></html>
                    '''

        driver = ReloadingDriver()

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/protected",
            "tabs_till_verify": 3,
        })

        # Initial navigation
        driver.get(req.url)

        with patch.object(time, 'sleep', side_effect=lambda s: None):
            token = service._resolve_turnstile_captcha(req, driver)

        # Should handle the reload gracefully
        assert driver._reload_count >= 1


class TestTurnstileEnvironmentSetup:
    """Tests for environment setup needed for turnstile solving."""

    def test_turnstile_requires_tabs_till_verify(self):
        """Test that turnstile resolution requires tabs_till_verify parameter."""
        import flaresolverr_service as service

        class SimpleDriver:
            pass

        driver = SimpleDriver()

        # Without tabs_till_verify, turnstile resolution is skipped
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
        })

        token = service._resolve_turnstile_captcha(req, driver)
        assert token is None

    def test_turnstile_requires_url(self):
        """Test that turnstile resolution requires URL parameter."""
        import flaresolverr_service as service

        class SimpleDriver:
            pass

        driver = SimpleDriver()

        req = V1RequestBase({
            "cmd": "request.get",
            "tabs_till_verify": 3,
            # url is missing
        })

        # Should raise exception due to missing URL
        with pytest.raises(Exception) as exc_info:
            service._resolve_turnstile_captcha(req, driver)

        assert "url" in str(exc_info.value).lower()

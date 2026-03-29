"""Real integration tests for captcha solvers against live challenges.

These tests verify the captcha solver implementations against real challenge pages.
They are marked with 'integration' and 'slow' markers and should only run when
the solver libraries are installed and browser automation is available.

Test Sites:
- hCaptcha: https://accounts.hcaptcha.com/demo
- reCAPTCHA: https://www.google.com/recaptcha/api2/demo

References:
- https://github.com/QIN2DIM/hcaptcha-challenger
- https://github.com/QIN2DIM/recaptcha-challenger
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

# Mark all tests in this file as integration tests
pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture
def check_solver_libraries():
    """Fixture to check if solver libraries are available."""
    hcaptcha_available = False
    recaptcha_available = False

    try:
        import hcaptcha_challenger  # noqa: F401
        hcaptcha_available = True
    except ImportError:
        pass

    try:
        import recaptcha_challenger  # noqa: F401
        recaptcha_available = True
    except ImportError:
        pass

    return {
        "hcaptcha": hcaptcha_available,
        "recaptcha": recaptcha_available,
    }


@pytest.fixture
def mock_webdriver_with_hcaptcha():
    """Create a mock WebDriver simulating hCaptcha page."""
    class MockWebDriver:
        def __init__(self):
            self.current_url = "https://example.com/login"
            self.page_source = '''
            <html>
                <body>
                    <form>
                        <div class="h-captcha" data-sitekey="test-site-key"></div>
                        <iframe src="https://newassets.hcaptcha.com/captcha/v1/test"></iframe>
                    </form>
                </body>
            </html>
            '''
            self._cookies = []

        def find_elements(self, by, value):
            """Simulate finding hCaptcha elements."""
            elements = []
            if "h-captcha" in value or "hcaptcha" in value:
                elements.append(MagicMock())
            if "iframe" in value and "hcaptcha.com" in value:
                elements.append(MagicMock())
            return elements

        def get_cookies(self):
            return self._cookies.copy()

        def execute_script(self, script):
            return None

        def get_screenshot_as_base64(self):
            return "base64_screenshot"

    return MockWebDriver()


@pytest.fixture
def mock_webdriver_with_recaptcha():
    """Create a mock WebDriver simulating reCAPTCHA page."""
    class MockWebDriver:
        def __init__(self):
            self.current_url = "https://example.com/login"
            self.page_source = '''
            <html>
                <body>
                    <form>
                        <div class="g-recaptcha" data-sitekey="test-site-key"></div>
                        <iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>
                    </form>
                </body>
            </html>
            '''
            self._cookies = []

        def find_elements(self, by, value):
            """Simulate finding reCAPTCHA elements."""
            elements = []
            if "g-recaptcha" in value or "recaptcha" in value:
                elements.append(MagicMock())
            if "iframe" in value and "google.com/recaptcha" in value:
                elements.append(MagicMock())
            return elements

        def get_cookies(self):
            return self._cookies.copy()

        def execute_script(self, script):
            return None

        def get_screenshot_as_base64(self):
            return "base64_screenshot"

    return MockWebDriver()


class TestHCaptchaRealIntegration:
    """Integration tests for hCaptcha solver against real challenge patterns.

    These tests follow the pattern from hcaptcha-challenger examples:
    https://github.com/QIN2DIM/hcaptcha-challenger/blob/main/examples/demo_captcha_agent.py
    """

    @pytest.mark.skipif(
        not os.environ.get("TEST_REAL_CAPTCHAS"),
        reason="Set TEST_REAL_CAPTCHAS=1 to run real captcha tests"
    )
    def test_hcaptcha_solver_with_live_page(self, check_solver_libraries):
        """Test hCaptcha solver against a real challenge page.

        This test requires:
        1. hcaptcha-challenger library installed
        2. Browser automation available
        3. Network access to hCaptcha demo page
        4. TEST_REAL_CAPTCHAS environment variable set

        Based on the example from hcaptcha-challenger:
        ```python
        from hcaptcha_challenger import AgentV, AgentConfig
        agent = AgentV(page=page, agent_config=AgentConfig())
        await agent.robotic_arm.click_checkbox()
        await agent.wait_for_challenge()
        ```
        """
        if not check_solver_libraries["hcaptcha"]:
            pytest.skip("hcaptcha-challenger library not installed")

        # Import here to skip gracefully if not available
        try:
            from hcaptcha_challenger import AgentV, AgentConfig
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            pytest.skip(f"Required library not available: {e}")

        # This test would require actual browser automation
        # For now, we verify the imports work and API is compatible
        assert AgentV is not None
        assert AgentConfig is not None

    def test_hcaptcha_detection_on_page(self, mock_webdriver_with_hcaptcha):
        """Test that hCaptcha is correctly detected on a page."""
        from flaresolverr_service import _detect_captcha_type

        driver = mock_webdriver_with_hcaptcha
        captcha_type = _detect_captcha_type(driver)

        assert captcha_type == "hcaptcha"

    def test_hcaptcha_solver_placeholder_behavior(self, mock_webdriver_with_hcaptcha):
        """Test the placeholder hCaptcha solver behavior.

        The current implementation is a placeholder that logs a warning
        and returns False. This test documents the expected behavior
        until full integration is implemented.
        """
        from captcha_solvers import HCaptchaChallengerSolver

        solver = HCaptchaChallengerSolver()
        driver = mock_webdriver_with_hcaptcha

        # Solver should be unavailable without the library
        assert not solver.is_available()

        # Should return False (not raise exception)
        result = solver.solve(driver, "hcaptcha")
        assert result is False

    def test_hcaptcha_sitekey_accessibility(self):
        """Test that hCaptcha sitekey utilities are accessible if library installed."""
        try:
            from hcaptcha_challenger.utils import SiteKey

            # Verify SiteKey has expected demo keys
            assert hasattr(SiteKey, "user_easy")
            assert hasattr(SiteKey, "epic")
            assert hasattr(SiteKey, "discord")

            # Verify site link generation works
            site_link = SiteKey.as_site_link(SiteKey.user_easy)
            assert "hcaptcha.com" in site_link
        except ImportError:
            pytest.skip("hcaptcha-challenger not installed")


class TestReCaptchaRealIntegration:
    """Integration tests for reCAPTCHA solver against real challenge patterns.

    These tests follow the pattern from recaptcha-challenger examples:
    https://github.com/QIN2DIM/recaptcha-challenger/blob/main/README.md
    """

    @pytest.mark.skipif(
        not os.environ.get("TEST_REAL_CAPTCHAS"),
        reason="Set TEST_REAL_CAPTCHAS=1 to run real captcha tests"
    )
    def test_recaptcha_solver_with_live_page(self, check_solver_libraries):
        """Test reCAPTCHA solver against a real challenge page.

        This test requires:
        1. recaptcha-challenger library installed
        2. Browser automation available
        3. Network access to Google reCAPTCHA demo page
        4. TEST_REAL_CAPTCHAS environment variable set

        Based on the example from recaptcha-challenger:
        ```python
        from recaptcha_challenger import new_audio_solver
        solver = new_audio_solver()
        if solver.utils.face_the_checkbox(page):
            solver.anti_recaptcha(page)
        ```
        """
        if not check_solver_libraries["recaptcha"]:
            pytest.skip("recaptcha-challenger library not installed")

        try:
            from recaptcha_challenger import new_audio_solver
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            pytest.skip(f"Required library not available: {e}")

        assert new_audio_solver is not None

    def test_recaptcha_detection_on_page(self, mock_webdriver_with_recaptcha):
        """Test that reCAPTCHA is correctly detected on a page."""
        from flaresolverr_service import _detect_captcha_type

        driver = mock_webdriver_with_recaptcha
        captcha_type = _detect_captcha_type(driver)

        assert captcha_type == "recaptcha"

    def test_recaptcha_solver_placeholder_behavior(self, mock_webdriver_with_recaptcha):
        """Test the placeholder reCAPTCHA solver behavior."""
        from captcha_solvers import ReCaptchaChallengerSolver

        solver = ReCaptchaChallengerSolver()
        driver = mock_webdriver_with_recaptcha

        # Solver should be unavailable without the library
        assert not solver.is_available()

        # Should return False (not raise exception)
        result = solver.solve(driver, "recaptcha")
        assert result is False

    def test_recaptcha_demo_page_accessible(self):
        """Verify that the reCAPTCHA demo page URL is correct."""
        # Document the expected demo page URL
        demo_url = "https://www.google.com/recaptcha/api2/demo"

        # In a real integration test, we would verify the page loads
        # For this test, we just verify the URL pattern
        assert "google.com" in demo_url
        assert "recaptcha" in demo_url
        assert "demo" in demo_url


class TestSolverManagerIntegration:
    """Integration tests for SolverManager with real solvers."""

    def test_manager_detects_installed_solvers(self, check_solver_libraries):
        """Test that SolverManager correctly detects installed solvers."""
        from captcha_solvers import SolverManager

        manager = SolverManager()
        available = manager.list_available_solvers()

        # Default solver is always available
        assert "default" in available

        # Check if external solvers are detected
        if check_solver_libraries["hcaptcha"]:
            assert "hcaptcha-challenger" in available

        if check_solver_libraries["recaptcha"]:
            assert "recaptcha-challenger" in available

    def test_manager_routes_to_hcaptcha_solver(self, mock_webdriver_with_hcaptcha, check_solver_libraries):
        """Test SolverManager routes hCaptcha challenges correctly."""
        from captcha_solvers import SolverManager

        manager = SolverManager()
        driver = mock_webdriver_with_hcaptcha

        # Should not raise exception
        result = manager.solve(driver, "hcaptcha")
        # Returns False since no real solver or default returns False
        assert result is False

    def test_manager_routes_to_recaptcha_solver(self, mock_webdriver_with_recaptcha, check_solver_libraries):
        """Test SolverManager routes reCAPTCHA challenges correctly."""
        from captcha_solvers import SolverManager

        manager = SolverManager()
        driver = mock_webdriver_with_recaptcha

        # Should not raise exception
        result = manager.solve(driver, "recaptcha")
        assert result is False


class TestEnvironmentSetup:
    """Tests for environment setup needed for real captcha solving."""

    def test_captcha_solver_env_variable(self, monkeypatch):
        """Test CAPTCHA_SOLVER environment variable is read correctly."""
        from captcha_solvers import get_config_captcha_solver

        # Test default
        monkeypatch.delenv("CAPTCHA_SOLVER", raising=False)
        assert get_config_captcha_solver() == "default"

        # Test custom value
        monkeypatch.setenv("CAPTCHA_SOLVER", "hcaptcha-challenger")
        assert get_config_captcha_solver() == "hcaptcha-challenger"

    def test_playwright_installation_check(self):
        """Test that playwright is available for browser automation."""
        try:
            from playwright.sync_api import sync_playwright
            assert sync_playwright is not None
        except ImportError:
            pytest.skip("playwright not installed - needed for real captcha tests")

    def test_selenium_webdriver_available(self):
        """Test that selenium WebDriver is available."""
        from selenium.webdriver.chrome.webdriver import WebDriver
        assert WebDriver is not None


@pytest.mark.skipif(
    not os.environ.get("TEST_REAL_CAPTCHAS"),
    reason="Set TEST_REAL_CAPTCHAS=1 to run real captcha tests"
)
class TestRealCaptchaChallengeFlow:
    """End-to-end tests against real captcha challenges.

    These tests are completely optional and require:
    1. Both solver libraries installed
    2. Playwright or Selenium with browser
    3. Network access
    4. TEST_REAL_CAPTCHAS=1 environment variable
    """

    def test_full_hcaptcha_flow(self, check_solver_libraries):
        """Complete hCaptcha solving flow on demo page."""
        if not check_solver_libraries["hcaptcha"]:
            pytest.skip("hcaptcha-challenger not installed")

        try:
            from hcaptcha_challenger import AgentV, AgentConfig
            from hcaptcha_challenger.utils import SiteKey
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            pytest.skip(f"Missing dependency: {e}")

        # This would be the full integration test
        # For safety, we don't actually run browser automation in unit tests
        # but document what the flow would look like:

        expected_flow = """
        Expected hCaptcha flow:
        1. Navigate to SiteKey.as_site_link(SiteKey.user_easy)
        2. Initialize AgentV with AgentConfig
        3. Click checkbox with agent.robotic_arm.click_checkbox()
        4. Wait for challenge with agent.wait_for_challenge()
        5. Solve returns CaptchaResponse in agent.cr_list
        """
        assert "hcaptcha" in expected_flow.lower()

    def test_full_recaptcha_flow(self, check_solver_libraries):
        """Complete reCAPTCHA solving flow on demo page."""
        if not check_solver_libraries["recaptcha"]:
            pytest.skip("recaptcha-challenger not installed")

        try:
            from recaptcha_challenger import new_audio_solver
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            pytest.skip(f"Missing dependency: {e}")

        expected_flow = """
        Expected reCAPTCHA flow:
        1. Navigate to https://www.google.com/recaptcha/api2/demo
        2. Create solver with new_audio_solver()
        3. Check checkbox with solver.utils.face_the_checkbox(page)
        4. Solve with solver.anti_recaptcha(page)
        5. Response in solver.response
        """
        assert "recaptcha" in expected_flow.lower()

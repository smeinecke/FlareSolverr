"""Integration tests for pluggable browser backends.

These tests verify that all registered backends can be instantiated,
create a browser context/driver, and perform basic operations.
They require a live FlareSolverr server or can run standalone against
backend factories directly.
"""

import os
import sys
import time
import unittest
import urllib.parse

import pytest
import requests

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from flaresolverr import backends
from flaresolverr.backends.browser_context import get_browser_context

pytestmark = pytest.mark.integration


class TestBackendLoading(unittest.TestCase):
    """Verify backend registration and factory loading."""

    def test_default_backend_registered(self):
        backend = backends.get_backend("undetected_chromedriver")
        assert backend is not None

    def test_playwright_backend_registered(self):
        try:
            backend = backends.get_backend("playwright")
            assert backend is not None
        except ValueError:
            pytest.skip("playwright backend not registered (import may have failed)")

    def test_camoufox_backend_registered(self):
        try:
            backend = backends.get_backend("camoufox")
            assert backend is not None
        except ValueError:
            pytest.skip("camoufox backend not registered (import may have failed)")

    def test_seleniumbase_backend_registered(self):
        try:
            backend = backends.get_backend("seleniumbase")
            assert backend is not None
        except ValueError:
            pytest.skip("seleniumbase backend not registered (import may have failed)")


class TestBackendCreation(unittest.TestCase):
    """Verify each backend can create a driver/BrowserContext.

    These tests spawn real browser processes. They are skipped when
    the required dependencies are not installed.
    """

    @classmethod
    def tearDownClass(cls):
        # Aggressive cleanup: kill any leftover Chrome / chromium processes.
        # This prevents "user data directory already in use" errors in CI.
        if os.name != "nt":
            os.system("pkill -f 'chrome.*--remote-debugging' >/dev/null 2>&1 || true")
            os.system("pkill -f chromium >/dev/null 2>&1 || true")

    def _create_and_navigate(self, backend_name: str) -> None:
        """Helper: create driver, navigate to example.com, verify title."""
        backend = backends.get_backend(backend_name)
        driver = None
        try:
            driver = backend.create_driver(proxy=None, stealth_mode="off")
            ctx = get_browser_context(driver)
            ctx.get("https://example.com")

            title = ctx.title
            source = ctx.page_source
            url = ctx.current_url
            parsed = urllib.parse.urlparse(url)
            assert parsed.hostname == "example.com" and parsed.scheme == "https", f"Unexpected URL: {url}"
            assert "Example Domain" in (title or source), f"Page content unexpected: {title!r}"
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_UNDETECTED_CHROMEDRIVER", "").lower() == "true",
        reason="SKIP_BACKEND_UNDETECTED_CHROMEDRIVER=true",
    )
    def test_undetected_chromedriver_creates_driver(self):
        self._create_and_navigate("undetected_chromedriver")

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_PLAYWRIGHT", "").lower() == "true",
        reason="SKIP_BACKEND_PLAYWRIGHT=true",
    )
    def test_playwright_creates_driver(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            pytest.skip("playwright not installed")
        self._create_and_navigate("playwright")

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_CAMOUFOX", "").lower() == "true",
        reason="SKIP_BACKEND_CAMOUFOX=true",
    )
    def test_camoufox_creates_driver(self):
        try:
            import camoufox  # noqa: F401
        except ImportError:
            pytest.skip("camoufox not installed")
        self._create_and_navigate("camoufox")

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_SELENIUMBASE", "").lower() == "true",
        reason="SKIP_BACKEND_SELENIUMBASE=true",
    )
    def test_seleniumbase_creates_driver(self):
        try:
            import seleniumbase  # noqa: F401
        except ImportError:
            pytest.skip("seleniumbase not installed")
        self._create_and_navigate("seleniumbase")


class TestBackendFeatures(unittest.TestCase):
    """Verify backend-specific feature support and error behavior."""

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_UNDETECTED_CHROMEDRIVER", "").lower() == "true",
        reason="SKIP_BACKEND_UNDETECTED_CHROMEDRIVER=true",
    )
    def test_undetected_chromedriver_cdp_supported(self):
        backend = backends.get_backend("undetected_chromedriver")
        driver = None
        try:
            driver = backend.create_driver(proxy=None, stealth_mode="off")
            ctx = get_browser_context(driver)
            # CDP should work without error
            result = ctx.execute_cdp_cmd("Runtime.evaluate", {"expression": "navigator.userAgent"})
            assert result is not None
            assert "userAgent" in str(result)
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_PLAYWRIGHT", "").lower() == "true",
        reason="SKIP_BACKEND_PLAYWRIGHT=true",
    )
    def test_playwright_cdp_raises(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            pytest.skip("playwright not installed")
        backend = backends.get_backend("playwright")
        driver = None
        try:
            driver = backend.create_driver(proxy=None, stealth_mode="off")
            ctx = get_browser_context(driver)
            with pytest.raises(NotImplementedError, match="not supported by the Playwright backend"):
                ctx.execute_cdp_cmd("Network.enable", {})
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_CAMOUFOX", "").lower() == "true",
        reason="SKIP_BACKEND_CAMOUFOX=true",
    )
    def test_camoufox_cdp_raises(self):
        try:
            import camoufox  # noqa: F401
        except ImportError:
            pytest.skip("camoufox not installed")
        backend = backends.get_backend("camoufox")
        driver = None
        try:
            driver = backend.create_driver(proxy=None, stealth_mode="off")
            ctx = get_browser_context(driver)
            with pytest.raises(NotImplementedError, match="not supported by the Camoufox backend"):
                ctx.execute_cdp_cmd("Network.enable", {})
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass


class TestBrowserContextProtocol(unittest.TestCase):
    """Verify BrowserContext protocol methods work across backends.

    Uses a real browser context from each available backend.
    """

    @classmethod
    def tearDownClass(cls):
        if os.name != "nt":
            os.system("pkill -f 'chrome.*--remote-debugging' >/dev/null 2>&1 || true")
            os.system("pkill -f chromium >/dev/null 2>&1 || true")

    def _test_protocol(self, backend_name: str) -> None:
        backend = backends.get_backend(backend_name)
        driver = None
        try:
            driver = backend.create_driver(proxy=None, stealth_mode="off")
            ctx = get_browser_context(driver)

            # Navigation
            ctx.get("https://example.com")
            parsed = urllib.parse.urlparse(ctx.current_url)
            assert parsed.hostname == "example.com" and parsed.scheme == "https"
            assert "Example Domain" in ctx.title

            # Scripting
            ua = ctx.execute_script("return navigator.userAgent")
            assert isinstance(ua, str) and len(ua) > 0

            # Querying
            h1 = ctx.find_element("tag name", "h1")
            assert h1 is not None
            elements = ctx.find_elements("tag name", "p")
            assert len(elements) >= 1

            # Cookies
            ctx.add_cookie({"name": "test", "value": "123", "domain": "example.com"})
            cookies = ctx.get_cookies()
            assert any(c.get("name") == "test" for c in cookies)
            ctx.delete_cookie("test")
            cookies = ctx.get_cookies()
            assert not any(c.get("name") == "test" for c in cookies)

            # Screenshot
            b64 = ctx.get_screenshot_as_base64()
            assert isinstance(b64, str) and len(b64) > 100

            # Waits
            h1_wait = ctx.wait_for_presence("tag name", "h1", timeout=5.0)
            assert h1_wait is not None

            # Action chain existence (not full interaction)
            actions = ctx.action_chain()
            assert actions is not None
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_UNDETECTED_CHROMEDRIVER", "").lower() == "true",
        reason="SKIP_BACKEND_UNDETECTED_CHROMEDRIVER=true",
    )
    def test_undetected_chromedriver_protocol(self):
        self._test_protocol("undetected_chromedriver")

    @pytest.mark.skipif(
        os.environ.get("SKIP_BACKEND_PLAYWRIGHT", "").lower() == "true",
        reason="SKIP_BACKEND_PLAYWRIGHT=true",
    )
    def test_playwright_protocol(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            pytest.skip("playwright not installed")
        self._test_protocol("playwright")


class TestApiWithBackends(unittest.TestCase):
    """End-to-end API tests against a live FlareSolverr server.

    The server must be started with the desired DRIVER_BACKEND already set.
    These tests verify that request.get and sessions.create work correctly.
    """

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
                time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        try:
            res = requests.post(f"{cls.base_url}/v1", json={"cmd": "sessions.list"}, timeout=10)
            body = res.json()
            for sid in body.get("sessions", []):
                requests.post(
                    f"{cls.base_url}/v1",
                    json={"cmd": "sessions.destroy", "session": sid},
                    timeout=10,
                )
        except Exception:
            pass

    def _post(self, payload: dict, timeout: int = 120):
        res = requests.post(f"{self.base_url}/v1", json=payload, timeout=timeout)
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_request_get_google(self):
        result = self._post({
            "cmd": "request.get",
            "url": "https://www.google.com",
            "maxTimeout": 60000,
        })
        self.assertEqual(result.get("status"), "ok")
        self.assertIn("Google", result.get("solution", {}).get("title", ""))

    def test_session_create_and_destroy(self):
        create_res = self._post({
            "cmd": "sessions.create",
            "session": "test-backend-session",
        })
        self.assertEqual(create_res.get("status"), "ok")

        list_res = self._post({"cmd": "sessions.list"})
        self.assertIn("test-backend-session", list_res.get("sessions", []))

        destroy_res = self._post({
            "cmd": "sessions.destroy",
            "session": "test-backend-session",
        })
        self.assertEqual(destroy_res.get("status"), "ok")

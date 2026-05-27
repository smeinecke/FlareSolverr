import pytest
from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from unittest.mock import MagicMock, patch

from flaresolverr.services.base import ChallengeService
from flaresolverr.services.manager import ServiceManager
from flaresolverr.services.cloudflare import CloudflareService
from flaresolverr.services.ddos_guard import DDoSGuardService
from flaresolverr.services.brave import BraveService


class _FakeService(ChallengeService):
    name = "fake"

    def detect(self, driver: WebDriver) -> bool:
        return True

    def resolve(self, driver: WebDriver) -> None:
        pass


class TestChallengeService:
    def test_service_has_name(self):
        svc = _FakeService()
        assert svc.name == "fake"


class TestServiceManager:
    def test_register_and_get_service(self):
        mgr = ServiceManager()
        svc = _FakeService()
        mgr.register(svc)
        assert mgr.get_service("fake") is svc
        assert mgr.get_service("missing") is None

    def test_detect_returns_none_when_no_services(self):
        mgr = ServiceManager()
        mock_driver = MagicMock()
        assert mgr.detect(mock_driver, ["fake"]) is None

    def test_detect_returns_first_matching_service(self):
        mgr = ServiceManager()

        class SvcA(ChallengeService):
            name = "a"
            def detect(self, driver):
                return False
            def resolve(self, driver):
                pass

        class SvcB(ChallengeService):
            name = "b"
            def detect(self, driver):
                return True
            def resolve(self, driver):
                pass

        mgr.register(SvcA())
        mgr.register(SvcB())
        mock_driver = MagicMock()
        assert mgr.detect(mock_driver, ["a", "b"]) == "b"

    def test_detect_skips_disabled_services(self):
        mgr = ServiceManager()
        svc = _FakeService()
        mgr.register(svc)
        mock_driver = MagicMock()
        assert mgr.detect(mock_driver, ["other"]) is None

    def test_detect_warns_on_unregistered_enabled_service(self, caplog):
        mgr = ServiceManager()
        mock_driver = MagicMock()
        with caplog.at_level("WARNING"):
            result = mgr.detect(mock_driver, ["missing"])
        assert result is None
        assert "not registered" in caplog.text

    def test_resolve_calls_service_resolve(self):
        mgr = ServiceManager()
        svc = _FakeService()
        mgr.register(svc)
        mock_driver = MagicMock()
        mgr.resolve(mock_driver, "fake")
        # No exception means resolve was called (FakeService.resolve is a no-op)

    def test_resolve_raises_on_missing_service(self):
        mgr = ServiceManager()
        mock_driver = MagicMock()
        with pytest.raises(Exception, match="not found"):
            mgr.resolve(mock_driver, "missing")


class TestCloudflareService:
    @pytest.fixture
    def svc(self):
        return CloudflareService()

    def test_name(self, svc):
        assert svc.name == "cloudflare"

    def test_detect_by_title(self, svc):
        driver = MagicMock()
        driver.title = "Just a moment..."
        driver.find_elements.return_value = []
        assert svc.detect(driver) is True

    def test_detect_by_selector(self, svc):
        driver = MagicMock()
        driver.title = "Some Page"
        driver.find_elements.return_value = [MagicMock()]
        assert svc.detect(driver) is True

    def test_detect_no_challenge(self, svc):
        driver = MagicMock()
        driver.title = "Some Page"
        driver.find_elements.return_value = []
        assert svc.detect(driver) is False

    @patch("flaresolverr.services.cloudflare.time.sleep")
    @patch("flaresolverr.services.cloudflare.WebDriverWait")
    @patch("flaresolverr.services.cloudflare._random_delay", return_value=0.01)
    def test_resolve_clicks_verify_and_waits(
        self, mock_delay, mock_wait, mock_sleep, svc
    ):
        driver = MagicMock()
        driver.title = "Just a moment..."
        driver.page_source = ""
        driver.find_elements.return_value = []

        # Make WebDriverWait.until_not raise TimeoutException once, then succeed
        from selenium.common import TimeoutException

        call_count = [0]

        def side_effect(*a, **k):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise TimeoutException()
            return True

        mock_wait_instance = MagicMock()
        mock_wait_instance.until_not.side_effect = side_effect
        mock_wait.return_value = mock_wait_instance

        svc.resolve(driver)
        assert mock_wait_instance.until_not.call_count >= 2


class TestDDoSGuardService:
    @pytest.fixture
    def svc(self):
        return DDoSGuardService()

    def test_name(self, svc):
        assert svc.name == "ddos_guard"

    def test_detect_by_title(self, svc):
        driver = MagicMock()
        driver.title = "DDoS-Guard"
        assert svc.detect(driver) is True

    def test_detect_no_challenge(self, svc):
        driver = MagicMock()
        driver.title = "Some Page"
        assert svc.detect(driver) is False

    @patch("flaresolverr.services.ddos_guard.WebDriverWait")
    def test_resolve_waits_for_redirect(self, mock_wait, svc):
        driver = MagicMock()
        driver.title = "Some Page"
        driver.current_url = "https://example.com"
        driver.page_source = "<html><body>ok</body></html>"

        # Simulate title disappearing after first attempt
        call_count = [0]

        def until_not_side_effect(condition):
            call_count[0] += 1
            if call_count[0] >= 2:
                return True
            raise TimeoutException()

        mock_wait_instance = MagicMock()
        mock_wait_instance.until_not.side_effect = until_not_side_effect
        mock_wait.return_value = mock_wait_instance

        svc.resolve(driver)
        assert mock_wait_instance.until_not.call_count >= 1


class TestBraveService:
    @pytest.fixture
    def svc(self):
        return BraveService()

    def test_name(self, svc):
        assert svc.name == "brave"

    def test_detect_by_url(self, svc):
        driver = MagicMock()
        driver.title = "Some Page"
        driver.current_url = "https://search.brave.com/captcha"
        driver.page_source = ""
        assert svc.detect(driver) is True

    def test_detect_by_page_source(self, svc):
        driver = MagicMock()
        driver.title = "Some Page"
        driver.current_url = "https://example.com"
        driver.page_source = '<script>"page":"/captcha"</script>'
        assert svc.detect(driver) is True

    def test_detect_no_challenge(self, svc):
        driver = MagicMock()
        driver.title = "Some Page"
        driver.current_url = "https://example.com"
        driver.page_source = "<html><body>ok</body></html>"
        assert svc.detect(driver) is False

    @patch("flaresolverr.services.brave.BraveService._is_verify_button_visible")
    @patch("flaresolverr.services.brave.time.sleep")
    @patch("flaresolverr.services.brave.WebDriverWait")
    def test_resolve_clicks_and_waits(self, mock_wait, mock_sleep, mock_is_visible, svc):
        driver = MagicMock()
        driver.current_url = "https://search.brave.com/captcha"
        driver.page_source = ""

        mock_is_visible.return_value = True

        # Redirect away from captcha after a few attempts
        call_count = [0]

        def until_side_effect(func):
            call_count[0] += 1
            if call_count[0] >= 3:
                return True
            return func(driver)

        mock_wait_instance = MagicMock()
        mock_wait_instance.until.side_effect = until_side_effect
        mock_wait.return_value = mock_wait_instance

        svc.resolve(driver)
        assert mock_wait_instance.until.call_count >= 1

    @patch("flaresolverr.services.brave._human_like_click")
    @patch("flaresolverr.services.brave.time.sleep")
    @patch("flaresolverr.services.brave.WebDriverWait")
    def test_resolve_clicks_visible_button(self, mock_wait, mock_sleep, mock_hlc, svc):
        driver = MagicMock()
        driver.current_url = "https://search.brave.com/captcha"
        driver.page_source = ""

        mock_button = MagicMock()
        mock_button.is_displayed.return_value = True
        driver.find_elements.return_value = [mock_button]

        mock_wait_instance = MagicMock()
        mock_wait_instance.until.return_value = True
        mock_wait.return_value = mock_wait_instance

        svc.resolve(driver)
        mock_hlc.assert_called_once_with(driver, mock_button)

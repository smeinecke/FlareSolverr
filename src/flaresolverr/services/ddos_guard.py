"""DDoS-Guard challenge service."""

import logging

logger = logging.getLogger(__name__)
import time

from selenium.webdriver.common.by import By

from flaresolverr.backends.browser_context import BrowserContext
from flaresolverr.services.base import ChallengeService, _wait_for_redirect
from flaresolverr.utils import get_config_browser_wait_timeout

DDOS_GUARD_TITLES = [
    "DDoS-Guard",
]

DDOS_GUARD_CHALLENGE_SELECTORS = [
    'script[src*="/.well-known/ddos-guard/js-challenge/"]',
]

DDOS_GUARD_CAPTCHA_SELECTORS = [
    'script[src*="/.well-known/ddos-guard/ddg-captcha-page/"]',
]


class DDoSGuardManualCaptchaError(RuntimeError):
    """DDoS-Guard escalated to a manual captcha that FlareSolverr cannot solve."""


def _wait_for_title_change(driver: BrowserContext, title: str, timeout: float) -> bool:
    """Wait until the document title no longer matches, ignoring case."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if (driver.title or "").lower() != title.lower():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.1)
    return False


class DDoSGuardService(ChallengeService):
    name = "ddos_guard"

    def _has_selector(self, driver: BrowserContext, selectors: list[str]) -> bool:
        for selector in selectors:
            try:
                if len(driver.find_elements(By.CSS_SELECTOR, selector)) > 0:
                    return True
            except Exception:  # noqa: BLE001
                logger.debug("DDoS-Guard detect: failed to query selector during navigation")
                continue
        return False

    def _raise_if_manual_captcha(self, driver: BrowserContext) -> None:
        if self._has_selector(driver, DDOS_GUARD_CAPTCHA_SELECTORS):
            raise DDoSGuardManualCaptchaError(
                "DDoS-Guard returned its manual captcha page: the automated browser check failed for this IP and browser, and FlareSolverr cannot solve captchas."
            )

    def detect(self, driver: BrowserContext) -> bool:
        try:
            page_title = (driver.title or "").strip()
        except Exception:  # noqa: BLE001
            logger.debug("DDoS-Guard detect: failed to read title during navigation")
            return False
        for title in DDOS_GUARD_TITLES:
            if title.lower() == page_title.lower():
                logger.info("Challenge detected. Title found: " + page_title)
                return True
        if self._has_selector(driver, DDOS_GUARD_CHALLENGE_SELECTORS + DDOS_GUARD_CAPTCHA_SELECTORS):
            logger.info("Challenge detected. DDoS-Guard challenge marker found")
            return True
        return False

    def resolve(self, driver: BrowserContext) -> None:
        self._raise_if_manual_captcha(driver)
        html_element = self._get_html_element(driver)
        if html_element is None:
            return
        browser_wait_timeout = get_config_browser_wait_timeout()
        attempt = 0

        while True:
            attempt += 1
            try:
                for title in DDOS_GUARD_TITLES:
                    logger.debug("Waiting for title (attempt " + str(attempt) + "): " + title)
                    if not _wait_for_title_change(driver, title, browser_wait_timeout):
                        raise TimeoutError("Timed out waiting for DDoS-Guard title to change")
                break
            except Exception:  # noqa: BLE001
                logger.debug("Timeout waiting for selector")
                self._raise_if_manual_captcha(driver)
                html_element = self._get_html_element(driver)
                if html_element is None:
                    continue

        _wait_for_redirect(driver, html_element, browser_wait_timeout)
        self._raise_if_manual_captcha(driver)

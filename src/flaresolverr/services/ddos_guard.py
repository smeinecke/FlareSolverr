"""DDoS-Guard challenge service."""

import logging

logger = logging.getLogger(__name__)

from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.support.expected_conditions import title_is
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr.services.base import ChallengeService, _wait_for_redirect

SHORT_TIMEOUT = 1

DDOS_GUARD_TITLES = [
    "DDoS-Guard",
]


class DDoSGuardService(ChallengeService):
    name = "ddos_guard"

    def detect(self, driver: WebDriver) -> bool:
        try:
            page_title = (driver.title or "").strip()
        except Exception:  # noqa: BLE001
            logger.debug("DDoS-Guard detect: failed to read title during navigation")
            return False
        for title in DDOS_GUARD_TITLES:
            if title.lower() == page_title.lower():
                logger.info("Challenge detected. Title found: " + page_title)
                return True
        return False

    def resolve(self, driver: WebDriver) -> None:
        html_element = self._get_html_element(driver)
        if html_element is None:
            return
        attempt = 0

        while True:
            attempt += 1
            try:
                for title in DDOS_GUARD_TITLES:
                    logger.debug("Waiting for title (attempt " + str(attempt) + "): " + title)
                    WebDriverWait(driver, SHORT_TIMEOUT).until_not(title_is(title))
                break
            except TimeoutException:
                logger.debug("Timeout waiting for selector")
                html_element = self._get_html_element(driver)
                if html_element is None:
                    continue

        _wait_for_redirect(driver, html_element, SHORT_TIMEOUT)

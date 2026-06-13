"""DDoS-Guard challenge service."""

import logging

from selenium.common import TimeoutException
from flaresolverr.backends.browser_context import BrowserContext
from flaresolverr.services.base import ChallengeService, _wait_for_redirect

SHORT_TIMEOUT = 1

DDOS_GUARD_TITLES = [
    "DDoS-Guard",
]


class DDoSGuardService(ChallengeService):
    name = "ddos_guard"

    def detect(self, driver: BrowserContext) -> bool:
        try:
            page_title = (driver.title or "").strip()
        except Exception:
            logging.debug("DDoS-Guard detect: failed to read title during navigation")
            return False
        for title in DDOS_GUARD_TITLES:
            if title.lower() == page_title.lower():
                logging.info("Challenge detected. Title found: " + page_title)
                return True
        return False

    def resolve(self, driver: BrowserContext) -> None:
        html_element = self._get_html_element(driver)
        if html_element is None:
            return
        attempt = 0

        while True:
            attempt += 1
            try:
                for title in DDOS_GUARD_TITLES:
                    logging.debug("Waiting for title (attempt " + str(attempt) + "): " + title)
                    if not driver.wait_for_title_not(title, SHORT_TIMEOUT):
                        raise TimeoutException()
                break
            except Exception:
                logging.debug("Timeout waiting for selector")
                html_element = self._get_html_element(driver)
                if html_element is None:
                    continue

        if html_element is not None:
            _wait_for_redirect(driver, html_element, SHORT_TIMEOUT)

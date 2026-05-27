"""Brave Search challenge service."""

import logging
import re
import time

from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr.services.base import ChallengeService

SHORT_TIMEOUT = 1

BRAVE_VERIFY_XPATHS = [
    "//button[contains(translate(.,'VERIFY','verify'), 'verify')]",
    "//*[@role='button' and contains(translate(.,'VERIFY','verify'), 'verify')]",
    "//a[contains(translate(.,'VERIFY','verify'), 'verify')]",
    "//button[.//*[contains(translate(.,'VERIFY','verify'), 'verify')]]",
]


class BraveService(ChallengeService):
    name = "brave"

    def detect(self, driver: WebDriver) -> bool:
        current_url = driver.current_url or ""
        if not current_url.startswith("https://search.brave.com/"):
            return False

        src = driver.page_source
        if re.search(r"Brave\s+Search\s+decided\sto\s+schedule\sa\s+captcha", src):
            logging.info("Challenge detected. Brave captcha page found.")
            return True
        return False

    def resolve(self, driver: WebDriver) -> None:
        attempt = 0

        while True:
            attempt += 1
            src = driver.page_source
            current_url = driver.current_url or ""
            if not current_url.startswith("https://search.brave.com/"):
                break

            if not re.search(r"Brave\s+Search\s+decided\sto\s+schedule\sa\s+captcha", src):
                break

            logging.debug("Brave challenge active (attempt %d)", attempt)

            button = self._find_clickable_verify_button(driver)
            if button is not None:
                logging.debug("Brave Verify button clickable, clicking...")
                button.click()
                logging.debug("Brave Verify button clicked, waiting for it to become clickable again or challenge to resolve...")
                try:
                    WebDriverWait(driver, SHORT_TIMEOUT).until(
                        lambda d: (
                            not re.search(r"Brave\s+Search\s+decided\sto\s+schedule\sa\s+captcha", d.page_source)
                            or self._find_clickable_verify_button(d) is not None
                        )
                    )
                    # If challenge is resolved, the next loop iteration will break.
                    # If button became clickable again, we loop and click again.
                    continue
                except TimeoutException:
                    logging.debug("Timeout waiting for Brave button state change or challenge resolution, retrying...")
                    continue
            else:
                logging.debug("Brave Verify button not clickable (not visible or disabled), waiting...")
                time.sleep(2)
                continue

    def _find_clickable_verify_button(self, driver: WebDriver):
        """Find a verify button that is visible and not disabled."""
        try:
            for xpath in BRAVE_VERIFY_XPATHS:
                for el in driver.find_elements(By.XPATH, xpath):
                    if el.is_displayed() and not el.get_attribute("disabled"):
                        return el
            return None
        except Exception:
            return None

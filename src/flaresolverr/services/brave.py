"""Brave Search challenge service."""

import logging
import re
import time

from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr.services.base import ChallengeService

SHORT_TIMEOUT = 10

BRAVE_CAPTCHA_RE = re.compile(r"Brave\s+Search\s+decided\s+to\s+schedule\s+a\s+captcha")

BRAVE_VERIFY_XPATHS = [
    # Text-based matchers (need full-alphabet translate for case-insensitive)
    "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'verify')]",
    "//*[@role='button' and contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'verify')]",
    "//a[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'verify')]",
    "//button[.//*[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'verify')]]",
    # Also match "Try again" button on verification-failed state
    "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'try again')]",
    "//*[@role='button' and contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'try again')]",
    # Structure-based matchers (work even before text renders)
    "//div[contains(@class,'captcha-actions')]//button[not(contains(@class,'default-captcha-button'))]",
    "//div[contains(@class,'captcha-button-wrap')]//button",
]


class BraveService(ChallengeService):
    name = "brave"

    def detect(self, driver: WebDriver) -> bool:
        try:
            current_url = driver.current_url or ""
            if not current_url.startswith("https://search.brave.com/"):
                return False

            if self._page_has_captcha(driver):
                logging.info("Challenge detected. Brave captcha page found.")
                return True
            return False
        except Exception:
            logging.debug("Brave detect failed due to navigation in progress, assuming not detected")
            return False

    def resolve(self, driver: WebDriver) -> None:
        attempt = 0

        while True:
            attempt += 1
            try:
                current_url = driver.current_url or ""
            except Exception:
                logging.debug("Brave resolve: page navigation in progress, breaking")
                break
            if not current_url.startswith("https://search.brave.com/"):
                break

            if not self._page_has_captcha(driver):
                break

            logging.debug("Brave challenge active (attempt %d)", attempt)

            button = self._find_clickable_verify_button(driver)
            if button is not None:
                logging.debug("Brave Verify/Try again button clickable, clicking...")
                button.click()
                logging.debug("Brave button clicked, waiting for it to become clickable again or challenge to resolve...")
                try:
                    WebDriverWait(driver, SHORT_TIMEOUT).until(lambda d: not self._page_has_captcha(d) or self._find_clickable_verify_button(d) is not None)
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

    def _page_has_captcha(self, driver: WebDriver) -> bool:
        try:
            return bool(BRAVE_CAPTCHA_RE.search(driver.page_source))
        except Exception:
            return False

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

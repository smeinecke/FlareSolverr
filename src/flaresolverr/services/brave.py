"""Brave Search challenge service."""

import logging
import re
import time

from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr import utils
from flaresolverr.services.base import ChallengeService, _wait_for_redirect

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

    def _safe_page_source(self, driver: WebDriver) -> str:
        """Safely get a snippet of page source for debugging."""
        try:
            src = driver.page_source
            return src[:2000] if src else "<empty>"
        except Exception as e:
            return f"<unavailable: {e}>"

    def _safe_current_url(self, driver: WebDriver) -> str:
        """Safely get current URL for debugging."""
        try:
            return driver.current_url or "<empty>"
        except Exception as e:
            return f"<unavailable: {e}>"

    def resolve(self, driver: WebDriver) -> None:
        logging.debug("Brave resolve: starting")
        html_element = self._get_html_element(driver)
        if html_element is None:
            logging.debug("Brave resolve: no html element at entry, aborting")
            return
        attempt = 0

        while True:
            attempt += 1
            safe_url = self._safe_current_url(driver)
            logging.debug("Brave resolve: attempt %d, url=%s", attempt, safe_url)
            try:
                current_url = utils.retry_driver_read(lambda: driver.current_url or "")
            except Exception as e:
                logging.debug("Brave resolve: current_url failed after retries (%s), breaking", e)
                logging.debug("Brave resolve: page_source at break: %s", self._safe_page_source(driver))
                break
            if not current_url.startswith("https://search.brave.com/"):
                logging.debug("Brave resolve: left brave.com (%s), breaking", current_url)
                logging.debug("Brave resolve: page_source at break: %s", self._safe_page_source(driver))
                break

            has_captcha = self._page_has_captcha(driver)
            logging.debug("Brave resolve: attempt %d, has_captcha=%s", attempt, has_captcha)
            if not has_captcha:
                logging.debug("Brave resolve: no captcha detected, breaking")
                logging.debug("Brave resolve: page_source at break: %s", self._safe_page_source(driver))
                break

            logging.debug("Brave resolve: page_source (has_captcha=True): %s", self._safe_page_source(driver))
            button = self._find_clickable_verify_button(driver)
            if button is not None:
                logging.debug("Brave resolve: clickable button found, clicking...")
                try:
                    button.click()
                    logging.debug("Brave resolve: button clicked")
                except Exception as e:
                    logging.debug("Brave resolve: button.click() failed (%s), retrying...", e)
                    logging.debug("Brave resolve: page_source after click failure: %s", self._safe_page_source(driver))
                    html_element = self._get_html_element(driver)
                    if html_element is None:
                        logging.debug("Brave resolve: no html element after click failure, breaking")
                        break
                    continue
                try:
                    WebDriverWait(driver, SHORT_TIMEOUT).until(lambda d: not self._page_has_captcha(d) or self._find_clickable_verify_button(d) is not None)
                except TimeoutException:
                    logging.debug("Brave resolve: timeout waiting for state change, retrying...")
                    logging.debug("Brave resolve: page_source after timeout: %s", self._safe_page_source(driver))
                html_element = self._get_html_element(driver)
                if html_element is None:
                    logging.debug("Brave resolve: no html element after wait, continuing")
                    continue
            else:
                logging.debug("Brave resolve: no clickable button, sleeping 2s")
                logging.debug("Brave resolve: page_source (no button): %s", self._safe_page_source(driver))
                time.sleep(2)
                continue

        logging.debug("Brave resolve: waiting for redirect stabilization")
        _wait_for_redirect(driver, html_element, SHORT_TIMEOUT)
        logging.debug("Brave resolve: finished")

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

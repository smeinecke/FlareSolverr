"""Brave Search challenge service."""

import logging
import re
import time
from typing import Any

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

    def resolve(self, driver: WebDriver) -> None:
        html_element = self._get_html_element(driver)
        if html_element is None:
            return
        attempt = 0

        while True:
            attempt += 1
            try:
                current_url = utils.retry_driver_read(lambda: driver.current_url or "")
            except Exception:
                break
            if not current_url.startswith("https://search.brave.com/"):
                break

            has_captcha = self._page_has_captcha(driver)
            if not has_captcha:
                break

            driver._flaresolverr_brave_debug = self._collect_debug_state(driver, attempt)
            button = self._find_clickable_verify_button(driver)
            if button is not None:
                try:
                    button.click()
                except Exception:
                    html_element = self._get_html_element(driver)
                    if html_element is None:
                        break
                    continue
                try:
                    WebDriverWait(driver, SHORT_TIMEOUT).until(lambda d: not self._page_has_captcha(d) or self._find_clickable_verify_button(d) is not None)
                except TimeoutException:
                    pass
                html_element = self._get_html_element(driver)
                if html_element is None:
                    continue
            else:
                time.sleep(2)
                continue

        _wait_for_redirect(driver, html_element, SHORT_TIMEOUT)

    def _page_has_captcha(self, driver: WebDriver) -> bool:
        try:
            return bool(BRAVE_CAPTCHA_RE.search(driver.page_source))
        except Exception:
            return False

    def _collect_debug_state(self, driver: WebDriver, attempt: int) -> dict[str, Any]:
        """Collect debug state for Brave challenge resolution."""
        state: dict[str, Any] = {"attempts": attempt}
        try:
            state["url"] = driver.current_url or ""
        except Exception:
            state["url"] = ""
        try:
            state["title"] = driver.title or ""
        except Exception:
            state["title"] = ""
        try:
            html = driver.page_source or ""
            state["captcha_present"] = bool(BRAVE_CAPTCHA_RE.search(html))
            state["page_source_snippet"] = html[:500]
        except Exception:
            state["captcha_present"] = False
            state["page_source_snippet"] = ""
        state["button_found"] = self._find_clickable_verify_button(driver) is not None
        return state

    def get_debug_info(self, driver: WebDriver) -> dict[str, Any] | None:
        return getattr(driver, "_flaresolverr_brave_debug", None)

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

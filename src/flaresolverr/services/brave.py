"""Brave Search challenge service."""

import logging
import time

from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr.services.base import ChallengeService
from flaresolverr.utils import _human_like_click

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
        src = driver.page_source
        if "/captcha" in current_url:
            logging.info("Challenge detected. Brave captcha URL found: %s", current_url)
            return True
        if '"page":"/captcha"' in src:
            logging.info("Challenge detected. Brave captcha page data found.")
            return True
        if "Your request has been flagged as being suspicious" in src or "Brave Search decided to schedule a captcha" in src:
            logging.info("Challenge detected. Brave captcha page found.")
            return True
        return False

    def resolve(self, driver: WebDriver) -> None:
        attempt = 0
        last_verify_click_ts = 0.0
        click_cooldown_seconds = 10.0

        while True:
            attempt += 1
            src = driver.page_source
            current_url = driver.current_url or ""

            is_brave_challenge = (
                "/captcha" in current_url or
                '"page":"/captcha"' in src or
                "Your request has been flagged as being suspicious" in src or
                "Brave Search decided to schedule a captcha" in src
            )

            if not is_brave_challenge:
                break

            logging.debug("Brave challenge active (attempt %d)", attempt)

            if self._is_verify_button_visible(driver):
                now = time.time()
                if now - last_verify_click_ts >= click_cooldown_seconds:
                    logging.debug("Brave Verify button visible, clicking...")
                    self._click_verify(driver)
                    last_verify_click_ts = now
                else:
                    remaining = click_cooldown_seconds - (now - last_verify_click_ts)
                    logging.debug("Skipping Brave verify click due to cooldown (%.1fs remaining)", remaining)
                try:
                    WebDriverWait(driver, SHORT_TIMEOUT).until(
                        lambda d: not (
                            "/captcha" in (d.current_url or "") or
                            '"page":"/captcha"' in d.page_source or
                            "Your request has been flagged as being suspicious" in d.page_source
                        )
                    )
                    logging.debug("Brave challenge resolved, no longer on captcha page.")
                    break
                except TimeoutException:
                    logging.debug("Timeout waiting for Brave captcha state to end, retrying...")
                    continue
            else:
                logging.debug("Brave Verify button not yet visible, waiting...")
                time.sleep(2)
                continue

    def _is_verify_button_visible(self, driver: WebDriver) -> bool:
        try:
            for xpath in BRAVE_VERIFY_XPATHS:
                for el in driver.find_elements(By.XPATH, xpath):
                    if el.is_displayed():
                        return True
            return False
        except Exception:
            return False

    def _click_verify(self, driver: WebDriver) -> None:
        try:
            logging.debug("Try to find the Brave 'Verify' button...")
            button = None
            for xpath in BRAVE_VERIFY_XPATHS:
                elems = driver.find_elements(By.XPATH, xpath)
                for el in elems:
                    if el.is_displayed():
                        button = el
                        logging.debug("Brave 'Verify' button found via xpath: %s", xpath)
                        break
                if button:
                    break
            if button:
                _human_like_click(driver, button)
                logging.debug("The Brave 'Verify' button found and clicked!")
        except Exception:
            logging.debug("The Brave 'Verify' button not found on the page.")

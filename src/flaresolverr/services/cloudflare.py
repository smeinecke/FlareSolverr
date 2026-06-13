"""Cloudflare challenge service."""

import logging
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from flaresolverr.backends.browser_context import BrowserContext
from flaresolverr.services.base import ChallengeService, _wait_for_redirect
from flaresolverr.utils import _human_like_click, _random_delay

SHORT_TIMEOUT = 1
HARD_BLOCK_TEXT = "Incompatible browser extension or network configuration"

CLOUDFLARE_TITLES = [
    "Just a moment...",
    "Nur einen Moment…",
]

CLOUDFLARE_SELECTORS = [
    "#cf-challenge-running",
    ".ray_id",
    ".attack-box",
    "#cf-please-wait",
    "#challenge-spinner",
    "#trk_jschal_js",
    "#turnstile-wrapper",
    ".lds-ring",
    "td.info #js_info",
    "div.vc div.text-box h2",
]


class CloudflareService(ChallengeService):
    name = "cloudflare"

    def detect(self, driver: BrowserContext) -> bool:
        try:
            page_title = (driver.title or "").strip()
        except Exception:
            logging.debug("Cloudflare detect: failed to read title during navigation")
            return False
        for title in CLOUDFLARE_TITLES:
            if title.lower() == page_title.lower():
                logging.info("Challenge detected. Title found: " + page_title)
                return True
        for selector in CLOUDFLARE_SELECTORS:
            try:
                found_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            except Exception:
                logging.debug("Cloudflare detect: failed to query selector during navigation")
                return False
            if len(found_elements) > 0:
                logging.info("Challenge detected. Selector found: " + selector)
                return True
        return False

    def resolve(self, driver: BrowserContext) -> None:
        html_element = self._get_html_element(driver)
        if html_element is None:
            return
        attempt = 0
        last_verify_click_ts = 0.0
        click_cooldown_seconds = 10.0

        while True:
            attempt += 1
            try:
                for title in CLOUDFLARE_TITLES:
                    logging.debug("Waiting for title (attempt " + str(attempt) + "): " + title)
                    if driver.wait_for_title_not(title, SHORT_TIMEOUT):
                        continue
                for selector in CLOUDFLARE_SELECTORS:
                    logging.debug("Waiting for selector (attempt " + str(attempt) + "): " + selector)
                    if driver.wait_for_absence(By.CSS_SELECTOR, selector, SHORT_TIMEOUT):
                        continue
                break
            except Exception:
                logging.debug("Timeout waiting for selector")
                page_source = ""
                try:
                    page_source = driver.page_source
                except Exception:
                    logging.debug("Could not read page source during navigation")
                if HARD_BLOCK_TEXT in page_source:
                    raise Exception("Cloudflare hard block: Incompatible browser extension or network configuration")
                now = time.time()
                if self._should_attempt_verify_click(driver):
                    if now - last_verify_click_ts >= click_cooldown_seconds:
                        self._click_verify(driver)
                        last_verify_click_ts = now
                    else:
                        remaining = click_cooldown_seconds - (now - last_verify_click_ts)
                        logging.debug("Skipping verify click due to cooldown (%.1fs remaining)", remaining)
                else:
                    logging.debug("Skipping verify click: challenge appears to be in automatic verification mode")
                html_element = self._get_html_element(driver)
                if html_element is None:
                    continue

        if html_element is not None:
            _wait_for_redirect(driver, html_element, SHORT_TIMEOUT)

    def _should_attempt_verify_click(self, driver: BrowserContext) -> bool:
        try:
            if driver.find_elements(By.XPATH, "//input[@type='button' and @value='Verify you are human']"):
                return True

            src = driver.page_source
            if "Verifying you are human. This may take a few seconds." in src:
                logging.debug("_should_attempt_verify_click: False (Verifying text present)")
                return False

            if "Verification successful. Waiting for" in src:
                is_hidden = driver.execute_script(
                    "var el = document.getElementById('ijUz0');if (!el) return false;return getComputedStyle(el).display === 'none';"
                )
                if not is_hidden:
                    logging.debug("_should_attempt_verify_click: False (Verification successful visible)")
                    return False

            markers = driver.find_elements(
                By.CSS_SELECTOR,
                "#turnstile-wrapper, iframe[src*='turnstile'], iframe[src*='challenges.cloudflare.com']",
            )
            if markers:
                return True

            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            iframe_srcs = [f.get_attribute("src") or "(no src)" for f in iframes[:5]]
            logging.debug(
                "_should_attempt_verify_click: False (no markers). iframes=%s, page_snippet=%r",
                iframe_srcs,
                src[src.find("<body") : src.find("<body") + 800] if "<body" in src else src[:800],
            )
            return False
        except Exception as e:
            logging.debug("_should_attempt_verify_click: exception %s", e)
            return False

    def _click_verify(self, driver: BrowserContext, num_tabs: int = 1) -> None:
        try:
            logging.debug("Try to find the Cloudflare verify checkbox...")
            actions = driver.action_chain()
            actions.pause(_random_delay(4.0, 6.0))
            for _ in range(num_tabs):
                actions.send_keys(Keys.TAB).pause(_random_delay(0.08, 0.15))
            actions.pause(_random_delay(0.8, 1.2))
            actions.send_keys(Keys.SPACE).perform()
            logging.debug(f"Cloudflare verify checkbox clicked after {num_tabs} tabs!")
        except Exception:
            logging.debug("Cloudflare verify checkbox not found on the page.")
        finally:
            driver.switch_to_default_content()

        try:
            logging.debug("Try to find the Cloudflare 'Verify you are human' button...")
            button = driver.find_element(
                by=By.XPATH,
                value="//input[@type='button' and @value='Verify you are human']",
            )
            if button:
                _human_like_click(driver, button)
                logging.debug("The Cloudflare 'Verify you are human' button found and clicked!")
        except Exception:
            logging.debug("The Cloudflare 'Verify you are human' button not found on the page.")

        time.sleep(_random_delay(1.5, 2.5))

"""Cloudflare challenge service."""

import logging

logger = logging.getLogger(__name__)
import time
from typing import Any

from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.expected_conditions import presence_of_element_located, title_is
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr.services.base import ChallengeService, _wait_for_redirect
from flaresolverr.utils import (
    _human_like_click,
    _random_delay,
    collect_failure_evidence,
    get_config_browser_wait_timeout,
    get_config_challenge_probe_grace,
)

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

    def detect(self, driver: WebDriver) -> bool:
        try:
            page_title = (driver.title or "").strip()
        except Exception:  # noqa: BLE001
            logger.debug("Cloudflare detect: failed to read title during navigation")
            return False
        for title in CLOUDFLARE_TITLES:
            if title.lower() == page_title.lower():
                logger.info("Challenge detected. Title found: " + page_title)
                return True
        for selector in CLOUDFLARE_SELECTORS:
            try:
                found_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            except Exception:  # noqa: BLE001
                logger.debug("Cloudflare detect: failed to query selector during navigation")
                return False
            if len(found_elements) > 0:
                logger.info("Challenge detected. Selector found: " + selector)
                return True
        return False

    def resolve(self, driver: WebDriver) -> None:
        html_element = self._get_html_element(driver)
        if html_element is None:
            return
        browser_wait_timeout = get_config_browser_wait_timeout()
        attempt = 0
        resolve_start = time.time()
        last_verify_click_ts = 0.0
        click_cooldown_seconds = 10.0
        # Challenge state probing forces synchronous layout and walks the whole
        # DOM on the challenge page every poll — measured to stall Turnstile's
        # automatic verification (challenge never resolved while probing ran,
        # resolved in ~4s without it). Give auto-verification an undisturbed
        # window before probing or clicking; interactive challenges wait for
        # input anyway, so the delay costs nothing there.
        probe_grace_seconds = get_config_challenge_probe_grace()

        while True:
            attempt += 1
            try:
                for title in CLOUDFLARE_TITLES:
                    logger.debug("Waiting for title (attempt " + str(attempt) + "): " + title)
                    WebDriverWait(driver, browser_wait_timeout).until_not(title_is(title))
                for selector in CLOUDFLARE_SELECTORS:
                    logger.debug("Waiting for selector (attempt " + str(attempt) + "): " + selector)
                    WebDriverWait(driver, browser_wait_timeout).until_not(presence_of_element_located((By.CSS_SELECTOR, selector)))
                break
            except TimeoutException:
                logger.debug("Timeout waiting for selector")
                page_source = ""
                try:
                    page_source = driver.page_source
                except Exception:  # noqa: BLE001
                    logger.debug("Could not read page source during navigation")
                if HARD_BLOCK_TEXT in page_source:
                    raise RuntimeError("Cloudflare hard block: Incompatible browser extension or network configuration")
                now = time.time()
                if now - resolve_start < probe_grace_seconds:
                    logger.debug(
                        "Skipping challenge-state probe: grace period (%.1fs remaining)",
                        probe_grace_seconds - (now - resolve_start),
                    )
                elif self._should_attempt_verify_click(driver):
                    if now - last_verify_click_ts >= click_cooldown_seconds:
                        self._click_verify(driver)
                        last_verify_click_ts = now
                        # Dispatch alone is not activation — re-probe so the log
                        # records whether the click actually changed state.
                        try:
                            after = self._probe_challenge_state(driver)
                            if isinstance(after, dict):
                                if after.get("successTextVisible"):
                                    logger.info("Verify click produced a visible success state")
                                elif after.get("verifyButton") or after.get("challengeIframe"):
                                    logger.debug("Verify click dispatched; interactive control still present")
                                else:
                                    logger.debug("Verify click dispatched; control gone, waiting for transition")
                        except Exception:  # noqa: BLE001
                            logger.debug("Post-click state probe failed")
                    else:
                        remaining = click_cooldown_seconds - (now - last_verify_click_ts)
                        logger.debug("Skipping verify click due to cooldown (%.1fs remaining)", remaining)
                else:
                    logger.debug("Skipping verify click: challenge appears to be in automatic verification mode")
                html_element = self._get_html_element(driver)
                if html_element is None:
                    continue

        _wait_for_redirect(driver, html_element, browser_wait_timeout)

    def get_debug_info(self, driver: WebDriver) -> dict[str, Any] | None:
        """Collect a bounded failure record for Cloudflare challenge timeouts.

        Includes the generic browser/response evidence plus Cloudflare-specific
        state from window._cf_chl_opt and the rendered iframe/error elements.
        Cookie values and POST bodies are never included.
        """
        info = collect_failure_evidence(driver)

        def _safe(fn, default=None):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                return default

        cf_opt = _safe(lambda: driver.execute_script("return window._cf_chl_opt || null"))
        if isinstance(cf_opt, dict):
            info["cfChallenge"] = {
                "cType": cf_opt.get("cType"),
                "cRay": cf_opt.get("cRay"),
                "cNounce": cf_opt.get("cNounce"),
                "cvId": cf_opt.get("cvId"),
                "md": cf_opt.get("md"),
            }
        iframe_srcs = _safe(lambda: [f.get_attribute("src") for f in driver.find_elements(By.TAG_NAME, "iframe")], [])
        info["iframes"] = [src for src in (iframe_srcs or []) if src][:10]
        info["visibleErrorText"] = _safe(
            lambda: driver.execute_script(
                """
                var texts = [];
                var walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
                var node;
                while (node = walker.nextNode()) {
                    var t = node.textContent.trim();
                    if (t.length > 4 && t.length < 200 && node.parentElement && node.parentElement.offsetParent !== null) {
                        texts.push(t);
                    }
                    if (texts.length >= 15) break;
                }
                return texts;
                """
            ),
            [],
        )
        info["challengePresent"] = _safe(lambda: self.detect(driver), None)
        return info

    def _probe_challenge_state(self, driver: WebDriver) -> dict[str, Any] | None:
        """Evaluate the visible challenge DOM state in one round-trip.

        All checks are visibility-aware: hidden template markup (which always
        contains strings like "Verification successful. Waiting for") does not
        count — only rendered, non-zero-size, non-display:none elements.
        """
        return driver.execute_script(
            """
            function isVisible(el) {
                if (!el) { return false; }
                var rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) { return false; }
                var style = getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            }
            function hasVisibleLeafText(marker) {
                var els = document.querySelectorAll('div, span, p, h1, h2, h3, td, section');
                for (var i = 0; i < els.length; i++) {
                    var el = els[i];
                    if (el.children.length === 0 && el.textContent.indexOf(marker) !== -1 && isVisible(el)) {
                        return true;
                    }
                }
                return false;
            }
            var verifyButton = document.querySelector("input[type='button'][value='Verify you are human']");
            var challengeIframes = document.querySelectorAll(
                "iframe[src*='challenges.cloudflare.com'], iframe[src*='turnstile']"
            );
            var visibleIframe = false;
            for (var i = 0; i < challengeIframes.length; i++) {
                if (isVisible(challengeIframes[i])) { visibleIframe = true; break; }
            }
            var wrapper = document.getElementById('turnstile-wrapper');
            var wrapperHasControl = !!(wrapper && isVisible(wrapper) && wrapper.querySelector('iframe, input'));
            var iframeSrcs = [];
            var allIframes = document.querySelectorAll('iframe');
            for (var j = 0; j < allIframes.length && j < 5; j++) {
                iframeSrcs.push(allIframes[j].getAttribute('src') || '(no src)');
            }
            return {
                verifyButton: !!(verifyButton && isVisible(verifyButton)),
                challengeIframe: visibleIframe,
                turnstileWrapperWithControl: wrapperHasControl,
                verifyingTextVisible: hasVisibleLeafText('Verifying you are human'),
                successTextVisible: hasVisibleLeafText('Verification successful'),
                iframeSrcs: iframeSrcs
            };
            """
        )

    def _should_attempt_verify_click(self, driver: WebDriver) -> bool:
        try:
            state = self._probe_challenge_state(driver)
        except Exception as e:  # noqa: BLE001
            logger.debug("_should_attempt_verify_click: exception %s", e)
            return False
        if not isinstance(state, dict):
            return False

        # A visible success state means the challenge already passed — never click.
        if state.get("successTextVisible"):
            logger.debug("_should_attempt_verify_click: False (visible success state)")
            return False

        # A rendered interactive control means the challenge wants a click.
        if state.get("verifyButton") or state.get("challengeIframe") or state.get("turnstileWrapperWithControl"):
            logger.debug("_should_attempt_verify_click: True (interactive control present)")
            return True

        # Visible "Verifying..." text with no control = automatic managed
        # challenge; blind clicks would hit arbitrary page elements.
        if state.get("verifyingTextVisible"):
            logger.debug("_should_attempt_verify_click: False (automatic verification in progress)")
            return False

        logger.debug("_should_attempt_verify_click: False (no markers). iframes=%s", state.get("iframeSrcs"))
        return False

    def _click_verify(self, driver: WebDriver, num_tabs: int = 1) -> None:
        try:
            logger.debug("Try to find the Cloudflare verify checkbox...")
            actions = ActionChains(driver)
            actions.pause(_random_delay(4.0, 6.0))
            for _ in range(num_tabs):
                actions.send_keys(Keys.TAB).pause(_random_delay(0.08, 0.15))
            actions.pause(_random_delay(0.8, 1.2))
            actions.send_keys(Keys.SPACE).perform()
            logger.debug(f"Cloudflare verify checkbox clicked after {num_tabs} tabs!")
        except Exception:  # noqa: BLE001
            logger.debug("Cloudflare verify checkbox not found on the page.")
        finally:
            driver.switch_to.default_content()

        try:
            logger.debug("Try to find the Cloudflare 'Verify you are human' button...")
            button = driver.find_element(
                by=By.XPATH,
                value="//input[@type='button' and @value='Verify you are human']",
            )
            if button:
                _human_like_click(driver, button)
                logger.debug("The Cloudflare 'Verify you are human' button found and clicked!")
        except Exception:  # noqa: BLE001
            logger.debug("The Cloudflare 'Verify you are human' button not found on the page.")

        time.sleep(_random_delay(1.5, 2.5))

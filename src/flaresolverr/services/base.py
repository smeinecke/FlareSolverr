"""Base class for challenge services."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from selenium.webdriver.common.by import By

from flaresolverr.backends.browser_context import BrowserContext, Element

logger = logging.getLogger(__name__)


def _wait_for_redirect(driver: BrowserContext, html_element: Element | None, timeout: int = 1) -> None:
    """Wait for the page to redirect by checking staleness of the html element."""
    if html_element is None:
        return
    logger.debug("Waiting for redirect")
    try:
        driver.wait_for_staleness(html_element, timeout)
    except Exception:  # noqa: BLE001
        logger.debug("Timeout waiting for redirect")


class ChallengeService(ABC):
    """Abstract base class for challenge detection/resolution services."""

    name: str = "base"

    @abstractmethod
    def detect(self, driver: BrowserContext) -> bool:
        """Check if this service's challenge is present on the page."""

    @abstractmethod
    def resolve(self, driver: BrowserContext) -> None:
        """Attempt to resolve the challenge. Raises Exception on failure."""

    def _get_html_element(self, driver: BrowserContext) -> Element | None:
        """Get the <html> element, returning None if navigation is in progress."""
        try:
            return driver.find_element(By.TAG_NAME, "html")
        except Exception:  # noqa: BLE001
            logger.debug("Could not find html element during navigation")
            return None

    def get_debug_info(self, driver: BrowserContext, stealth_mode: str | None = None) -> dict[str, Any] | None:
        """Return debug state dict for this service, or None if not available."""
        return None

"""Base class for challenge services."""

import logging

logger = logging.getLogger(__name__)
from abc import ABC, abstractmethod
from typing import Any

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import staleness_of
from selenium.webdriver.support.wait import WebDriverWait


def _wait_for_redirect(driver: WebDriver, html_element, timeout: int = 1) -> None:
    """Wait for the page to redirect by checking staleness of the html element."""
    logger.debug("Waiting for redirect")
    try:
        WebDriverWait(driver, timeout).until(staleness_of(html_element))
    except Exception:  # noqa: BLE001
        logger.debug("Timeout waiting for redirect")


class ChallengeService(ABC):
    """Abstract base class for challenge detection/resolution services."""

    name: str = "base"

    @abstractmethod
    def detect(self, driver: WebDriver) -> bool:
        """Check if this service's challenge is present on the page."""

    @abstractmethod
    def resolve(self, driver: WebDriver) -> None:
        """Attempt to resolve the challenge. Raises Exception on failure."""

    def _get_html_element(self, driver: WebDriver):
        """Get the <html> element, returning None if navigation is in progress."""
        try:
            return driver.find_element(By.TAG_NAME, "html")
        except Exception:  # noqa: BLE001
            logger.debug("Could not find html element during navigation")
            return None

    def get_debug_info(self, driver: WebDriver) -> dict[str, Any] | None:
        """Return debug state dict for this service, or None if not available."""
        return None

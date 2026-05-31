"""Base class for challenge services."""

import logging

from abc import ABC, abstractmethod

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import staleness_of
from selenium.webdriver.support.wait import WebDriverWait


def _wait_for_redirect(driver: WebDriver, html_element, timeout: int = 1) -> None:
    """Wait for the page to redirect by checking staleness of the html element."""
    logging.debug("Waiting for redirect")
    try:
        WebDriverWait(driver, timeout).until(staleness_of(html_element))
    except Exception:
        logging.debug("Timeout waiting for redirect")


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
        except Exception:
            logging.debug("Could not find html element during navigation")
            return None

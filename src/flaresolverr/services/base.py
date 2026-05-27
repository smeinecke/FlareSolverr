"""Base class for challenge services."""

from abc import ABC, abstractmethod

from selenium.webdriver.chrome.webdriver import WebDriver


class ChallengeService(ABC):
    """Abstract base class for challenge detection/resolution services."""

    name: str = "base"

    @abstractmethod
    def detect(self, driver: WebDriver) -> bool:
        """Check if this service's challenge is present on the page."""

    @abstractmethod
    def resolve(self, driver: WebDriver) -> None:
        """Attempt to resolve the challenge. Raises Exception on failure."""

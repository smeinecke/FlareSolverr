from typing import Any, Protocol

from selenium.webdriver.chrome.webdriver import WebDriver


class BackendBase(Protocol):
    """Protocol for browser backend implementations."""

    def create_driver(self, proxy: dict[str, Any] | None, stealth_mode: str) -> WebDriver:
        """Create and return a configured WebDriver instance."""
        ...

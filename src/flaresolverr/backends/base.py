from typing import Any, Protocol

from selenium.webdriver.chrome.webdriver import WebDriver

from flaresolverr.backends.browser_context import BrowserContext


class BackendBase(Protocol):
    """Protocol for browser backend implementations."""

    def create_driver(self, proxy: dict[str, Any] | None, stealth_mode: str) -> WebDriver | BrowserContext:
        """Create and return a configured WebDriver or BrowserContext instance."""
        ...

"""Default Chromium backend (undetected-chromedriver / custom Chromium).

The actual implementation lives in ``utils.get_webdriver()`` so that the
existing stealth, proxy, logging, lifecycle and cleanup behavior is preserved.
This class only satisfies the :class:`BackendBase` registry interface for the
default backend names ``undetected_chromedriver`` and ``custom_chromium``.
"""

from typing import Any

from selenium.webdriver.chrome.webdriver import WebDriver

from flaresolverr import utils
from flaresolverr.backends.browser_context import BrowserContext


class UndetectedChromeBackend:
    """Delegate to ``utils.get_webdriver()``'s built-in Chromium path."""

    def create_driver(self, proxy: dict[str, Any] | None, stealth_mode: str) -> WebDriver | BrowserContext:
        # utils.get_webdriver() only delegates to this registry for non-Chromium
        # backend names; for the default names it runs the full built-in path.
        return utils.get_webdriver(proxy=proxy, stealth_mode=stealth_mode)

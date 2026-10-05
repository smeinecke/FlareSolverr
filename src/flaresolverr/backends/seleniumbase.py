import logging
import os
import urllib.parse
from typing import Any

from flaresolverr import utils

logger = logging.getLogger(__name__)


class SeleniumBaseBackend:
    def create_driver(self, proxy: dict[str, Any] | None, stealth_mode: str) -> Any:
        logger.debug("Launching web browser (seleniumbase)...")
        try:
            from seleniumbase import Driver  # pyright: ignore[reportMissingImports]
        except ImportError as e:
            raise ImportError(
                "seleniumbase is not installed. Install with: pip install 'seleniumbase>=4.30' "
                "(it pins selenium==4.49.x and cannot share the main dependency set)"
            ) from e

        # chromium_arg accepts a list — a comma-joined string would corrupt
        # args containing commas (e.g. --stealth-navigator-languages=en-US,en).
        chromium_args = ["--disable-dev-shm-usage", "--disable-setuid-sandbox", "--no-zygote"]

        kwargs: dict[str, Any] = {
            "uc": stealth_mode != utils.STEALTH_MODE_OFF,
            "headless": utils.get_config_headless(),
            "window_size": "1920,1080",
            "no_sandbox": True,
            "chromium_arg": chromium_args,
            # Enable the ChromeDriver performance/browser logs so document
            # evidence (status/headers) and sessions.network work like on the
            # other chromedriver backends.
            "log_cdp_events": True,
        }

        # Note: binary_location=<custom Chromium> was tried and abandoned —
        # SB's UC launch path cannot bring it up (chromedriver never reaches
        # the debug port even though the binary launches standalone). The
        # post-launch normalization below still fixes the biggest leaks:
        # HeadlessChrome UA and the missing stealth JS.

        if proxy is not None and "url" in proxy:
            proxy_url = proxy["url"]
            if all(key in proxy for key in ["username", "password"]):
                parsed = urllib.parse.urlparse(proxy_url)
                proxy_str = f"{parsed.scheme}://{proxy['username']}:{proxy['password']}@{parsed.hostname}:{parsed.port}"
                kwargs["proxy"] = proxy_str
            else:
                kwargs["proxy"] = proxy_url

        if os.environ.get("DISABLE_WEB_SECURITY", "false").lower() == "true":
            kwargs["disable_web_security"] = True

        try:
            driver = Driver(**kwargs)
        except Exception as e:
            logger.error("Error starting SeleniumBase driver: %s", e)
            raise

        # Same post-launch normalization the UC path applies: strips the
        # HeadlessChrome token via CDP and injects stealth_fallback.js on
        # stock Chromium (a no-op beyond logging on the custom build).
        utils._maybe_normalize_user_agent(driver, stealth_mode)
        utils._maybe_apply_stealth(driver, stealth_mode)

        return driver

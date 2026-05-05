import logging
import os
import urllib.parse
from typing import Any

from selenium.webdriver.chrome.webdriver import WebDriver
from flaresolverr import utils


class SeleniumBaseBackend:
    def create_driver(self, proxy: dict[str, Any] | None, stealth_mode: str) -> WebDriver:
        logging.debug("Launching web browser (seleniumbase)...")
        try:
            from seleniumbase import Driver
        except ImportError as e:
            raise ImportError(
                "seleniumbase is not installed. Install with: pip install flaresolverr[seleniumbase]"
            ) from e

        kwargs: dict[str, Any] = {
            "uc": stealth_mode != utils.STEALTH_MODE_OFF,
            "headless": utils.get_config_headless(),
            "window_size": "1920,1080",
            "no_sandbox": True,
        }

        if proxy is not None and "url" in proxy:
            proxy_url = proxy["url"]
            if all(key in proxy for key in ["username", "password"]):
                parsed = urllib.parse.urlparse(proxy_url)
                proxy_str = f"{parsed.scheme}://{proxy['username']}:{proxy['password']}@{parsed.hostname}:{parsed.port}"
                kwargs["proxy"] = proxy_str
            else:
                kwargs["proxy"] = proxy_url

        if utils.get_config_disable_quic():
            kwargs["disable_quic"] = True

        if os.environ.get("DISABLE_WEB_SECURITY", "false").lower() == "true":
            kwargs["disable_web_security"] = True

        try:
            driver = Driver(**kwargs)
        except Exception as e:
            logging.error("Error starting SeleniumBase driver: %s", e)
            raise

        return driver

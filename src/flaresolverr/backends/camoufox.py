import logging
import time
from typing import Any

from selenium.common import TimeoutException
from selenium.webdriver.common.keys import Keys

from flaresolverr.backends.browser_context import ActionChainBuilder, BrowserContext, Element


class CamoufoxElement(Element):
    """Wraps a Playwright ElementHandle."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def click(self) -> None:
        self._handle.click()

    def clear(self) -> None:
        self._handle.fill("")

    def send_keys(self, text: str) -> None:
        self._handle.type(text)

    def get_attribute(self, name: str) -> str | None:
        return self._handle.get_attribute(name)

    @property
    def text(self) -> str:
        return self._handle.inner_text()

    @property
    def location(self) -> dict[str, int]:
        box = self._handle.bounding_box()
        if box:
            return {"x": int(box["x"]), "y": int(box["y"])}
        return {"x": 0, "y": 0}

    @property
    def size(self) -> dict[str, int]:
        box = self._handle.bounding_box()
        if box:
            return {"width": int(box["width"]), "height": int(box["height"])}
        return {"width": 0, "height": 0}


_KEYS_MAP: dict[str, str] = {
    Keys.TAB: "Tab",
    Keys.SPACE: "Space",
    Keys.ENTER: "Enter",
    Keys.ESCAPE: "Escape",
    Keys.BACKSPACE: "Backspace",
    Keys.DELETE: "Delete",
    Keys.ARROW_UP: "ArrowUp",
    Keys.ARROW_DOWN: "ArrowDown",
    Keys.ARROW_LEFT: "ArrowLeft",
    Keys.ARROW_RIGHT: "ArrowRight",
}


class CamoufoxActionChainBuilder(ActionChainBuilder):
    """Playwright-based action chain builder (executes immediately)."""

    def __init__(self, page: Any) -> None:
        self._page = page
        self._current_x = 0.0
        self._current_y = 0.0

    def move_to_element(self, element: Element) -> "CamoufoxActionChainBuilder":
        if not isinstance(element, CamoufoxElement):
            raise TypeError(f"Expected CamoufoxElement, got {type(element).__name__}")
        box = element._handle.bounding_box()
        if box:
            self._current_x = box["x"] + box["width"] / 2
            self._current_y = box["y"] + box["height"] / 2
            self._page.mouse.move(self._current_x, self._current_y)
        return self

    def move_by_offset(self, x: int, y: int) -> "CamoufoxActionChainBuilder":
        self._current_x += x
        self._current_y += y
        self._page.mouse.move(self._current_x, self._current_y)
        return self

    def pause(self, seconds: float) -> "CamoufoxActionChainBuilder":
        time.sleep(seconds)
        return self

    def click(self, element: Element | None = None) -> "CamoufoxActionChainBuilder":
        if element is not None:
            if not isinstance(element, CamoufoxElement):
                raise TypeError(f"Expected CamoufoxElement, got {type(element).__name__}")
            box = element._handle.bounding_box()
            if box:
                self._page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        else:
            self._page.mouse.click(self._current_x, self._current_y)
        return self

    def click_and_hold(self) -> "CamoufoxActionChainBuilder":
        self._page.mouse.down()
        return self

    def release(self) -> "CamoufoxActionChainBuilder":
        self._page.mouse.up()
        return self

    def send_keys(self, *keys: str) -> "CamoufoxActionChainBuilder":
        for key in keys:
            mapped = _KEYS_MAP.get(key, key)
            self._page.keyboard.press(mapped)
        return self

    def perform(self) -> None:
        pass  # All actions execute immediately


def _playwright_selector(by: str, value: str) -> str:
    """Convert Selenium-style locator to Playwright selector."""
    by_lower = by.lower().replace("_", " ")
    if by_lower == "xpath":
        return f"xpath={value}"
    if by_lower == "css selector":
        return value
    if by_lower == "tag name":
        return value
    if by_lower == "id":
        return f"#{value}"
    if by_lower == "class name":
        return f".{value}"
    if by_lower == "name":
        return f"[name='{value}']"
    return value


class CamoufoxBrowserContext(BrowserContext):
    """Playwright-based browser context using Camoufox."""

    def __init__(self, camoufox: Any, browser: Any, page: Any) -> None:
        self._camoufox = camoufox
        self._browser = browser
        self._page = page
        self._last_dialog: Any = None
        self._page.on("dialog", self._on_dialog)

    def _on_dialog(self, dialog: Any) -> None:
        self._last_dialog = dialog

    def get(self, url: str) -> None:
        self._page.goto(url)

    def execute_script(self, script: str, *args: Any) -> Any:
        script = script.strip()
        has_args = "arguments[" in script
        unwrapped = [a._handle if isinstance(a, CamoufoxElement) else a for a in args]
        if has_args:
            script = f"(...__args) => {{ {script.replace('arguments', '__args')} }}"
            return self._page.evaluate(script, *unwrapped)
        # For scripts without arguments, wrap in IIFE to support return statements
        script = f"() => {{ {script} }}"
        return self._page.evaluate(script)

    def find_element(self, by: str, value: str) -> Element:
        selector = _playwright_selector(by, value)
        handle = self._page.query_selector(selector)
        if handle is None:
            raise Exception(f"Element not found: {by}={value}")
        return CamoufoxElement(handle)

    def find_elements(self, by: str, value: str) -> list[Element]:
        selector = _playwright_selector(by, value)
        handles = self._page.query_selector_all(selector)
        return [CamoufoxElement(h) for h in handles]

    @property
    def page_source(self) -> str:
        return self._page.content()

    @property
    def title(self) -> str:
        return self._page.title()

    @property
    def current_url(self) -> str:
        return self._page.url

    def add_cookie(self, cookie: dict[str, Any]) -> None:
        cookie_copy = dict(cookie)
        if "url" not in cookie_copy:
            cookie_copy["url"] = self._page.url
        self._page.context.add_cookies([cookie_copy])

    def delete_cookie(self, name: str) -> None:
        cookies = self._page.context.cookies()
        self._page.context.clear_cookies()
        for cookie in cookies:
            if cookie.get("name") != name:
                self._page.context.add_cookies([cookie])

    def get_cookies(self) -> list[dict[str, Any]]:
        return self._page.context.cookies()

    def get_screenshot_as_base64(self) -> str:
        return self._page.screenshot(type="base64")

    def switch_to_default_content(self) -> None:
        pass  # No-op for Playwright

    def get_alert_text(self) -> str:
        if self._last_dialog:
            return self._last_dialog.message
        return ""

    def dismiss_alert(self) -> None:
        if self._last_dialog:
            self._last_dialog.dismiss()
            self._last_dialog = None

    def close(self) -> None:
        try:
            self._browser.close()
        except Exception:
            pass

    def quit(self) -> None:
        try:
            self._browser.close()
        except Exception:
            pass
        try:
            self._camoufox.__exit__(None, None, None)
        except Exception:
            pass

    def execute_cdp_cmd(self, method: str, params: dict[str, Any]) -> Any:
        logging.debug("CDP command ignored for Camoufox: %s", method)
        return None

    def action_chain(self) -> ActionChainBuilder:
        return CamoufoxActionChainBuilder(self._page)

    def wait_for_presence(self, by: str, value: str, timeout: float) -> Element:
        selector = _playwright_selector(by, value)
        handle = self._page.wait_for_selector(selector, state="attached", timeout=timeout * 1000)
        return CamoufoxElement(handle)

    def wait_for_absence(self, by: str, value: str, timeout: float) -> bool:
        selector = _playwright_selector(by, value)
        end_time = time.time() + timeout
        while time.time() < end_time:
            handle = self._page.query_selector(selector)
            if handle is None:
                return True
            time.sleep(0.1)
        raise TimeoutException(f"Timeout waiting for absence: {by}={value}")

    def wait_for_visibility(self, by: str, value: str, timeout: float) -> Element:
        selector = _playwright_selector(by, value)
        handle = self._page.wait_for_selector(selector, state="visible", timeout=timeout * 1000)
        return CamoufoxElement(handle)

    def wait_for_title(self, title: str, timeout: float) -> bool:
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self.title == title:
                return True
            time.sleep(0.1)
        raise TimeoutException(f"Timeout waiting for title: {title}")

    def wait_for_title_not(self, title: str, timeout: float) -> bool:
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self.title != title:
                return True
            time.sleep(0.1)
        raise TimeoutException(f"Timeout waiting for title not to be: {title}")

    def wait_for_staleness(self, element: Element, timeout: float) -> bool:
        if not isinstance(element, CamoufoxElement):
            raise TypeError(f"Expected CamoufoxElement, got {type(element).__name__}")
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                element._handle.evaluate("() => true")
            except Exception:
                return True
            time.sleep(0.1)
        raise TimeoutException("Timeout waiting for element staleness")

    def get_user_agent(self) -> str:
        return self.execute_script("return navigator.userAgent")

    def apply_user_agent_override(self, user_agent: str) -> None:
        logging.debug("User agent override skipped for Camoufox")


class CamoufoxBackend:
    """Backend using Camoufox (Playwright-based anti-detect browser)."""

    def create_driver(self, proxy: dict[str, Any] | None, stealth_mode: str) -> BrowserContext:
        try:
            from camoufox.sync_api import Camoufox
        except ImportError as e:
            raise ImportError(
                "camoufox is not installed. Install it with: pip install 'camoufox[geoip]'"
            ) from e

        from flaresolverr import utils

        headless = utils.get_config_headless()
        kwargs: dict[str, Any] = {
            "headless": "virtual" if headless and utils.PLATFORM_VERSION != "nt" else headless,
            "window": (1920, 1080),
        }

        if proxy:
            proxy_config: dict[str, str] = {}
            if "url" in proxy:
                proxy_config["server"] = proxy["url"]
            elif "host" in proxy and "port" in proxy:
                proxy_config["server"] = f"http://{proxy['host']}:{proxy['port']}"
            if "username" in proxy:
                proxy_config["username"] = proxy["username"]
            if "password" in proxy:
                proxy_config["password"] = proxy["password"]
            if proxy_config:
                kwargs["proxy"] = proxy_config

        camoufox = Camoufox(**kwargs)
        browser = camoufox.__enter__()
        page = browser.new_page()
        return CamoufoxBrowserContext(camoufox, browser, page)

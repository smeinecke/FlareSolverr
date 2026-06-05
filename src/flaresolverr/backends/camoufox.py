import base64
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from selenium.common import TimeoutException
from selenium.webdriver.common.keys import Keys

from flaresolverr.backends.browser_context import ActionChainBuilder, BrowserContext, Element


class _SyncExecutor:
    """Runs Playwright sync API calls in a dedicated thread to avoid greenlet issues."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1)

    def submit(self, func, *args, **kwargs):
        return self._executor.submit(func, *args, **kwargs).result()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)


class CamoufoxElement(Element):
    """Wraps a Playwright ElementHandle."""

    def __init__(self, handle: Any, executor: _SyncExecutor) -> None:
        self._handle = handle
        self._executor = executor

    def click(self) -> None:
        self._executor.submit(self._handle.click)

    def clear(self) -> None:
        self._executor.submit(self._handle.fill, "")

    def send_keys(self, text: str) -> None:
        self._executor.submit(self._handle.type, text)

    def get_attribute(self, name: str) -> str | None:
        return self._executor.submit(self._handle.get_attribute, name)

    @property
    def text(self) -> str:
        return self._executor.submit(self._handle.inner_text)

    @property
    def location(self) -> dict[str, int]:
        def _get():
            box = self._handle.bounding_box()
            if box:
                return {"x": int(box["x"]), "y": int(box["y"])}
            return {"x": 0, "y": 0}

        return self._executor.submit(_get)

    @property
    def size(self) -> dict[str, int]:
        def _get():
            box = self._handle.bounding_box()
            if box:
                return {"width": int(box["width"]), "height": int(box["height"])}
            return {"width": 0, "height": 0}

        return self._executor.submit(_get)


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
    """Playwright-based action chain builder (executes in executor thread)."""

    def __init__(self, page: Any, executor: _SyncExecutor) -> None:
        self._page = page
        self._executor = executor
        self._current_x = 0.0
        self._current_y = 0.0

    def move_to_element(self, element: Element) -> "CamoufoxActionChainBuilder":
        if not isinstance(element, CamoufoxElement):
            raise TypeError(f"Expected CamoufoxElement, got {type(element).__name__}")

        def _move():
            box = element._handle.bounding_box()
            if box:
                self._current_x = box["x"] + box["width"] / 2
                self._current_y = box["y"] + box["height"] / 2
                self._page.mouse.move(self._current_x, self._current_y)

        self._executor.submit(_move)
        return self

    def move_by_offset(self, x: int, y: int) -> "CamoufoxActionChainBuilder":
        self._current_x += x
        self._current_y += y
        self._executor.submit(self._page.mouse.move, self._current_x, self._current_y)
        return self

    def pause(self, seconds: float) -> "CamoufoxActionChainBuilder":
        self._executor.submit(time.sleep, seconds)
        return self

    def click(self, element: Element | None = None) -> "CamoufoxActionChainBuilder":
        def _click():
            if element is not None:
                if not isinstance(element, CamoufoxElement):
                    raise TypeError(f"Expected CamoufoxElement, got {type(element).__name__}")
                box = element._handle.bounding_box()
                if box:
                    self._page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            else:
                self._page.mouse.click(self._current_x, self._current_y)

        self._executor.submit(_click)
        return self

    def click_and_hold(self) -> "CamoufoxActionChainBuilder":
        self._executor.submit(self._page.mouse.down)
        return self

    def release(self) -> "CamoufoxActionChainBuilder":
        self._executor.submit(self._page.mouse.up)
        return self

    def send_keys(self, *keys: str) -> "CamoufoxActionChainBuilder":
        def _send():
            for key in keys:
                mapped = _KEYS_MAP.get(key)
                if mapped:
                    self._page.keyboard.press(mapped)
                else:
                    self._page.keyboard.type(key)

        self._executor.submit(_send)
        return self

    def perform(self) -> None:
        pass  # All actions execute immediately in executor


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

    def __init__(self, executor: _SyncExecutor, camoufox: Any, browser: Any, page: Any, stealth_mode: str = "off") -> None:
        self._executor = executor
        self._camoufox = camoufox
        self._browser = browser
        self._page = page
        self._stealth_mode = stealth_mode
        self._last_dialog: Any = None

        def _attach():
            self._page.on("dialog", self._on_dialog)

        self._executor.submit(_attach)

    def _on_dialog(self, dialog: Any) -> None:
        self._last_dialog = dialog

    def get(self, url: str) -> None:
        self._executor.submit(self._page.goto, url)

    def execute_script(self, script: str, *args: Any) -> Any:
        def _run():
            script_local = script.strip()
            has_args = "arguments[" in script_local
            unwrapped = [a._handle if isinstance(a, CamoufoxElement) else a for a in args]
            if has_args:
                script_local = f"(...__args) => {{ {script_local.replace('arguments', '__args')} }}"
                return self._page.evaluate(script_local, *unwrapped)
            # For scripts without arguments, wrap in IIFE to support return statements
            script_local = f"() => {{ {script_local} }}"
            return self._page.evaluate(script_local)

        return self._executor.submit(_run)

    def find_element(self, by: str, value: str) -> Element:
        def _find():
            selector = _playwright_selector(by, value)
            handle = self._page.query_selector(selector)
            if handle is None:
                raise Exception(f"Element not found: {by}={value}")
            return CamoufoxElement(handle, self._executor)

        return self._executor.submit(_find)

    def find_elements(self, by: str, value: str) -> list[Element]:
        def _find():
            selector = _playwright_selector(by, value)
            handles = self._page.query_selector_all(selector)
            return cast(list[Element], [CamoufoxElement(h, self._executor) for h in handles])

        return self._executor.submit(_find)

    @property
    def page_source(self) -> str:
        return self._executor.submit(self._page.content)

    @property
    def title(self) -> str:
        return self._executor.submit(self._page.title)

    @property
    def current_url(self) -> str:
        return self._executor.submit(lambda: self._page.url)

    def add_cookie(self, cookie: dict[str, Any]) -> None:
        def _add():
            cookie_copy = dict(cookie)
            if "url" not in cookie_copy and "domain" not in cookie_copy:
                cookie_copy["url"] = self._page.url
            self._page.context.add_cookies([cookie_copy])

        self._executor.submit(_add)

    def delete_cookie(self, name: str) -> None:
        def _delete():
            cookies = self._page.context.cookies()
            self._page.context.clear_cookies()
            for cookie in cookies:
                if cookie.get("name") != name:
                    self._page.context.add_cookies([cookie])

        self._executor.submit(_delete)

    def get_cookies(self) -> list[dict[str, Any]]:
        return self._executor.submit(self._page.context.cookies)

    def get_screenshot_as_base64(self) -> str:
        def _shot():
            return base64.b64encode(self._page.screenshot(type="png")).decode("ascii")

        return self._executor.submit(_shot)

    def switch_to_default_content(self) -> None:
        pass  # No-op for Playwright

    def get_alert_text(self) -> str:
        def _get():
            if self._last_dialog:
                return self._last_dialog.message
            return ""

        return self._executor.submit(_get)

    def dismiss_alert(self) -> None:
        def _dismiss():
            if self._last_dialog:
                self._last_dialog.dismiss()
                self._last_dialog = None

        self._executor.submit(_dismiss)

    def close(self) -> None:
        self._executor.submit(self._browser.close)

    def quit(self) -> None:
        def _quit():
            try:
                self._browser.close()
            except Exception:  # nosec B110
                pass
            try:
                self._camoufox.__exit__(None, None, None)
            except Exception:  # nosec B110
                pass

        self._executor.submit(_quit)
        self._executor.shutdown()

    def execute_cdp_cmd(self, method: str, params: dict[str, Any]) -> Any:
        def _run():
            # Translate common CDP commands to Playwright equivalents.
            if method == "Page.addScriptToEvaluateOnNewDocument":
                self._page.add_init_script(params.get("source", ""))
                return {}
            if method == "Emulation.setUserAgentOverride":
                self._page.set_extra_http_headers({"User-Agent": params.get("userAgent", "")})
                return {}
            if method == "Network.setExtraHTTPHeaders":
                self._page.set_extra_http_headers(params.get("headers", {}))
                return {}
            if method == "Network.enable":
                return {}  # No-op: Playwright network is always enabled
            if method == "Network.setBlockedURLs":
                for pattern in params.get("urls", []):
                    self._page.route(pattern, lambda route: route.abort())
                return {}
            raise NotImplementedError(f"CDP command '{method}' is not supported by the Camoufox backend")

        return self._executor.submit(_run)

    def action_chain(self) -> ActionChainBuilder:
        return CamoufoxActionChainBuilder(self._page, self._executor)

    def wait_for_presence(self, by: str, value: str, timeout: float) -> Element:
        def _wait():
            selector = _playwright_selector(by, value)
            handle = self._page.wait_for_selector(selector, state="attached", timeout=timeout * 1000)
            return CamoufoxElement(handle, self._executor)

        return self._executor.submit(_wait)

    def wait_for_absence(self, by: str, value: str, timeout: float) -> bool:
        def _wait():
            selector = _playwright_selector(by, value)
            end_time = time.time() + timeout
            while time.time() < end_time:
                handle = self._page.query_selector(selector)
                if handle is None:
                    return True
                time.sleep(0.1)
            raise TimeoutException(f"Timeout waiting for absence: {by}={value}")

        return self._executor.submit(_wait)

    def wait_for_visibility(self, by: str, value: str, timeout: float) -> Element:
        def _wait():
            selector = _playwright_selector(by, value)
            handle = self._page.wait_for_selector(selector, state="visible", timeout=timeout * 1000)
            return CamoufoxElement(handle, self._executor)

        return self._executor.submit(_wait)

    def wait_for_title(self, title: str, timeout: float) -> bool:
        def _wait():
            end_time = time.time() + timeout
            while time.time() < end_time:
                if self._page.title() == title:
                    return True
                time.sleep(0.1)
            return False

        return self._executor.submit(_wait)

    def wait_for_title_not(self, title: str, timeout: float) -> bool:
        def _wait():
            end_time = time.time() + timeout
            while time.time() < end_time:
                if self._page.title() != title:
                    return True
                time.sleep(0.1)
            return False

        return self._executor.submit(_wait)

    def wait_for_staleness(self, element: Element, timeout: float) -> bool:
        if not isinstance(element, CamoufoxElement):
            raise TypeError(f"Expected CamoufoxElement, got {type(element).__name__}")

        def _wait():
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    element._handle.evaluate("() => true")
                except Exception:
                    return True
                time.sleep(0.1)
            raise TimeoutException("Timeout waiting for element staleness")

        return self._executor.submit(_wait)

    def get_user_agent(self) -> str:
        return self.execute_script("return navigator.userAgent")

    def apply_user_agent_override(self, user_agent: str) -> None:
        logging.debug("User agent override skipped for Camoufox")

    def apply_proxy(self, proxy: dict[str, Any] | None) -> None:
        def _update():
            proxy_config: dict[str, str] = {}
            if proxy is not None:
                if "url" in proxy and proxy["url"]:
                    proxy_config["server"] = proxy["url"]
                elif "host" in proxy and "port" in proxy:
                    proxy_config["server"] = f"http://{proxy['host']}:{proxy['port']}"
                if "username" in proxy:
                    proxy_config["username"] = proxy["username"]
                if "password" in proxy:
                    proxy_config["password"] = proxy["password"]

            context_kwargs: dict[str, Any] = {"viewport": {"width": 1920, "height": 1080}}
            if proxy_config:
                context_kwargs["proxy"] = proxy_config

            self._page.context.close()
            new_context = self._browser.new_context(**context_kwargs)
            self._page = new_context.new_page()
            self._page.on("dialog", self._on_dialog)
            logging.debug("Camoufox context recreated with updated proxy.")

        self._executor.submit(_update)


class CamoufoxBackend:
    """Backend using Camoufox (Playwright-based anti-detect browser)."""

    def create_driver(self, proxy: dict[str, Any] | None, stealth_mode: str) -> BrowserContext:
        try:
            from camoufox.sync_api import Camoufox  # pyright: ignore[reportMissingImports]
        except ImportError as e:
            raise ImportError("camoufox is not installed. Install it with: pip install 'camoufox[geoip]'") from e

        from flaresolverr import utils

        executor = _SyncExecutor()

        def _create():
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
            return camoufox, browser, page

        camoufox, browser, page = executor.submit(_create)
        return CamoufoxBrowserContext(executor, camoufox, browser, page, stealth_mode=stealth_mode)

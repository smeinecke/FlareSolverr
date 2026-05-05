from typing import Any

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.expected_conditions import (
    presence_of_element_located,
    staleness_of,
    title_is,
    visibility_of_element_located,
)
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr.backends.browser_context import ActionChainBuilder, BrowserContext, Element


class SeleniumElement(Element):
    """Wraps a Selenium WebElement to satisfy the Element protocol."""

    def __init__(self, element) -> None:
        self._element = element

    def click(self) -> None:
        self._element.click()

    def clear(self) -> None:
        self._element.clear()

    def send_keys(self, text: str) -> None:
        self._element.send_keys(text)

    def get_attribute(self, name: str) -> str | None:
        return self._element.get_attribute(name)

    @property
    def text(self) -> str:
        return self._element.text

    @property
    def location(self) -> dict[str, int]:
        return self._element.location

    @property
    def size(self) -> dict[str, int]:
        return self._element.size


class SeleniumActionChainBuilder(ActionChainBuilder):
    """Wraps Selenium ActionChains."""

    def __init__(self, driver: WebDriver) -> None:
        self._actions = ActionChains(driver)

    def _unwrap(self, element: Element | None):
        if element is None:
            return None
        if isinstance(element, SeleniumElement):
            return element._element
        raise TypeError(f"Expected SeleniumElement, got {type(element).__name__}")

    def move_to_element(self, element: Element) -> "SeleniumActionChainBuilder":
        self._actions.move_to_element(self._unwrap(element))
        return self

    def move_by_offset(self, x: int, y: int) -> "SeleniumActionChainBuilder":
        self._actions.move_by_offset(x, y)
        return self

    def pause(self, seconds: float) -> "SeleniumActionChainBuilder":
        self._actions.pause(seconds)
        return self

    def click(self, element: Element | None = None) -> "SeleniumActionChainBuilder":
        self._actions.click(self._unwrap(element))
        return self

    def click_and_hold(self) -> "SeleniumActionChainBuilder":
        self._actions.click_and_hold()
        return self

    def release(self) -> "SeleniumActionChainBuilder":
        self._actions.release()
        return self

    def send_keys(self, *keys: str) -> "SeleniumActionChainBuilder":
        for key in keys:
            self._actions.send_keys(key)
        return self

    def perform(self) -> None:
        self._actions.perform()


class SeleniumBrowserContext(BrowserContext):
    """Wraps a Selenium WebDriver to satisfy the BrowserContext protocol."""

    def __init__(self, driver: WebDriver) -> None:
        self._driver = driver

    def get(self, url: str) -> None:
        self._driver.get(url)

    def execute_script(self, script: str, *args: Any) -> Any:
        unwrapped = [a._element if isinstance(a, SeleniumElement) else a for a in args]
        return self._driver.execute_script(script, *unwrapped)

    def find_element(self, by: str, value: str) -> Element:
        return SeleniumElement(self._driver.find_element(by, value))

    def find_elements(self, by: str, value: str) -> list[Element]:
        return [SeleniumElement(el) for el in self._driver.find_elements(by, value)]

    @property
    def page_source(self) -> str:
        return self._driver.page_source

    @property
    def title(self) -> str:
        return self._driver.title

    @property
    def current_url(self) -> str:
        return self._driver.current_url

    def add_cookie(self, cookie: dict[str, Any]) -> None:
        self._driver.add_cookie(cookie)

    def delete_cookie(self, name: str) -> None:
        self._driver.delete_cookie(name)

    def get_cookies(self) -> list[dict[str, Any]]:
        return self._driver.get_cookies()

    def get_screenshot_as_base64(self) -> str:
        return self._driver.get_screenshot_as_base64()

    def switch_to_default_content(self) -> None:
        self._driver.switch_to.default_content()

    def get_alert_text(self) -> str:
        return self._driver.switch_to.alert.text

    def dismiss_alert(self) -> None:
        self._driver.switch_to.alert.dismiss()

    def close(self) -> None:
        self._driver.close()

    def quit(self) -> None:
        self._driver.quit()

    def execute_cdp_cmd(self, method: str, params: dict[str, Any]) -> Any:
        return self._driver.execute_cdp_cmd(method, params)

    def action_chain(self) -> ActionChainBuilder:
        return SeleniumActionChainBuilder(self._driver)

    def wait_for_presence(self, by: str, value: str, timeout: float) -> Element:
        return SeleniumElement(
            WebDriverWait(self._driver, timeout).until(presence_of_element_located((by, value)))
        )

    def wait_for_absence(self, by: str, value: str, timeout: float) -> bool:
        WebDriverWait(self._driver, timeout).until_not(presence_of_element_located((by, value)))
        return True

    def wait_for_visibility(self, by: str, value: str, timeout: float) -> Element:
        return SeleniumElement(
            WebDriverWait(self._driver, timeout).until(visibility_of_element_located((by, value)))
        )

    def wait_for_title(self, title: str, timeout: float) -> bool:
        WebDriverWait(self._driver, timeout).until(title_is(title))
        return True

    def wait_for_title_not(self, title: str, timeout: float) -> bool:
        WebDriverWait(self._driver, timeout).until_not(title_is(title))
        return True

    def wait_for_staleness(self, element: Element, timeout: float) -> bool:
        if not isinstance(element, SeleniumElement):
            raise TypeError(f"Expected SeleniumElement, got {type(element).__name__}")
        WebDriverWait(self._driver, timeout).until(staleness_of(element._element))
        return True

    def get_user_agent(self) -> str:
        from flaresolverr import utils
        return utils.get_user_agent(self._driver)

    def apply_user_agent_override(self, user_agent: str) -> None:
        from flaresolverr import utils
        utils.apply_user_agent_override(self._driver, user_agent)

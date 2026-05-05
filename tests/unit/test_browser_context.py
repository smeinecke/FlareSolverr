from unittest.mock import MagicMock, patch

import pytest

from flaresolverr.backends.browser_context import get_browser_context
from flaresolverr.backends.selenium_context import SeleniumBrowserContext, SeleniumElement


def test_get_browser_context_wraps_webdriver():
    mock_driver = MagicMock()
    ctx = get_browser_context(mock_driver)
    assert isinstance(ctx, SeleniumBrowserContext)


def test_get_browser_context_passes_through_selenium_browser_context():
    mock_driver = MagicMock()
    ctx = SeleniumBrowserContext(mock_driver)
    result = get_browser_context(ctx)
    assert result is ctx


def test_selenium_browser_context_get():
    mock_driver = MagicMock()
    ctx = SeleniumBrowserContext(mock_driver)
    ctx.get("https://example.com")
    mock_driver.get.assert_called_once_with("https://example.com")


def test_selenium_browser_context_execute_script():
    mock_driver = MagicMock()
    mock_driver.execute_script.return_value = "result"
    ctx = SeleniumBrowserContext(mock_driver)
    result = ctx.execute_script("return 1 + 1")
    assert result == "result"
    mock_driver.execute_script.assert_called_once_with("return 1 + 1")


def test_selenium_browser_context_find_element():
    mock_driver = MagicMock()
    mock_element = MagicMock()
    mock_driver.find_element.return_value = mock_element
    ctx = SeleniumBrowserContext(mock_driver)
    el = ctx.find_element("xpath", "//div")
    assert isinstance(el, SeleniumElement)
    mock_driver.find_element.assert_called_once_with("xpath", "//div")


def test_selenium_browser_context_find_elements():
    mock_driver = MagicMock()
    mock_elements = [MagicMock(), MagicMock()]
    mock_driver.find_elements.return_value = mock_elements
    ctx = SeleniumBrowserContext(mock_driver)
    elements = ctx.find_elements("css selector", "div")
    assert len(elements) == 2
    assert all(isinstance(el, SeleniumElement) for el in elements)


def test_selenium_browser_context_page_source():
    mock_driver = MagicMock()
    mock_driver.page_source = "<html></html>"
    ctx = SeleniumBrowserContext(mock_driver)
    assert ctx.page_source == "<html></html>"


def test_selenium_browser_context_title():
    mock_driver = MagicMock()
    mock_driver.title = "Example"
    ctx = SeleniumBrowserContext(mock_driver)
    assert ctx.title == "Example"


def test_selenium_browser_context_current_url():
    mock_driver = MagicMock()
    mock_driver.current_url = "https://example.com"
    ctx = SeleniumBrowserContext(mock_driver)
    assert ctx.current_url == "https://example.com"


def test_selenium_browser_context_cookies():
    mock_driver = MagicMock()
    mock_driver.get_cookies.return_value = [{"name": "test", "value": "123"}]
    ctx = SeleniumBrowserContext(mock_driver)
    assert ctx.get_cookies() == [{"name": "test", "value": "123"}]


def test_selenium_browser_context_screenshot():
    mock_driver = MagicMock()
    mock_driver.get_screenshot_as_base64.return_value = "base64data"
    ctx = SeleniumBrowserContext(mock_driver)
    assert ctx.get_screenshot_as_base64() == "base64data"


def test_selenium_browser_context_switch_to_default_content():
    mock_driver = MagicMock()
    ctx = SeleniumBrowserContext(mock_driver)
    ctx.switch_to_default_content()
    mock_driver.switch_to.default_content.assert_called_once()


def test_selenium_browser_context_alert():
    mock_driver = MagicMock()
    mock_driver.switch_to.alert.text = "alert text"
    ctx = SeleniumBrowserContext(mock_driver)
    assert ctx.get_alert_text() == "alert text"
    ctx.dismiss_alert()
    mock_driver.switch_to.alert.dismiss.assert_called_once()


def test_selenium_browser_context_close_and_quit():
    mock_driver = MagicMock()
    ctx = SeleniumBrowserContext(mock_driver)
    ctx.close()
    mock_driver.close.assert_called_once()
    ctx.quit()
    mock_driver.quit.assert_called_once()


def test_selenium_browser_context_execute_cdp_cmd():
    mock_driver = MagicMock()
    mock_driver.execute_cdp_cmd.return_value = {"result": "ok"}
    ctx = SeleniumBrowserContext(mock_driver)
    result = ctx.execute_cdp_cmd("Network.enable", {})
    assert result == {"result": "ok"}


def test_selenium_browser_context_action_chain():
    mock_driver = MagicMock()
    ctx = SeleniumBrowserContext(mock_driver)
    builder = ctx.action_chain()
    assert builder is not None


def test_selenium_browser_context_wait_for_presence():
    mock_driver = MagicMock()
    mock_element = MagicMock()
    with patch("flaresolverr.backends.selenium_context.WebDriverWait") as mock_wait:
        mock_wait.return_value.until.return_value = mock_element
        ctx = SeleniumBrowserContext(mock_driver)
        el = ctx.wait_for_presence("css selector", "div", 5)
        assert isinstance(el, SeleniumElement)


def test_selenium_browser_context_wait_for_title_not():
    mock_driver = MagicMock()
    with patch("flaresolverr.backends.selenium_context.WebDriverWait") as mock_wait:
        ctx = SeleniumBrowserContext(mock_driver)
        result = ctx.wait_for_title_not("Just a moment...", 1)
        assert result is True
        mock_wait.return_value.until_not.assert_called_once()


def test_selenium_browser_context_wait_for_staleness():
    mock_driver = MagicMock()
    mock_element = MagicMock()
    with patch("flaresolverr.backends.selenium_context.WebDriverWait") as mock_wait:
        ctx = SeleniumBrowserContext(mock_driver)
        sel_element = SeleniumElement(mock_element)
        result = ctx.wait_for_staleness(sel_element, 1)
        assert result is True
        mock_wait.return_value.until.assert_called_once()


def test_selenium_element_properties():
    mock_element = MagicMock()
    mock_element.text = "hello"
    mock_element.location = {"x": 10, "y": 20}
    mock_element.size = {"width": 100, "height": 200}
    mock_element.get_attribute.return_value = "attr_value"
    el = SeleniumElement(mock_element)
    assert el.text == "hello"
    assert el.location == {"x": 10, "y": 20}
    assert el.size == {"width": 100, "height": 200}
    assert el.get_attribute("data-id") == "attr_value"
    el.click()
    mock_element.click.assert_called_once()
    el.clear()
    mock_element.clear.assert_called_once()
    el.send_keys("text")
    mock_element.send_keys.assert_called_once_with("text")

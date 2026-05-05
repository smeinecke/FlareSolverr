from unittest.mock import MagicMock, patch

import pytest

from flaresolverr.backends.camoufox import (
    CamoufoxActionChainBuilder,
    CamoufoxBrowserContext,
    CamoufoxElement,
    _playwright_selector,
)


class TestPlaywrightSelector:
    def test_xpath(self):
        assert _playwright_selector("xpath", "//div") == "xpath=//div"

    def test_css_selector(self):
        assert _playwright_selector("css selector", "div.class") == "div.class"

    def test_tag_name(self):
        assert _playwright_selector("tag name", "html") == "html"

    def test_id(self):
        assert _playwright_selector("id", "myId") == "#myId"

    def test_class_name(self):
        assert _playwright_selector("class name", "myClass") == ".myClass"

    def test_name(self):
        assert _playwright_selector("name", "field") == "[name='field']"


class TestCamoufoxElement:
    def test_click(self):
        mock_handle = MagicMock()
        el = CamoufoxElement(mock_handle)
        el.click()
        mock_handle.click.assert_called_once()

    def test_clear(self):
        mock_handle = MagicMock()
        el = CamoufoxElement(mock_handle)
        el.clear()
        mock_handle.fill.assert_called_once_with("")

    def test_send_keys(self):
        mock_handle = MagicMock()
        el = CamoufoxElement(mock_handle)
        el.send_keys("hello")
        mock_handle.type.assert_called_once_with("hello")

    def test_get_attribute(self):
        mock_handle = MagicMock()
        mock_handle.get_attribute.return_value = "value"
        el = CamoufoxElement(mock_handle)
        assert el.get_attribute("name") == "value"

    def test_text(self):
        mock_handle = MagicMock()
        mock_handle.inner_text.return_value = "inner text"
        el = CamoufoxElement(mock_handle)
        assert el.text == "inner text"

    def test_location(self):
        mock_handle = MagicMock()
        mock_handle.bounding_box.return_value = {"x": 10.5, "y": 20.5, "width": 100, "height": 200}
        el = CamoufoxElement(mock_handle)
        assert el.location == {"x": 10, "y": 20}

    def test_size(self):
        mock_handle = MagicMock()
        mock_handle.bounding_box.return_value = {"x": 10.5, "y": 20.5, "width": 100.5, "height": 200.5}
        el = CamoufoxElement(mock_handle)
        assert el.size == {"width": 100, "height": 200}

    def test_location_fallback_when_no_bounding_box(self):
        mock_handle = MagicMock()
        mock_handle.bounding_box.return_value = None
        el = CamoufoxElement(mock_handle)
        assert el.location == {"x": 0, "y": 0}


class TestCamoufoxActionChainBuilder:
    def test_move_to_element(self):
        mock_page = MagicMock()
        mock_handle = MagicMock()
        mock_handle.bounding_box.return_value = {"x": 10, "y": 20, "width": 100, "height": 50}
        builder = CamoufoxActionChainBuilder(mock_page)
        el = CamoufoxElement(mock_handle)
        result = builder.move_to_element(el)
        assert result is builder
        mock_page.mouse.move.assert_called_once_with(60.0, 45.0)

    def test_move_by_offset(self):
        mock_page = MagicMock()
        builder = CamoufoxActionChainBuilder(mock_page)
        result = builder.move_by_offset(10, 20)
        assert result is builder
        mock_page.mouse.move.assert_called_once_with(10.0, 20.0)

    def test_click(self):
        mock_page = MagicMock()
        builder = CamoufoxActionChainBuilder(mock_page)
        builder._current_x = 100
        builder._current_y = 200
        result = builder.click()
        assert result is builder
        mock_page.mouse.click.assert_called_once_with(100, 200)

    def test_click_on_element(self):
        mock_page = MagicMock()
        mock_handle = MagicMock()
        mock_handle.bounding_box.return_value = {"x": 10, "y": 20, "width": 100, "height": 50}
        builder = CamoufoxActionChainBuilder(mock_page)
        el = CamoufoxElement(mock_handle)
        result = builder.click(el)
        assert result is builder
        mock_page.mouse.click.assert_called_once_with(60.0, 45.0)

    def test_click_and_hold_and_release(self):
        mock_page = MagicMock()
        builder = CamoufoxActionChainBuilder(mock_page)
        builder.click_and_hold()
        mock_page.mouse.down.assert_called_once()
        builder.release()
        mock_page.mouse.up.assert_called_once()

    def test_perform_is_noop(self):
        mock_page = MagicMock()
        builder = CamoufoxActionChainBuilder(mock_page)
        builder.perform()  # should not raise


class TestCamoufoxBrowserContext:
    def test_get(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        ctx.get("https://example.com")
        mock_page.goto.assert_called_once_with("https://example.com")

    def test_execute_script_without_args(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate.return_value = "result"
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        result = ctx.execute_script("return navigator.userAgent")
        assert result == "result"
        mock_page.evaluate.assert_called_once()

    def test_execute_script_with_args(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate.return_value = None
        mock_handle = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        el = CamoufoxElement(mock_handle)
        ctx.execute_script("arguments[0].scrollIntoView();", el)
        mock_page.evaluate.assert_called_once()
        # Verify the script was rewritten to use __args
        script_arg = mock_page.evaluate.call_args[0][0]
        assert "__args" in script_arg

    def test_find_element(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_handle = MagicMock()
        mock_page.query_selector.return_value = mock_handle
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        el = ctx.find_element("css selector", "div")
        assert isinstance(el, CamoufoxElement)

    def test_find_element_not_found(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.query_selector.return_value = None
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        with pytest.raises(Exception, match="Element not found"):
            ctx.find_element("css selector", "div")

    def test_find_elements(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_handles = [MagicMock(), MagicMock()]
        mock_page.query_selector_all.return_value = mock_handles
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        elements = ctx.find_elements("css selector", "div")
        assert len(elements) == 2

    def test_page_source(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.content.return_value = "<html></html>"
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        assert ctx.page_source == "<html></html>"

    def test_title(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.title.return_value = "Example"
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        assert ctx.title == "Example"

    def test_current_url(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        assert ctx.current_url == "https://example.com"

    def test_add_cookie(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.context = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        ctx.add_cookie({"name": "test", "value": "123"})
        mock_page.context.add_cookies.assert_called_once()

    def test_delete_cookie(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.context = MagicMock()
        mock_page.context.cookies.return_value = [
            {"name": "keep", "value": "1"},
            {"name": "remove", "value": "2"},
        ]
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        ctx.delete_cookie("remove")
        mock_page.context.clear_cookies.assert_called_once()
        # Should re-add only the "keep" cookie
        assert mock_page.context.add_cookies.call_count == 1
        added = mock_page.context.add_cookies.call_args[0][0]
        assert len(added) == 1
        assert added[0]["name"] == "keep"

    def test_get_cookies(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.context = MagicMock()
        mock_page.context.cookies.return_value = [{"name": "test"}]
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        assert ctx.get_cookies() == [{"name": "test"}]

    def test_get_screenshot_as_base64(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.screenshot.return_value = "base64data"
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        assert ctx.get_screenshot_as_base64() == "base64data"
        mock_page.screenshot.assert_called_once_with(type="base64")

    def test_switch_to_default_content(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        ctx.switch_to_default_content()  # no-op, should not raise

    def test_alert_handling(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        # No alert yet
        assert ctx.get_alert_text() == ""
        # Simulate dialog event
        mock_dialog = MagicMock()
        mock_dialog.message = "alert message"
        ctx._on_dialog(mock_dialog)
        assert ctx.get_alert_text() == "alert message"
        ctx.dismiss_alert()
        mock_dialog.dismiss.assert_called_once()

    def test_close_and_quit(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        ctx.close()
        mock_browser.close.assert_called_once()
        ctx.quit()
        mock_camoufox.__exit__.assert_called_once()

    def test_execute_cdp_cmd_is_noop(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        result = ctx.execute_cdp_cmd("Network.enable", {})
        assert result is None

    def test_action_chain(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        builder = ctx.action_chain()
        assert isinstance(builder, CamoufoxActionChainBuilder)

    def test_wait_for_presence(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_handle = MagicMock()
        mock_page.wait_for_selector.return_value = mock_handle
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        el = ctx.wait_for_presence("css selector", "div", 5)
        assert isinstance(el, CamoufoxElement)
        mock_page.wait_for_selector.assert_called_once_with("div", state="attached", timeout=5000.0)

    def test_wait_for_absence(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.query_selector.return_value = None
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        result = ctx.wait_for_absence("css selector", "div", 1)
        assert result is True

    def test_wait_for_visibility(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_handle = MagicMock()
        mock_page.wait_for_selector.return_value = mock_handle
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        el = ctx.wait_for_visibility("css selector", "div", 5)
        assert isinstance(el, CamoufoxElement)
        mock_page.wait_for_selector.assert_called_once_with("div", state="visible", timeout=5000.0)

    def test_wait_for_title(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.title.return_value = "Target"
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        result = ctx.wait_for_title("Target", 1)
        assert result is True

    def test_wait_for_title_not(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.title.return_value = "Different"
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        result = ctx.wait_for_title_not("Target", 1)
        assert result is True

    def test_wait_for_staleness(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_handle = MagicMock()
        mock_handle.evaluate.side_effect = Exception("detached")
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        el = CamoufoxElement(mock_handle)
        result = ctx.wait_for_staleness(el, 1)
        assert result is True

    def test_get_user_agent(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate.return_value = "Mozilla/5.0"
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        assert ctx.get_user_agent() == "Mozilla/5.0"

    def test_apply_user_agent_override(self):
        mock_camoufox = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        ctx = CamoufoxBrowserContext(mock_camoufox, mock_browser, mock_page)
        ctx.apply_user_agent_override("custom-ua")  # no-op, should not raise

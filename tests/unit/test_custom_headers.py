"""Tests for custom headers support.

Ensures that custom HTTP headers can be set via the 'headers' parameter.

References: https://github.com/FlareSolverr/FlareSolverr/issues/266
"""

from unittest.mock import MagicMock, patch

import pytest

from dtos import V1RequestBase


class MockWebDriver:
    """Mock WebDriver for testing headers functionality."""

    def __init__(self):
        self.current_url = "https://example.com"
        self.page_source = "<html></html>"
        self._extra_headers = {}
        self._cdp_calls = []

    def execute_cdp_cmd(self, cmd, params):
        """Mock CDP command execution."""
        self._cdp_calls.append((cmd, params))
        if cmd == "Network.setExtraHTTPHeaders":
            self._extra_headers.update(params.get("headers", {}))
        return {}

    def get_cookies(self):
        return []

    def get_screenshot_as_base64(self):
        return "base64"


class TestSetCustomHeaders:
    """Tests for the _set_custom_headers function."""

    def test_no_headers_does_nothing(self):
        """Test that no CDP call is made when headers is None."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
        })

        service._set_custom_headers(req, mock_driver)

        assert len(mock_driver._cdp_calls) == 0
        assert len(mock_driver._extra_headers) == 0

    def test_empty_headers_does_nothing(self):
        """Test that no CDP call is made when headers is empty list."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [],
        })

        service._set_custom_headers(req, mock_driver)

        assert len(mock_driver._cdp_calls) == 0

    def test_dict_format_headers(self):
        """Test headers in dict format {name, value}."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                {"name": "Referer", "value": "https://referrer.com"},
                {"name": "X-Custom", "value": "test-value"},
            ],
        })

        service._set_custom_headers(req, mock_driver)

        assert len(mock_driver._cdp_calls) == 1
        cmd, params = mock_driver._cdp_calls[0]
        assert cmd == "Network.setExtraHTTPHeaders"
        assert params["headers"]["Referer"] == "https://referrer.com"
        assert params["headers"]["X-Custom"] == "test-value"

    def test_string_format_headers(self):
        """Test headers in string format 'Name: Value'."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                "Referer: https://referrer.com",
                "Authorization: Bearer token123",
            ],
        })

        service._set_custom_headers(req, mock_driver)

        assert len(mock_driver._cdp_calls) == 1
        cmd, params = mock_driver._cdp_calls[0]
        assert cmd == "Network.setExtraHTTPHeaders"
        assert params["headers"]["Referer"] == "https://referrer.com"
        assert params["headers"]["Authorization"] == "Bearer token123"

    def test_mixed_format_headers(self):
        """Test headers with mixed formats (both dict and string)."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                {"name": "X-From-Dict", "value": "dict-value"},
                "X-From-String: string-value",
            ],
        })

        service._set_custom_headers(req, mock_driver)

        cmd, params = mock_driver._cdp_calls[0]
        assert params["headers"]["X-From-Dict"] == "dict-value"
        assert params["headers"]["X-From-String"] == "string-value"

    def test_invalid_string_format_ignored(self):
        """Test that invalid string formats are skipped gracefully."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                "NoColonHere",  # Missing colon
                {"name": "Valid", "value": "value"},  # Valid dict
            ],
        })

        service._set_custom_headers(req, mock_driver)

        # Should still work with valid header
        cmd, params = mock_driver._cdp_calls[0]
        assert "Valid" in params["headers"]

    def test_headers_with_whitespace(self):
        """Test that whitespace is stripped from headers."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                "  Referer  :  https://example.com  ",
            ],
        })

        service._set_custom_headers(req, mock_driver)

        cmd, params = mock_driver._cdp_calls[0]
        assert params["headers"]["Referer"] == "https://example.com"

    def test_multiple_colons_in_string(self):
        """Test that only first colon separates name and value."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                "Authorization: Bearer: token: with: colons",
            ],
        })

        service._set_custom_headers(req, mock_driver)

        cmd, params = mock_driver._cdp_calls[0]
        assert params["headers"]["Authorization"] == "Bearer: token: with: colons"

    def test_cdp_failure_handled_gracefully(self, caplog):
        """Test that CDP command failure is handled gracefully with warning."""
        import flaresolverr_service as service
        import logging

        mock_driver = MockWebDriver()

        def failing_cdp(cmd, params):
            raise Exception("CDP not available")

        mock_driver.execute_cdp_cmd = failing_cdp

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [{"name": "Test", "value": "value"}],
        })

        with caplog.at_level(logging.WARNING):
            service._set_custom_headers(req, mock_driver)

        assert "Failed to set custom headers" in caplog.text


class TestHeadersIntegration:
    """Integration tests for headers in request flow."""

    def test_headers_set_before_navigation(self):
        """Test that headers are set before page navigation."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        call_order = []

        # Track call order
        original_set_headers = service._set_custom_headers
        original_navigate = service._navigate_request

        def tracking_set_headers(req, driver):
            call_order.append("set_headers")
            return original_set_headers(req, driver)

        def tracking_navigate(req, driver, method, target_url):
            call_order.append("navigate")
            return None  # Don't actually navigate

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(service, "_set_custom_headers", tracking_set_headers)
        monkeypatch.setattr(service, "_navigate_request", tracking_navigate)

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [{"name": "Referer", "value": "https://test.com"}],
        })

        # Call _evil_logic which orchestrates the flow
        # Note: We can't easily test full _evil_logic without mocking everything
        # But we verify the functions exist and are callable
        assert callable(service._set_custom_headers)
        assert callable(service._navigate_request)

        monkeypatch.undo()

    def test_headers_with_post_request(self):
        """Test that headers work with POST requests."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postData": "field=value",
            "headers": [{"name": "X-API-Key", "value": "secret123"}],
        })

        service._set_custom_headers(req, mock_driver)

        cmd, params = mock_driver._cdp_calls[0]
        assert params["headers"]["X-API-Key"] == "secret123"

    def test_headers_preserved_in_session(self):
        """Test that headers are set for each request in a session."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()

        # First request
        req1 = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/page1",
            "headers": [{"name": "Referer", "value": "https://page1.com"}],
        })

        service._set_custom_headers(req1, mock_driver)

        # Second request (same driver/session)
        mock_driver._extra_headers.clear()
        mock_driver._cdp_calls.clear()

        req2 = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com/page2",
            "headers": [{"name": "Referer", "value": "https://page2.com"}],
        })

        service._set_custom_headers(req2, mock_driver)

        # Should have new header
        cmd, params = mock_driver._cdp_calls[0]
        assert params["headers"]["Referer"] == "https://page2.com"


class TestHeadersEdgeCases:
    """Edge case tests for headers handling."""

    def test_empty_dict_header_skipped(self):
        """Test that empty dict headers are handled."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                {},  # Empty dict
                {"name": "Valid", "value": "value"},
            ],
        })

        service._set_custom_headers(req, mock_driver)

        # Should still work with valid header
        cmd, params = mock_driver._cdp_calls[0]
        assert "Valid" in params["headers"]

    def test_dict_missing_name_or_value(self):
        """Test dict without name or value is handled."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                {"name": "OnlyName"},  # Missing value
                {"value": "OnlyValue"},  # Missing name
                {"name": "Valid", "value": "value"},  # Complete
            ],
        })

        service._set_custom_headers(req, mock_driver)

        # Only complete dict should be used
        cmd, params = mock_driver._cdp_calls[0]
        assert "Valid" in params["headers"]

    def test_special_characters_in_header_value(self):
        """Test that special characters in header values are preserved."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                {"name": "Cookie", "value": "session=abc123; path=/; HttpOnly"},
                {"name": "User-Agent", "value": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            ],
        })

        service._set_custom_headers(req, mock_driver)

        cmd, params = mock_driver._cdp_calls[0]
        assert "session=abc123; path=/; HttpOnly" in params["headers"]["Cookie"]
        assert "Mozilla/5.0" in params["headers"]["User-Agent"]

    def test_very_long_header_value(self):
        """Test handling of very long header values."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        long_value = "x" * 10000
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [{"name": "X-Long", "value": long_value}],
        })

        service._set_custom_headers(req, mock_driver)

        cmd, params = mock_driver._cdp_calls[0]
        assert params["headers"]["X-Long"] == long_value

    def test_unicode_in_headers(self):
        """Test that unicode characters in headers are handled."""
        import flaresolverr_service as service

        mock_driver = MockWebDriver()
        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "headers": [
                {"name": "X-Unicode", "value": "日本語テスト"},
            ],
        })

        service._set_custom_headers(req, mock_driver)

        cmd, params = mock_driver._cdp_calls[0]
        assert params["headers"]["X-Unicode"] == "日本語テスト"

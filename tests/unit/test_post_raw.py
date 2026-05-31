"""Tests for raw POST data support (postDataRaw / postDataContentType)."""

from unittest.mock import patch

from flaresolverr.dtos import V1RequestBase


class MockDriverRawPost:
    """Mock WebDriver that simulates CDP Fetch interception for raw POST."""

    def __init__(self, simulate_fail=False, missing_logs=False):
        self.current_url = "https://example.com"
        self.page_source = "<html><body>OK</body></html>"
        self._cdp_calls = []
        self._simulate_fail = simulate_fail
        self._missing_logs = missing_logs
        self._fetch_enabled = False
        self._navigated = False
        self._logs_consumed = False

    def execute_cdp_cmd(self, cmd, params):
        self._cdp_calls.append((cmd, params))
        if cmd == "Fetch.enable":
            self._fetch_enabled = True
            return {}
        if cmd == "Fetch.disable":
            self._fetch_enabled = False
            return {}
        if cmd == "Page.navigate":
            self._navigated = True
            return {"frameId": "mock-frame", "loaderId": "mock-loader"}
        if cmd == "Fetch.continueRequest":
            return {}
        return {}

    def get_log(self, log_type):
        if log_type != "performance":
            return []
        if self._missing_logs or self._logs_consumed:
            return []
        self._logs_consumed = True
        if self._simulate_fail:
            return []
        return [
            {
                "message": '{"message": {"method": "Fetch.requestPaused", "params": {"requestId": "req-1", "request": {"url": "https://example.com/api"}, "resourceType": "Document"}}}'
            }
        ]

    def execute_script(self, script):
        if "document.readyState" in script:
            return "complete"
        return None


class TestPostRawValidation:
    """Tests for request validation with postDataRaw."""

    def test_post_missing_body_raises(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({"cmd": "request.post", "url": "https://example.com"})
        with patch.object(service, "_resolve_challenge"):
            try:
                service._cmd_request_post(req)
                assert False, "Expected exception"
            except Exception as e:
                assert "postData" in str(e) and "postDataRaw" in str(e)

    def test_post_with_both_bodies_raises(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com",
            "postData": "a=b",
            "postDataRaw": "{\"a\": \"b\"}",
        })
        with patch.object(service, "_resolve_challenge"):
            try:
                service._cmd_request_post(req)
                assert False, "Expected exception"
            except Exception as e:
                assert "Cannot use both" in str(e)

    def test_get_with_postDataRaw_raises(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.get",
            "url": "https://example.com",
            "postDataRaw": "test",
        })
        with patch.object(service, "_resolve_challenge"):
            try:
                service._cmd_request_get(req)
                assert False, "Expected exception"
            except Exception as e:
                assert "postDataRaw" in str(e)

    def test_post_with_postDataRaw_ok(self):
        """Validation should pass when only postDataRaw is provided."""
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com",
            "postDataRaw": "{\"key\": \"value\"}",
            "postDataContentType": "application/json",
        })
        with patch.object(service, "_resolve_challenge") as mock_resolve:
            service._cmd_request_post(req)
            assert mock_resolve.called


class TestPostRawCdpFlow:
    """Tests for the CDP-based raw POST flow."""

    def test_fetch_enable_and_navigate(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": '{"key": "value"}',
            "postDataContentType": "application/json",
        })
        driver = MockDriverRawPost()
        service._post_request_raw(req, driver)

        assert driver._navigated
        # Check Fetch.enable was called with wildcard pattern
        enable_cmd = [c for c in driver._cdp_calls if c[0] == "Fetch.enable"]
        assert len(enable_cmd) == 1
        assert enable_cmd[0][1]["patterns"][0]["urlPattern"] == "*"
        # Fetch.disable should also be called for cleanup
        disable_cmd = [c for c in driver._cdp_calls if c[0] == "Fetch.disable"]
        assert len(disable_cmd) == 1

    def test_continue_request_with_headers(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": '{"key": "value"}',
            "postDataContentType": "application/json",
            "headers": [{"name": "X-Custom", "value": "123"}],
        })
        driver = MockDriverRawPost()
        service._post_request_raw(req, driver)

        continue_calls = [c for c in driver._cdp_calls if c[0] == "Fetch.continueRequest"]
        assert len(continue_calls) == 1
        params = continue_calls[0][1]
        assert params["method"] == "POST"
        assert params["requestId"] == "req-1"
        # Check Content-Type header is present
        header_names = {h["name"] for h in params["headers"]}
        assert "Content-Type" in header_names
        assert "X-Custom" in header_names

    def test_disable_called_after_completion(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": "test",
        })
        driver = MockDriverRawPost()
        service._post_request_raw(req, driver)

        disable_calls = [c for c in driver._cdp_calls if c[0] == "Fetch.disable"]
        assert len(disable_calls) == 1

    def test_fails_when_intercept_not_found(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": "test",
        })
        driver = MockDriverRawPost(simulate_fail=True)
        try:
            service._post_request_raw(req, driver)
            assert False, "Expected exception"
        except Exception as e:
            assert "Failed to intercept" in str(e)

    def test_post_request_delegates_to_raw(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": "test",
        })
        driver = MockDriverRawPost()
        service._post_request(req, driver)

        # Should have gone through the raw path
        assert driver._navigated

    def test_post_request_uses_form_for_postData(self):
        from flaresolverr import flaresolverr_service as service

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postData": "field=value",
        })

        class MinimalDriver:
            def __init__(self):
                self._url = None

            def get(self, url):
                self._url = url

        driver = MinimalDriver()
        service._post_request(req, driver)

        assert driver._url is not None
        assert "hackForm" in driver._url


class TestDtoFields:
    """Tests for the new DTO fields."""

    def test_postDataRaw_field_exists(self):
        req = V1RequestBase({"postDataRaw": "raw body"})
        assert req.postDataRaw == "raw body"

    def test_postDataContentType_field_exists(self):
        req = V1RequestBase({"postDataContentType": "application/json"})
        assert req.postDataContentType == "application/json"

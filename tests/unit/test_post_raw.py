"""Tests for raw POST data support (postDataRaw / postDataContentType)."""

from unittest.mock import patch

from flaresolverr.dtos import V1RequestBase

from flaresolverr import flaresolverr_service as service


class MockDriverRawPost:
    """Mock WebDriver that simulates JavaScript XHR raw POST."""

    def __init__(self, simulate_fail=False, missing_logs=False):
        self.current_url = "https://example.com"
        self.page_source = "<html><body>OK</body></html>"
        self._get_url = None
        self._scripts = []
        self._simulate_fail = simulate_fail
        self._missing_logs = missing_logs
        self._xhr_done = False

    def get(self, url):
        self._get_url = url

    def execute_script(self, script):
        self._scripts.append(script)
        if "document.readyState" in script:
            return "complete"
        if "__flaresolverr_raw_post_done" in script:
            if not self._xhr_done:
                self._xhr_done = True
            return self._xhr_done
        if "__flaresolverr_raw_post_error" in script:
            if self._simulate_fail:
                return "CORS error"
            return None
        return None


class TestPostRawValidation:
    """Tests for request validation with postDataRaw."""

    def test_post_missing_body_raises(self):

        req = V1RequestBase({"cmd": "request.post", "url": "https://example.com"})
        with patch.object(service, "_resolve_challenge"):
            try:
                service._cmd_request_post(req)
                assert False, "Expected exception"
            except Exception as e:
                assert "postData" in str(e) and "postDataRaw" in str(e)

    def test_post_with_both_bodies_raises(self):

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

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com",
            "postDataRaw": "{\"key\": \"value\"}",
            "postDataContentType": "application/json",
        })
        with patch.object(service, "_resolve_challenge") as mock_resolve:
            service._cmd_request_post(req)
            assert mock_resolve.called


class TestPostRawJsFlow:
    """Tests for the JavaScript XHR-based raw POST flow."""

    def test_navigates_to_target_url(self):

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": '{"key": "value"}',
            "postDataContentType": "application/json",
        })
        driver = MockDriverRawPost()
        service._post_request_raw(req, driver)

        assert driver._get_url == "https://example.com/api"

    def test_executes_xhr_script_with_headers(self):

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": '{"key": "value"}',
            "postDataContentType": "application/json",
            "headers": [{"name": "X-Custom", "value": "123"}],
        })
        driver = MockDriverRawPost()
        service._post_request_raw(req, driver)

        # The first script should be the XHR script
        assert len(driver._scripts) >= 1
        xhr_script = driver._scripts[0]
        assert "XMLHttpRequest" in xhr_script
        assert "https://example.com/api" in xhr_script
        assert "Content-Type" in xhr_script
        assert "X-Custom" in xhr_script
        assert "\\\"key\\\": \\\"value\\\"" in xhr_script

    def test_executes_xhr_script_with_default_content_type(self):

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": "test",
        })
        driver = MockDriverRawPost()
        service._post_request_raw(req, driver)

        xhr_script = driver._scripts[0]
        assert "application/x-www-form-urlencoded" in xhr_script

    def test_fails_when_xhr_raises_error(self):

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
            assert "Raw POST request failed" in str(e)

    def test_post_request_delegates_to_raw(self):

        req = V1RequestBase({
            "cmd": "request.post",
            "url": "https://example.com/api",
            "postDataRaw": "test",
        })
        driver = MockDriverRawPost()
        service._post_request(req, driver)

        # Should have gone through the raw path (driver.get called)
        assert driver._get_url == "https://example.com/api"

    def test_post_request_uses_form_for_postData(self):

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

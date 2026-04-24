"""Unit tests for the FlareSolverr Python client library."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from flaresolverr.client import ActionQueue, FlareSolverrClient, FlareSolverrError
from flaresolverr.client.models import (
    Action,
    Cookie,
    Header,
    HealthResponse,
    IndexResponse,
    ProxyConfig,
    V1Response,
)


# ---------------------------------------------------------------------------
# ActionQueue
# ---------------------------------------------------------------------------

class TestActionQueue:
    def test_empty_queue(self):
        q = ActionQueue()
        assert len(q) == 0
        assert not q
        assert q.build() == []

    def test_wait(self):
        result = ActionQueue().wait(2.5).build()
        assert result == [{"type": "wait", "seconds": 2.5}]

    def test_fill(self):
        result = ActionQueue().fill("//input[@id='email']", "user@example.com").build()
        assert result == [{"type": "fill", "selector": "//input[@id='email']", "value": "user@example.com"}]

    def test_click_default(self):
        result = ActionQueue().click("//button").build()
        assert result == [{"type": "click", "selector": "//button"}]

    def test_click_human_like(self):
        result = ActionQueue().click("//button", human_like=True).build()
        assert result == [{"type": "click", "selector": "//button", "humanLike": True}]

    def test_wait_for(self):
        result = ActionQueue().wait_for("//div[@id='result']").build()
        assert result == [{"type": "wait_for", "selector": "//div[@id='result']"}]

    def test_chaining(self):
        result = (
            ActionQueue()
            .wait(1)
            .fill("//input[@id='u']", "user")
            .click("//button")
            .wait_for("//div[@id='ok']")
            .build()
        )
        assert len(result) == 4
        assert result[0]["type"] == "wait"
        assert result[1]["type"] == "fill"
        assert result[2]["type"] == "click"
        assert result[3]["type"] == "wait_for"

    def test_internals_use_action_objects(self):
        q = ActionQueue().wait(1).fill("//x", "y").click("//btn")
        assert all(isinstance(a, Action) for a in q._actions)

    def test_build_returns_dicts(self):
        result = ActionQueue().wait(1).build()
        assert isinstance(result[0], dict)

    def test_build_returns_copy(self):
        q = ActionQueue().wait(1)
        a = q.build()
        a.append({"type": "extra"})
        assert len(q.build()) == 1

    def test_clear(self):
        q = ActionQueue().wait(1).fill("//x", "y")
        q.clear()
        assert len(q) == 0

    def test_bool_true(self):
        assert ActionQueue().wait(1)

    def test_bool_false(self):
        assert not ActionQueue()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestAction:
    def test_fill_to_dict(self):
        a = Action(type="fill", selector="//input", value="hello")
        assert a.to_dict() == {"type": "fill", "selector": "//input", "value": "hello"}

    def test_click_human_like_to_dict(self):
        a = Action(type="click", selector="//btn", humanLike=True)
        assert a.to_dict() == {"type": "click", "selector": "//btn", "humanLike": True}

    def test_click_default_omits_human_like(self):
        a = Action(type="click", selector="//btn")
        assert "humanLike" not in a.to_dict()

    def test_wait_to_dict(self):
        a = Action(type="wait", seconds=2.5)
        assert a.to_dict() == {"type": "wait", "seconds": 2.5}

    def test_wait_for_to_dict(self):
        a = Action(type="wait_for", selector="//div")
        assert a.to_dict() == {"type": "wait_for", "selector": "//div"}


class TestCookie:
    def test_required_fields_only(self):
        c = Cookie(name="session", value="abc123")
        assert c.name == "session"
        assert c.value == "abc123"
        assert c.domain == ""
        assert c.path == "/"

    def test_full_construction(self):
        c = Cookie(name="cf", value="tok", domain=".example.com", path="/", secure=True)
        assert c.domain == ".example.com"
        assert c.secure is True

    def test_from_dict_full(self):
        data = {
            "name": "cf_clearance",
            "value": "xyz",
            "domain": ".example.com",
            "path": "/",
            "expires": 9999999999.0,
            "size": 40,
            "httpOnly": False,
            "secure": True,
            "session": False,
            "sameSite": "None",
        }
        c = Cookie.from_dict(data)
        assert c.name == "cf_clearance"
        assert c.value == "xyz"
        assert c.domain == ".example.com"
        assert c.secure is True
        assert c.sameSite == "None"

    def test_from_dict_minimal(self):
        c = Cookie.from_dict({"name": "x", "value": "y"})
        assert c.name == "x"
        assert c.domain == ""
        assert c.path == "/"


class TestProxyConfig:
    def test_to_dict_url_only(self):
        p = ProxyConfig(url="http://proxy:8080")
        assert p.to_dict() == {"url": "http://proxy:8080"}

    def test_to_dict_with_credentials(self):
        p = ProxyConfig(url="http://proxy:8080", username="u", password="p")
        d = p.to_dict()
        assert d["username"] == "u"
        assert d["password"] == "p"


class TestHeader:
    def test_to_dict(self):
        h = Header(name="X-Custom", value="value123")
        assert h.to_dict() == {"name": "X-Custom", "value": "value123"}


class TestV1Response:
    def _make_response_dict(self, **overrides):
        base = {
            "status": "ok",
            "message": "Challenge not detected!",
            "solution": {
                "url": "https://example.com",
                "status": 200,
                "headers": {},
                "response": "<html>...</html>",
                "cookies": [{"name": "cf", "value": "tok", "domain": ".example.com", "path": "/"}],
                "userAgent": "Mozilla/5.0",
            },
            "startTimestamp": 1000,
            "endTimestamp": 2000,
            "version": "3.5.2",
        }
        base.update(overrides)
        return base

    def test_is_ok(self):
        r = V1Response.from_dict(self._make_response_dict())
        assert r.is_ok is True

    def test_is_not_ok(self):
        r = V1Response.from_dict(self._make_response_dict(status="error"))
        assert r.is_ok is False

    def test_solution_parsed(self):
        r = V1Response.from_dict(self._make_response_dict())
        assert r.solution is not None
        assert r.solution.url == "https://example.com"
        assert r.solution.status == 200
        assert len(r.solution.cookies) == 1
        assert r.solution.cookies[0].name == "cf"

    def test_no_solution(self):
        r = V1Response.from_dict({"status": "ok", "message": "Session created.", "session": "abc"})
        assert r.solution is None
        assert r.session == "abc"

    def test_sessions_list(self):
        r = V1Response.from_dict({"status": "ok", "message": "", "sessions": ["s1", "s2"]})
        assert r.sessions == ["s1", "s2"]

    def test_turnstile_token(self):
        d = self._make_response_dict()
        d["solution"]["turnstile_token"] = "token123"
        r = V1Response.from_dict(d)
        assert r.solution is not None
        assert r.solution.turnstile_token == "token123"


class TestHealthResponse:
    def test_from_dict(self):
        h = HealthResponse.from_dict({"status": "ok"})
        assert h.status == "ok"


class TestIndexResponse:
    def test_from_dict(self):
        i = IndexResponse.from_dict({"msg": "FlareSolverr is ready!", "version": "3.5.2", "userAgent": "Mozilla/5.0"})
        assert i.msg == "FlareSolverr is ready!"
        assert i.version == "3.5.2"


# ---------------------------------------------------------------------------
# FlareSolverrClient — _build_payload
# ---------------------------------------------------------------------------

class TestRequestManagerPayload:
    def setup_method(self):
        self.client = FlareSolverrClient("http://localhost:8191")

    def _build_get_payload(self, **kwargs):
        return self.client.request._build_payload(cmd="request.get", url="https://example.com", **kwargs)

    def test_minimal_payload(self):
        p = self._build_get_payload()
        assert p == {"cmd": "request.get", "url": "https://example.com", "maxTimeout": 60000}

    def test_post_data(self):
        p = self.client.request._build_payload(cmd="request.post", url="https://x.com", post_data="a=1&b=2")
        assert p["postData"] == "a=1&b=2"

    def test_session(self):
        p = self._build_get_payload(session="my_session")
        assert p["session"] == "my_session"

    def test_cookies_serialized(self):
        c = Cookie(name="x", value="y")
        p = self._build_get_payload(cookies=[c])
        assert p["cookies"] == [{"name": "x", "value": "y"}]

    def test_headers_serialized(self):
        h = Header(name="Accept", value="text/html")
        p = self._build_get_payload(headers=[h])
        assert p["headers"] == [{"name": "Accept", "value": "text/html"}]

    def test_return_flags(self):
        p = self._build_get_payload(return_only_cookies=True, return_screenshot=True)
        assert p["returnOnlyCookies"] is True
        assert p["returnScreenshot"] is True

    def test_proxy(self):
        proxy = ProxyConfig(url="http://proxy:8080", username="u", password="p")
        p = self._build_get_payload(proxy=proxy)
        assert p["proxy"] == {"url": "http://proxy:8080", "username": "u", "password": "p"}

    def test_disable_media(self):
        p = self._build_get_payload(disable_media=True)
        assert p["disableMedia"] is True

    def test_disable_media_false_omitted(self):
        p = self._build_get_payload(disable_media=False)
        assert "disableMedia" not in p

    def test_tabs_till_verify(self):
        p = self._build_get_payload(tabs_till_verify=3)
        assert p["tabs_till_verify"] == 3

    def test_actions(self):
        actions = ActionQueue().click("//button").build()
        p = self._build_get_payload(actions=actions)
        assert p["actions"] == [{"type": "click", "selector": "//button"}]

    def test_captcha_solver(self):
        p = self._build_get_payload(captcha_solver="2captcha")
        assert p["captchaSolver"] == "2captcha"

    def test_stealth(self):
        p = self._build_get_payload(stealth=True)
        assert p["stealth"] is True

    def test_stealth_mode(self):
        p = self._build_get_payload(stealth_mode="csp-safe")
        assert p["stealthMode"] == "csp-safe"

    def test_user_agent(self):
        p = self._build_get_payload(user_agent="Mozilla/5.0 Test UA")
        assert p["userAgent"] == "Mozilla/5.0 Test UA"

    def test_stealth_none_omitted(self):
        p = self._build_get_payload()
        assert "stealth" not in p

    def test_post_method_has_tabs_till_verify(self):
        """post() exposes tabs_till_verify just like get()."""
        import inspect
        sig = inspect.signature(self.client.request.post)
        assert "tabs_till_verify" in sig.parameters


# ---------------------------------------------------------------------------
# FlareSolverrClient — HTTP layer (mocked)
# ---------------------------------------------------------------------------

class TestFlareSolverrClientHTTP:
    def _make_ok_response(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "message": "Challenge not detected!",
            "solution": {
                "url": "https://example.com",
                "status": 200,
                "headers": {},
                "response": "<html>hi</html>",
                "cookies": [],
                "userAgent": "Mozilla/5.0",
            },
            "startTimestamp": 1000,
            "endTimestamp": 2000,
            "version": "3.5.2",
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_get_request_posts_to_v1(self):
        client = FlareSolverrClient("http://localhost:8191")
        with patch("flaresolverr.client.client.requests.post") as mock_post:
            mock_post.return_value = self._make_ok_response()
            response = client.request.get("https://example.com")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "http://localhost:8191/v1"
        assert call_kwargs[1]["json"]["cmd"] == "request.get"
        assert call_kwargs[1]["json"]["url"] == "https://example.com"
        assert response.is_ok

    def test_post_request(self):
        client = FlareSolverrClient("http://localhost:8191")
        with patch("flaresolverr.client.client.requests.post") as mock_post:
            mock_post.return_value = self._make_ok_response()
            client.request.post("https://example.com/login", "user=x&pass=y")

        payload = mock_post.call_args[1]["json"]
        assert payload["cmd"] == "request.post"
        assert payload["postData"] == "user=x&pass=y"

    def test_error_status_raises(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "error", "message": "Timeout after 60 seconds."}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.post", return_value=mock_resp):
            with pytest.raises(FlareSolverrError) as exc_info:
                client.request.get("https://example.com")
        assert "Timeout" in str(exc_info.value)
        assert exc_info.value.response is not None

    def test_http_error_propagates(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("503")
        with patch("flaresolverr.client.client.requests.post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                client.request.get("https://example.com")

    def test_health_endpoint(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.get", return_value=mock_resp) as mock_get:
            health = client.health()
        mock_get.assert_called_once_with("http://localhost:8191/health", timeout=120.0)
        assert health.status == "ok"

    def test_index_endpoint(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"msg": "FlareSolverr is ready!", "version": "3.5.2", "userAgent": "Mozilla/5.0"}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.get", return_value=mock_resp):
            idx = client.index()
        assert idx.version == "3.5.2"

    def test_base_url_trailing_slash_stripped(self):
        client = FlareSolverrClient("http://localhost:8191/")
        assert client.base_url == "http://localhost:8191"

    def test_session_create(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "message": "Session created.", "session": "abc123"}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.post", return_value=mock_resp):
            r = client.sessions.create("abc123")
        assert r.session == "abc123"

    def test_session_create_with_stealth(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "message": "Session created.", "session": "abc123"}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.post", return_value=mock_resp) as mock_post:
            client.sessions.create("abc123", stealth=True)
        payload = mock_post.call_args[1]["json"]
        assert payload["cmd"] == "sessions.create"
        assert payload["session"] == "abc123"
        assert payload["stealth"] is True

    def test_session_create_with_stealth_mode(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "message": "Session created.", "session": "abc123"}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.post", return_value=mock_resp) as mock_post:
            client.sessions.create("abc123", stealth_mode="csp-safe")
        payload = mock_post.call_args[1]["json"]
        assert payload["cmd"] == "sessions.create"
        assert payload["session"] == "abc123"
        assert payload["stealthMode"] == "csp-safe"

    def test_session_create_with_user_agent(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "message": "Session created.", "session": "abc123"}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.post", return_value=mock_resp) as mock_post:
            client.sessions.create("abc123", user_agent="Mozilla/5.0 Test UA")
        payload = mock_post.call_args[1]["json"]
        assert payload["cmd"] == "sessions.create"
        assert payload["session"] == "abc123"
        assert payload["userAgent"] == "Mozilla/5.0 Test UA"

    def test_session_destroy(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "message": "The session has been removed."}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.post", return_value=mock_resp) as mock_post:
            client.sessions.destroy("abc123")
        payload = mock_post.call_args[1]["json"]
        assert payload["cmd"] == "sessions.destroy"
        assert payload["session"] == "abc123"

    def test_session_list(self):
        client = FlareSolverrClient("http://localhost:8191")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "message": "", "sessions": ["s1", "s2"]}
        mock_resp.raise_for_status = MagicMock()
        with patch("flaresolverr.client.client.requests.post", return_value=mock_resp):
            r = client.sessions.list()
        assert r.sessions == ["s1", "s2"]

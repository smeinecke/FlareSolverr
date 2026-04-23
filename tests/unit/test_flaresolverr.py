import json
from types import SimpleNamespace

import pytest

pytest.importorskip("func_timeout")
from flaresolverr import flaresolverr


def test_default_error_handler_returns_json_body(monkeypatch) -> None:
    fake_response = SimpleNamespace(content_type=None)
    monkeypatch.setattr(flaresolverr, "response", fake_response)

    bottle = flaresolverr.JSONErrorBottle()
    payload = bottle.default_error_handler(SimpleNamespace(body="Not found", status_code=404))

    assert fake_response.content_type == "application/json"
    assert json.loads(payload) == {"error": "Not found", "status_code": 404}


def test_index_returns_serialized_endpoint_response(monkeypatch) -> None:
    endpoint_value = object()
    monkeypatch.setattr(flaresolverr.flaresolverr_service, "index_endpoint", lambda: endpoint_value)
    monkeypatch.setattr(flaresolverr.utils, "object_to_dict", lambda value: {"wrapped": value is endpoint_value})

    assert flaresolverr.index() == {"wrapped": True}


def test_health_returns_serialized_endpoint_response(monkeypatch) -> None:
    endpoint_value = object()
    monkeypatch.setattr(flaresolverr.flaresolverr_service, "health_endpoint", lambda: endpoint_value)
    monkeypatch.setattr(flaresolverr.utils, "object_to_dict", lambda value: {"wrapped": value is endpoint_value})

    assert flaresolverr.health() == {"wrapped": True}


def test_controller_v1_uses_env_proxy_url_only(monkeypatch) -> None:
    captured = {"req": None}

    monkeypatch.setattr(flaresolverr, "request", SimpleNamespace(json={"cmd": "request.get"}))
    monkeypatch.setattr(flaresolverr, "response", SimpleNamespace(status=200))
    monkeypatch.setattr(flaresolverr, "env_proxy_url", "http://proxy:8080")
    monkeypatch.setattr(flaresolverr, "env_proxy_username", None)
    monkeypatch.setattr(flaresolverr, "env_proxy_password", None)

    def fake_controller(req):
        captured["req"] = req
        return SimpleNamespace(__error_500__=False, ok=True)

    monkeypatch.setattr(flaresolverr.flaresolverr_service, "controller_v1_endpoint", fake_controller)
    monkeypatch.setattr(flaresolverr.utils, "object_to_dict", lambda res: {"ok": getattr(res, "ok", False)})

    result = flaresolverr.controller_v1()

    assert captured["req"].proxy == {"url": "http://proxy:8080"}
    assert result == {"ok": True}


def test_controller_v1_uses_env_proxy_with_credentials(monkeypatch) -> None:
    captured = {"req": None}

    monkeypatch.setattr(flaresolverr, "request", SimpleNamespace(json={"cmd": "request.get"}))
    monkeypatch.setattr(flaresolverr, "response", SimpleNamespace(status=200))
    monkeypatch.setattr(flaresolverr, "env_proxy_url", "http://proxy:8080")
    monkeypatch.setattr(flaresolverr, "env_proxy_username", "user")
    monkeypatch.setattr(flaresolverr, "env_proxy_password", "pass")

    def fake_controller(req):
        captured["req"] = req
        return SimpleNamespace(__error_500__=False)

    monkeypatch.setattr(flaresolverr.flaresolverr_service, "controller_v1_endpoint", fake_controller)
    monkeypatch.setattr(flaresolverr.utils, "object_to_dict", lambda _res: {"ok": True})

    flaresolverr.controller_v1()

    assert captured["req"].proxy == {"url": "http://proxy:8080", "username": "user", "password": "pass"}


def test_controller_v1_keeps_explicit_proxy_from_request(monkeypatch) -> None:
    explicit_proxy = {"url": "http://explicit:9999"}
    captured = {"req": None}

    monkeypatch.setattr(flaresolverr, "request", SimpleNamespace(json={"cmd": "request.get", "proxy": explicit_proxy}))
    monkeypatch.setattr(flaresolverr, "response", SimpleNamespace(status=200))
    monkeypatch.setattr(flaresolverr, "env_proxy_url", "http://env:8080")
    monkeypatch.setattr(flaresolverr, "env_proxy_username", "user")
    monkeypatch.setattr(flaresolverr, "env_proxy_password", "pass")

    def fake_controller(req):
        captured["req"] = req
        return SimpleNamespace(__error_500__=False)

    monkeypatch.setattr(flaresolverr.flaresolverr_service, "controller_v1_endpoint", fake_controller)
    monkeypatch.setattr(flaresolverr.utils, "object_to_dict", lambda _res: {"ok": True})

    flaresolverr.controller_v1()

    assert captured["req"].proxy == explicit_proxy


def test_controller_v1_sets_500_status_when_error_flagged(monkeypatch) -> None:
    monkeypatch.setattr(flaresolverr, "request", SimpleNamespace(json={}))
    fake_response = SimpleNamespace(status=200)
    monkeypatch.setattr(flaresolverr, "response", fake_response)
    monkeypatch.setattr(flaresolverr, "env_proxy_url", None)
    monkeypatch.setattr(flaresolverr, "env_proxy_username", None)
    monkeypatch.setattr(flaresolverr, "env_proxy_password", None)

    monkeypatch.setattr(flaresolverr.flaresolverr_service, "controller_v1_endpoint", lambda _req: SimpleNamespace(__error_500__=True, message="err"))
    monkeypatch.setattr(flaresolverr.utils, "object_to_dict", lambda res: {"message": res.message})

    result = flaresolverr.controller_v1()

    assert fake_response.status == 500
    assert result == {"message": "err"}

from datetime import datetime, timedelta

from flaresolverr import sessions


class DummyDriver:
    def __init__(self) -> None:
        self.closed = 0
        self.quitted = 0

    def close(self) -> None:
        self.closed += 1

    def quit(self) -> None:
        self.quitted += 1


def test_session_lifetime_is_timedelta() -> None:
    created_at = datetime.now() - timedelta(seconds=2)
    session = sessions.Session("sid", DummyDriver(), created_at, stealth_mode="off")

    assert session.lifetime() >= timedelta(seconds=2)


def test_create_returns_new_then_existing_session(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    driver = DummyDriver()
    calls = {"count": 0}

    def fake_get_webdriver(proxy, stealth_mode=None):
        calls["count"] += 1
        assert proxy == {"url": "http://proxy"}
        assert stealth_mode == "off"
        return driver

    monkeypatch.setattr(sessions.utils, "get_webdriver", fake_get_webdriver)
    monkeypatch.setattr(sessions.utils, "get_config_stealth_mode", lambda: "off")

    created, is_new = storage.create("abc", proxy={"url": "http://proxy"})
    reused, is_new_reused = storage.create("abc", proxy={"url": "http://proxy"})

    assert is_new is True
    assert is_new_reused is False
    assert created is reused
    assert calls["count"] == 1


def test_create_with_force_new_recreates_existing_session(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    first = DummyDriver()
    second = DummyDriver()
    drivers = iter([first, second])

    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy, stealth_mode=None: next(drivers))
    monkeypatch.setattr(sessions.utils, "PLATFORM_VERSION", "posix")

    old_session, _ = storage.create("recreate")
    new_session, is_new = storage.create("recreate", force_new=True)

    assert is_new is True
    assert new_session is not old_session
    assert first.quitted == 1
    assert second.quitted == 0


def test_destroy_returns_false_for_missing_session() -> None:
    storage = sessions.SessionsStorage()

    assert storage.destroy("missing") is False


def test_destroy_closes_driver_on_windows(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    driver = DummyDriver()

    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy, stealth_mode=None: driver)
    monkeypatch.setattr(sessions.utils, "PLATFORM_VERSION", "nt")

    storage.create("win")

    assert storage.destroy("win") is True
    assert driver.closed == 1
    assert driver.quitted == 1


def test_get_recreates_expired_session(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    first = DummyDriver()
    second = DummyDriver()
    drivers = iter([first, second])

    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy, stealth_mode=None: next(drivers))
    monkeypatch.setattr(sessions.utils, "PLATFORM_VERSION", "posix")

    initial_session, _ = storage.create("ttl")
    initial_session.created_at = datetime.now() - timedelta(minutes=20)

    refreshed, fresh = storage.get("ttl", ttl=timedelta(minutes=5))

    assert fresh is True
    assert refreshed is not initial_session
    assert first.quitted == 1


def test_get_returns_existing_when_not_expired(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    driver = DummyDriver()

    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy, stealth_mode=None: driver)

    created, _ = storage.create("ok")
    created.created_at = datetime.now() - timedelta(seconds=10)

    session, fresh = storage.get("ok", ttl=timedelta(minutes=5))

    assert fresh is False
    assert session is created


def test_session_ids_lists_all_ids(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy, stealth_mode=None: DummyDriver())

    storage.create("one")
    storage.create("two")

    assert set(storage.session_ids()) == {"one", "two"}


def test_create_rejects_stealth_mismatch_for_existing_session(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy, stealth_mode=None: DummyDriver())
    monkeypatch.setattr(sessions.utils, "get_config_stealth_mode", lambda: "off")

    storage.create("s1", stealth_mode="off")

    try:
        storage.create("s1", stealth_mode="standard")
        assert False, "Expected ValueError for stealth mismatch"
    except ValueError as e:
        assert "already exists with stealthMode='off'" in str(e)


def test_create_rejects_user_agent_mismatch_for_existing_session(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy, stealth_mode=None: DummyDriver())
    monkeypatch.setattr(sessions.utils, "apply_user_agent_override", lambda _driver, _ua: None)

    storage.create("ua-session", user_agent="UA-1")

    try:
        storage.create("ua-session", user_agent="UA-2")
        assert False, "Expected ValueError for userAgent mismatch"
    except ValueError as e:
        assert "already initialized with userAgent='UA-1'" in str(e)


def test_create_accepts_legacy_boolean_stealth_mode(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    seen = {}

    def fake_get_webdriver(_proxy, stealth_mode=None):
        seen["mode"] = stealth_mode
        return DummyDriver()

    monkeypatch.setattr(sessions.utils, "get_webdriver", fake_get_webdriver)

    storage.create("legacy-true", stealth_mode=True)
    assert seen["mode"] == "standard"

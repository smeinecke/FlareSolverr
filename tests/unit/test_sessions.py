from datetime import datetime, timedelta

import sessions


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
    session = sessions.Session("sid", DummyDriver(), created_at)

    assert session.lifetime() >= timedelta(seconds=2)


def test_create_returns_new_then_existing_session(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    driver = DummyDriver()
    calls = {"count": 0}

    def fake_get_webdriver(proxy):
        calls["count"] += 1
        assert proxy == {"url": "http://proxy"}
        return driver

    monkeypatch.setattr(sessions.utils, "get_webdriver", fake_get_webdriver)

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

    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy: next(drivers))
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

    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy: driver)
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

    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy: next(drivers))
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

    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy: driver)

    created, _ = storage.create("ok")
    created.created_at = datetime.now() - timedelta(seconds=10)

    session, fresh = storage.get("ok", ttl=timedelta(minutes=5))

    assert fresh is False
    assert session is created


def test_session_ids_lists_all_ids(monkeypatch) -> None:
    storage = sessions.SessionsStorage()
    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda _proxy: DummyDriver())

    storage.create("one")
    storage.create("two")

    assert set(storage.session_ids()) == {"one", "two"}

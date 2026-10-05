"""Fault injection: dependencies misbehaving at system boundaries.

Covers the failure modes of session lifecycle and driver setup — browser
processes must never leak on the error paths, and cleanup must run even
when driver.quit() itself blows up.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from flaresolverr import sessions, utils


class DummyDriver:
    def __init__(self) -> None:
        self.closed = 0
        self.quitted = 0
        self.quit_exc: Exception | None = None
        self.browser_pid: int | None = None

    def close(self) -> None:
        self.closed += 1

    def quit(self) -> None:
        self.quitted += 1
        if self.quit_exc:
            raise self.quit_exc


def _storage(monkeypatch: pytest.MonkeyPatch, driver=None) -> tuple[sessions.SessionsStorage, Any]:
    monkeypatch.setattr(sessions.utils, "get_webdriver", lambda *_a, **_kw: driver or DummyDriver())
    monkeypatch.setattr(sessions.utils, "_cleanup_orphaned_temp_dirs", lambda: None)
    monkeypatch.setattr(sessions, "_ensure_process_dead", lambda _pid: None)
    monkeypatch.setattr(utils.os, "waitpid", lambda *_a: (_ for _ in ()).throw(ChildProcessError()))
    return sessions.SessionsStorage(), driver


class TestCreateFaults:
    def test_webdriver_failure_stores_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a, **_kw):
            raise RuntimeError("chrome failed to start")

        monkeypatch.setattr(sessions.utils, "get_webdriver", boom)
        storage = sessions.SessionsStorage()

        with pytest.raises(RuntimeError, match="chrome failed"):
            storage.create("s1")
        assert not storage.exists("s1")
        assert storage.session_ids() == []

    def test_ua_override_failure_quits_driver_and_stores_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A CDP failure during post-launch setup must not leak the browser."""
        driver = DummyDriver()
        storage, _ = _storage(monkeypatch, driver)
        monkeypatch.setattr(sessions.utils, "apply_user_agent_override", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("CDP dead")))

        with pytest.raises(RuntimeError, match="CDP dead"):
            storage.create("s1", user_agent="custom-ua")

        assert driver.quitted == 1, "driver must be quit on setup failure"
        assert not storage.exists("s1")

    def test_quit_failure_during_cleanup_does_not_mask_original_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = DummyDriver()
        driver.quit_exc = RuntimeError("quit also failed")
        storage, _ = _storage(monkeypatch, driver)
        monkeypatch.setattr(sessions.utils, "apply_user_agent_override", lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("original")))

        with pytest.raises(ValueError, match="original"):
            storage.create("s1", user_agent="ua")
        assert not storage.exists("s1")

    def test_session_limit_rejects_before_launching_browser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        launched = []

        def counting_driver(*_a, **_kw):
            launched.append(1)
            return DummyDriver()

        monkeypatch.setattr(sessions.utils, "get_webdriver", counting_driver)
        monkeypatch.setattr(sessions.utils, "get_config_session_max_count", lambda: 1)
        monkeypatch.setattr(sessions.utils, "_cleanup_orphaned_temp_dirs", lambda: None)
        monkeypatch.setattr(sessions, "_ensure_process_dead", lambda _pid: None)
        monkeypatch.setattr(utils.os, "waitpid", lambda *_a: (_ for _ in ()).throw(ChildProcessError()))

        storage = sessions.SessionsStorage()
        storage.create("s1")
        with pytest.raises(sessions.SessionLimitExceededError):
            storage.create("s2")
        assert launched == [1], "limit must reject before a second browser launches"
        assert storage.session_ids() == ["s1"]

    def test_recreate_returns_existing_without_new_browser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        launched = []

        def counting_driver(*_a, **_kw):
            launched.append(1)
            return DummyDriver()

        monkeypatch.setattr(sessions.utils, "get_webdriver", counting_driver)
        monkeypatch.setattr(sessions.utils, "_cleanup_orphaned_temp_dirs", lambda: None)
        monkeypatch.setattr(sessions, "_ensure_process_dead", lambda _pid: None)
        monkeypatch.setattr(utils.os, "waitpid", lambda *_a: (_ for _ in ()).throw(ChildProcessError()))

        storage = sessions.SessionsStorage()
        s1, fresh1 = storage.create("dup")
        s2, fresh2 = storage.create("dup")
        assert fresh1 is True and fresh2 is False
        assert s1 is s2
        assert launched == [1]


class TestDestroyFaults:
    def test_missing_session_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        storage, _ = _storage(monkeypatch)
        assert storage.destroy("ghost") is False

    def test_quit_failure_still_removes_session_and_cleans_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """driver.quit() raising must not leave the session registered nor skip reaping."""
        driver = DummyDriver()
        driver.quit_exc = RuntimeError("driver wedged")
        driver.browser_pid = 424242

        cleaned: list[str] = []
        reaped: list[Any] = []
        monkeypatch.setattr(sessions.utils, "get_webdriver", lambda *_a, **_kw: driver)
        monkeypatch.setattr(sessions.utils, "_cleanup_orphaned_temp_dirs", lambda: cleaned.append("x"))
        monkeypatch.setattr(sessions, "_ensure_process_dead", lambda pid: reaped.append(pid))
        monkeypatch.setattr(utils.os, "waitpid", lambda *_a: (_ for _ in ()).throw(ChildProcessError()))

        storage = sessions.SessionsStorage()
        storage.create("s1")

        with pytest.raises(RuntimeError, match="driver wedged"):
            storage.destroy("s1")

        assert not storage.exists("s1"), "session must be removed from storage even when quit fails"
        assert reaped == [424242], "process reaper must run even when quit fails"
        assert cleaned == ["x"], "temp-dir cleanup must run even when quit fails"

    def test_successful_destroy_runs_full_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        driver = DummyDriver()
        cleaned: list[str] = []
        reaped: list[Any] = []
        monkeypatch.setattr(sessions.utils, "get_webdriver", lambda *_a, **_kw: driver)
        monkeypatch.setattr(sessions.utils, "_cleanup_orphaned_temp_dirs", lambda: cleaned.append("x"))
        monkeypatch.setattr(sessions, "_ensure_process_dead", lambda pid: reaped.append(pid))
        monkeypatch.setattr(utils.os, "waitpid", lambda *_a: (_ for _ in ()).throw(ChildProcessError()))

        storage = sessions.SessionsStorage()
        storage.create("s1")
        assert storage.destroy("s1") is True
        assert driver.quitted == 1
        assert not storage.exists("s1")


class TestGetFaults:
    def test_ttl_expired_session_recreated_with_fresh_driver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        drivers = [DummyDriver(), DummyDriver()]
        calls: list[Any] = []

        def next_driver(*_a, **_kw):
            calls.append(1)
            return drivers[len(calls) - 1]

        destroyed: list[str] = []
        monkeypatch.setattr(sessions.utils, "get_webdriver", next_driver)
        monkeypatch.setattr(sessions.utils, "_cleanup_orphaned_temp_dirs", lambda: None)
        monkeypatch.setattr(sessions, "_ensure_process_dead", lambda _pid: None)
        monkeypatch.setattr(utils.os, "waitpid", lambda *_a: (_ for _ in ()).throw(ChildProcessError()))

        storage = sessions.SessionsStorage()
        orig_destroy = storage.destroy
        monkeypatch.setattr(storage, "destroy", lambda sid: destroyed.append(sid) or orig_destroy(sid))

        s1, _ = storage.get("s1", ttl=timedelta(seconds=60))
        assert calls == [1]
        # Force expiry, then get with a ttl -> must destroy + recreate
        s1.created_at = s1.created_at - timedelta(hours=2)
        s2, _fresh = storage.get("s1", ttl=timedelta(seconds=60))
        assert calls == [1, 1]
        assert destroyed == ["s1"], "expired session must be destroyed before recreation"
        assert s2.driver is drivers[1]


class TestNegativePaths:
    def test_session_limit_message_is_actionable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sessions.utils, "get_webdriver", lambda *_a, **_kw: DummyDriver())
        monkeypatch.setattr(sessions.utils, "get_config_session_max_count", lambda: 0)
        monkeypatch.setattr(sessions.utils, "_cleanup_orphaned_temp_dirs", lambda: None)
        monkeypatch.setattr(sessions, "_ensure_process_dead", lambda _pid: None)
        monkeypatch.setattr(utils.os, "waitpid", lambda *_a: (_ for _ in ()).throw(ChildProcessError()))

        storage = sessions.SessionsStorage()
        with pytest.raises(sessions.SessionLimitExceededError, match="Destroy an existing session"):
            storage.create("s1")

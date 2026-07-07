from unittest.mock import MagicMock

from flaresolverr import agent_check
from flaresolverr import flaresolverr_service


def test_compute_state_up_100_when_no_session_limit(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: None)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {})
    assert agent_check._compute_state() == "up 100%"


def test_compute_state_up_100_when_no_sessions_used(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 8)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {})
    assert agent_check._compute_state() == "up 100%"


def test_compute_state_up_weight_at_half_capacity(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 8)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {"a": 1, "b": 2, "c": 3, "d": 4})
    assert agent_check._compute_state() == "up 50%"


def test_compute_state_up_1_when_one_free_slot(monkeypatch) -> None:
    # 1 free slot out of 200: int(1/200*100) = 0, clamped to 1% by max(1, ...)
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 200)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {f"s{i}": i for i in range(199)})
    assert agent_check._compute_state() == "up 1%"


def test_compute_state_drain_at_session_limit(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 2)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {"a": 1, "b": 2})
    assert agent_check._compute_state() == "drain"


def test_compute_state_drain_above_session_limit(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 2)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {"a": 1, "b": 2, "c": 3})
    assert agent_check._compute_state() == "drain"


def test_compute_state_drain_when_max_count_zero(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 0)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {})
    assert agent_check._compute_state() == "drain"

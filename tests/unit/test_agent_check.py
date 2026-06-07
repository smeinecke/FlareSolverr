from unittest.mock import MagicMock

from flaresolverr import agent_check
from flaresolverr import flaresolverr_service


def test_compute_state_ready_when_no_session_limit(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: None)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {})
    assert agent_check._compute_state() == "ready"


def test_compute_state_ready_when_below_session_limit(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 8)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {"a": 1, "b": 2})
    assert agent_check._compute_state() == "ready"


def test_compute_state_drain_at_session_limit(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 2)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {"a": 1, "b": 2})
    assert agent_check._compute_state() == "drain"


def test_compute_state_drain_above_session_limit(monkeypatch) -> None:
    monkeypatch.setattr(agent_check.utils, "get_config_session_max_count", lambda: 2)
    monkeypatch.setattr(flaresolverr_service.SESSIONS_STORAGE, "sessions", {"a": 1, "b": 2, "c": 3})
    assert agent_check._compute_state() == "drain"

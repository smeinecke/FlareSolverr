from flaresolverr import agent_check
from flaresolverr import flaresolverr_service


def test_compute_state_ready_when_no_max_parallel(monkeypatch) -> None:
    monkeypatch.setattr(flaresolverr_service, "_MAX_PARALLEL_REQUESTS", None)
    monkeypatch.setattr(flaresolverr_service, "_active_requests", [])
    assert agent_check._compute_state() == "ready"


def test_compute_state_ready_when_below_75_percent(monkeypatch) -> None:
    monkeypatch.setattr(flaresolverr_service, "_MAX_PARALLEL_REQUESTS", 8)
    monkeypatch.setattr(flaresolverr_service, "_active_requests", [{"cmd": "request.get"}] * 5)
    assert agent_check._compute_state() == "ready"


def test_compute_state_50_percent_at_75_percent(monkeypatch) -> None:
    monkeypatch.setattr(flaresolverr_service, "_MAX_PARALLEL_REQUESTS", 8)
    monkeypatch.setattr(flaresolverr_service, "_active_requests", [{"cmd": "request.get"}] * 6)
    assert agent_check._compute_state() == "50%"


def test_compute_state_drain_at_max_parallel(monkeypatch) -> None:
    monkeypatch.setattr(flaresolverr_service, "_MAX_PARALLEL_REQUESTS", 8)
    monkeypatch.setattr(flaresolverr_service, "_active_requests", [{"cmd": "request.get"}] * 8)
    assert agent_check._compute_state() == "drain"


def test_compute_state_drain_above_max_parallel(monkeypatch) -> None:
    monkeypatch.setattr(flaresolverr_service, "_MAX_PARALLEL_REQUESTS", 8)
    monkeypatch.setattr(flaresolverr_service, "_active_requests", [{"cmd": "request.get"}] * 10)
    assert agent_check._compute_state() == "drain"


def test_compute_state_boundary_exactly_75_percent(monkeypatch) -> None:
    monkeypatch.setattr(flaresolverr_service, "_MAX_PARALLEL_REQUESTS", 4)
    monkeypatch.setattr(flaresolverr_service, "_active_requests", [{"cmd": "request.get"}] * 3)
    assert agent_check._compute_state() == "50%"

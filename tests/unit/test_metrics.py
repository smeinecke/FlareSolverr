from flaresolverr import metrics


def test_serve_starts_http_server_and_sleeps(monkeypatch) -> None:
    called = {"port": None, "sleep": 0}

    def fake_start_http_server(*, port):
        called["port"] = port

    def fake_sleep(_seconds):
        called["sleep"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(metrics, "start_http_server", fake_start_http_server)
    monkeypatch.setattr(metrics.time, "sleep", fake_sleep)

    try:
        metrics.serve(9999)
    except KeyboardInterrupt:
        pass

    assert called["port"] == 9999
    assert called["sleep"] == 1


def test_start_metrics_http_server_starts_daemon_thread(monkeypatch) -> None:
    captured = {"target": None, "kwargs": None, "daemon": None, "started": False, "log": None}

    class DummyThread:
        def __init__(self, target, kwargs, daemon):
            captured["target"] = target
            captured["kwargs"] = kwargs
            captured["daemon"] = daemon

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(metrics.logging, "info", lambda message: captured.__setitem__("log", message))
    monkeypatch.setattr("threading.Thread", DummyThread)

    metrics.start_metrics_http_server(8192)

    assert captured["target"] is metrics.serve
    assert captured["kwargs"] == {"port": 8192}
    assert captured["daemon"] is True
    assert captured["started"] is True
    assert "8192" in captured["log"]

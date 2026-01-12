from types import SimpleNamespace

from bottle_plugins import error_plugin, logger_plugin, prometheus_plugin


def test_error_plugin_returns_callback_response(monkeypatch) -> None:
    monkeypatch.setattr(error_plugin, "response", SimpleNamespace(status=200))

    wrapped = error_plugin.error_plugin(lambda: {"ok": True})

    assert wrapped() == {"ok": True}


def test_error_plugin_handles_exceptions(monkeypatch) -> None:
    state = {"logged": None}
    monkeypatch.setattr(error_plugin, "response", SimpleNamespace(status=200))
    monkeypatch.setattr(error_plugin.logging, "error", lambda msg: state.__setitem__("logged", msg))

    def raise_error():
        raise RuntimeError("boom")

    wrapped = error_plugin.error_plugin(raise_error)
    result = wrapped()

    assert result == {"error": "boom"}
    assert error_plugin.response.status == 500
    assert state["logged"] == "boom"


def test_logger_plugin_logs_non_health_requests(monkeypatch) -> None:
    logs = []
    monkeypatch.setattr(logger_plugin, "request", SimpleNamespace(url="http://localhost/v1", remote_addr="127.0.0.1", method="POST"))
    monkeypatch.setattr(logger_plugin, "response", SimpleNamespace(status="200 OK"))
    monkeypatch.setattr(logger_plugin.logging, "info", lambda msg: logs.append(msg))

    wrapped = logger_plugin.logger_plugin(lambda: {"ok": True})
    result = wrapped()

    assert result == {"ok": True}
    assert len(logs) == 1
    assert "POST" in logs[0]


def test_logger_plugin_skips_health_logs(monkeypatch) -> None:
    logs = []
    monkeypatch.setattr(logger_plugin, "request", SimpleNamespace(url="http://localhost/health", remote_addr="127.0.0.1", method="GET"))
    monkeypatch.setattr(logger_plugin, "response", SimpleNamespace(status="200 OK"))
    monkeypatch.setattr(logger_plugin.logging, "info", lambda msg: logs.append(msg))

    wrapped = logger_plugin.logger_plugin(lambda: {"ok": True})
    wrapped()

    assert logs == []


def test_prometheus_setup_starts_server_when_enabled(monkeypatch) -> None:
    started = {"port": None}
    monkeypatch.setattr(prometheus_plugin, "PROMETHEUS_ENABLED", True)
    monkeypatch.setattr(prometheus_plugin, "PROMETHEUS_PORT", 9000)
    monkeypatch.setattr(prometheus_plugin, "start_metrics_http_server", lambda port: started.__setitem__("port", port))

    prometheus_plugin.setup()

    assert started["port"] == 9000


def test_prometheus_setup_noop_when_disabled(monkeypatch) -> None:
    started = {"called": False}
    monkeypatch.setattr(prometheus_plugin, "PROMETHEUS_ENABLED", False)
    monkeypatch.setattr(prometheus_plugin, "start_metrics_http_server", lambda _port: started.__setitem__("called", True))

    prometheus_plugin.setup()

    assert started["called"] is False


def test_prometheus_plugin_exports_solution_domain_and_result(monkeypatch) -> None:
    durations = []
    counters = []

    class DurationMetric:
        def labels(self, **kwargs):
            class Observer:
                def observe(self, value):
                    durations.append((kwargs, value))

            return Observer()

    class CounterMetric:
        def labels(self, **kwargs):
            class Incrementer:
                def inc(self):
                    counters.append(kwargs)

            return Incrementer()

    monkeypatch.setattr(prometheus_plugin, "PROMETHEUS_ENABLED", True)
    monkeypatch.setattr(prometheus_plugin, "REQUEST_DURATION", DurationMetric())
    monkeypatch.setattr(prometheus_plugin, "REQUEST_COUNTER", CounterMetric())

    def callback():
        return {
            "startTimestamp": 1000,
            "endTimestamp": 4000,
            "message": "Challenge solved!",
            "solution": {"url": "https://example.com/path"},
        }

    wrapped = prometheus_plugin.prometheus_plugin(callback)
    wrapped()

    assert durations == [({"domain": "example.com"}, 3.0)]
    assert counters == [{"domain": "example.com", "result": "solved"}]


def test_prometheus_plugin_uses_request_url_when_solution_missing(monkeypatch) -> None:
    durations = []
    counters = []

    class DurationMetric:
        def labels(self, **kwargs):
            class Observer:
                def observe(self, value):
                    durations.append(kwargs)

            return Observer()

    class CounterMetric:
        def labels(self, **kwargs):
            class Incrementer:
                def inc(self):
                    counters.append(kwargs)

            return Incrementer()

    monkeypatch.setattr(prometheus_plugin, "PROMETHEUS_ENABLED", True)
    monkeypatch.setattr(prometheus_plugin, "REQUEST_DURATION", DurationMetric())
    monkeypatch.setattr(prometheus_plugin, "REQUEST_COUNTER", CounterMetric())
    monkeypatch.setattr(prometheus_plugin, "request", SimpleNamespace(json={"url": "https://fallback.test/page"}))

    def callback():
        return {
            "startTimestamp": 0,
            "endTimestamp": 100,
            "message": "Error: timeout",
            "solution": None,
        }

    wrapped = prometheus_plugin.prometheus_plugin(callback)
    wrapped()

    assert durations == [{"domain": "fallback.test"}]
    assert counters == [{"domain": "fallback.test", "result": "error"}]


def test_prometheus_plugin_skips_non_timed_responses(monkeypatch) -> None:
    called = {"duration": 0, "counter": 0}

    class DurationMetric:
        def labels(self, **kwargs):
            called["duration"] += 1
            return SimpleNamespace(observe=lambda _v: None)

    class CounterMetric:
        def labels(self, **kwargs):
            called["counter"] += 1
            return SimpleNamespace(inc=lambda: None)

    monkeypatch.setattr(prometheus_plugin, "PROMETHEUS_ENABLED", True)
    monkeypatch.setattr(prometheus_plugin, "REQUEST_DURATION", DurationMetric())
    monkeypatch.setattr(prometheus_plugin, "REQUEST_COUNTER", CounterMetric())

    wrapped = prometheus_plugin.prometheus_plugin(lambda: {"message": "ok"})
    wrapped()

    assert called == {"duration": 0, "counter": 0}


def test_prometheus_plugin_logs_warning_when_export_fails(monkeypatch) -> None:
    warnings = []
    monkeypatch.setattr(prometheus_plugin, "PROMETHEUS_ENABLED", True)
    monkeypatch.setattr(prometheus_plugin.logging, "warning", lambda msg: warnings.append(msg))

    wrapped = prometheus_plugin.prometheus_plugin(lambda: "not-a-dict")
    wrapped()

    assert len(warnings) == 1
    assert "Error exporting metrics" in warnings[0]

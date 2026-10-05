import json
import os
import tempfile
import time
from unittest.mock import MagicMock

import pytest

from flaresolverr import utils


def test_sanitize_user_agent_removes_headless_token():
    ua = "Mozilla/5.0 (...) HeadlessChrome/147.0.0.0 Safari/537.36"
    assert "HeadlessChrome/" not in utils.sanitize_user_agent(ua)
    assert "Chrome/147.0.0.0" in utils.sanitize_user_agent(ua)


def test_sanitize_user_agent_keeps_regular_user_agent():
    ua = "Mozilla/5.0 (...) Chrome/147.0.0.0 Safari/537.36"
    assert utils.sanitize_user_agent(ua) == ua


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/html", False),
        ("text/plain", False),
        ("application/json", False),
        ("application/javascript", False),
        ("application/xml", False),
        ("application/xhtml+xml", False),
        ("application/ld+json", False),
        ("image/jpeg", True),
        ("image/png", True),
        ("application/pdf", True),
        ("application/octet-stream", True),
        ("audio/mpeg", True),
        ("video/mp4", True),
        ("", True),
        (None, True),
    ],
)
def test_is_binary_content_type(content_type, expected):
    assert utils.is_binary_content_type(content_type) is expected


def _make_ack_driver(ext_id: str = "abc123") -> MagicMock:
    """Return a MagicMock driver that simulates extension-page ACK polling."""
    driver = MagicMock()
    driver.current_url = "about:blank"
    driver._proxy_ext_id = ext_id

    def fake_get(url: str) -> None:
        driver.current_url = url

    driver.get = MagicMock(side_effect=fake_get)

    def fake_execute(script: str):
        if "chrome.runtime.id" in script:
            return ext_id
        if "chrome.runtime.sendMessage" in script:
            return None
        # polling for result
        return {"success": True}

    driver.execute_script = MagicMock(side_effect=fake_execute)
    return driver


def test_apply_proxy_to_session_navigates_to_extension_page(monkeypatch) -> None:
    """It should navigate to the extension's proxy.html page."""
    driver = _make_ack_driver("abc123")
    monkeypatch.setattr(utils, "_check_proxy_reachable", lambda url: None)

    utils.apply_proxy_to_session(driver, {"url": "http://proxy:8080"})

    driver.get.assert_called_once_with("chrome-extension://abc123/proxy.html")


def test_apply_proxy_to_session_uses_chrome_runtime_sendmessage(monkeypatch) -> None:
    """apply_proxy_to_session should use chrome.runtime.sendMessage from the extension page."""
    driver = _make_ack_driver("abc123")
    monkeypatch.setattr(utils, "_check_proxy_reachable", lambda url: None)

    utils.apply_proxy_to_session(driver, {"url": "http://proxy:8080"})

    injected = [c[0][0] for c in driver.execute_script.call_args_list if "chrome.runtime.sendMessage" in c[0][0]]
    assert len(injected) == 1
    assert '"mode": "fixed_servers"' in injected[0]


def test_apply_proxy_to_session_sends_direct_for_empty_proxy(monkeypatch) -> None:
    """Passing an empty proxy should send mode=direct to the extension."""
    driver = _make_ack_driver("abc123")

    utils.apply_proxy_to_session(driver, {"url": ""})

    injected = [c[0][0] for c in driver.execute_script.call_args_list if "chrome.runtime.sendMessage" in c[0][0]]
    assert len(injected) == 1
    assert '"mode": "direct"' in injected[0]


def test_apply_proxy_to_session_sends_auth_when_present(monkeypatch) -> None:
    """Authenticated proxies should include auth credentials in the payload."""
    driver = _make_ack_driver("abc123")
    monkeypatch.setattr(utils, "_check_proxy_reachable", lambda url: None)

    utils.apply_proxy_to_session(driver, {"url": "http://proxy:8080", "username": "user", "password": "pass"})

    injected = [c[0][0] for c in driver.execute_script.call_args_list if "chrome.runtime.sendMessage" in c[0][0]]
    assert len(injected) == 1
    script = injected[0]
    assert '"username": "user"' in script
    assert '"password": "pass"' in script
    assert '"mode": "fixed_servers"' in script


def test_apply_proxy_to_session_extracts_auth_from_url(monkeypatch) -> None:
    """Credentials embedded in the proxy URL should populate the auth payload."""
    driver = _make_ack_driver("abc123")
    monkeypatch.setattr(utils, "_check_proxy_reachable", lambda url: None)

    utils.apply_proxy_to_session(driver, {"url": "http://user:pass@proxy:8080"})

    injected = [c[0][0] for c in driver.execute_script.call_args_list if "chrome.runtime.sendMessage" in c[0][0]]
    assert len(injected) == 1
    assert '"username": "user"' in injected[0]
    assert '"password": "pass"' in injected[0]


def test_apply_proxy_to_session_url_auth_percent_decoded(monkeypatch) -> None:
    """Percent-encoded credentials in the URL must be decoded before use."""
    driver = _make_ack_driver("abc123")
    monkeypatch.setattr(utils, "_check_proxy_reachable", lambda url: None)

    utils.apply_proxy_to_session(driver, {"url": "http://us%40er:p%40ss%3A1@proxy:8080"})

    injected = [c[0][0] for c in driver.execute_script.call_args_list if "chrome.runtime.sendMessage" in c[0][0]]
    assert len(injected) == 1
    assert '"username": "us@er"' in injected[0]
    assert '"password": "p@ss:1"' in injected[0]


def test_apply_proxy_to_session_explicit_fields_win_over_url(monkeypatch) -> None:
    """Explicit username/password fields take precedence over URL userinfo."""
    driver = _make_ack_driver("abc123")
    monkeypatch.setattr(utils, "_check_proxy_reachable", lambda url: None)

    utils.apply_proxy_to_session(driver, {"url": "http://urluser:urlpass@proxy:8080", "username": "explicit", "password": "explicitpass"})

    injected = [c[0][0] for c in driver.execute_script.call_args_list if "chrome.runtime.sendMessage" in c[0][0]]
    assert len(injected) == 1
    assert '"username": "explicit"' in injected[0]
    assert '"password": "explicitpass"' in injected[0]


def test_apply_proxy_to_session_url_without_password(monkeypatch) -> None:
    """URL userinfo with only a username sends an empty password."""
    driver = _make_ack_driver("abc123")
    monkeypatch.setattr(utils, "_check_proxy_reachable", lambda url: None)

    utils.apply_proxy_to_session(driver, {"url": "socks5://user@proxy:1080"})

    injected = [c[0][0] for c in driver.execute_script.call_args_list if "chrome.runtime.sendMessage" in c[0][0]]
    assert len(injected) == 1
    assert '"username": "user"' in injected[0]
    assert '"password": ""' in injected[0]


def test_invalid_proxy_error_redacts_url_credentials() -> None:
    """Error messages must not leak credentials embedded in the proxy URL."""
    driver = _make_ack_driver("abc123")
    with pytest.raises(RuntimeError, match="cannot parse host/port") as exc_info:
        utils.apply_proxy_to_session(driver, {"url": "http://user:secretpass@"})
    assert "secretpass" not in str(exc_info.value)


def test_apply_proxy_to_session_raises_on_invalid_proxy() -> None:
    """An invalid proxy (missing schema) must raise RuntimeError."""
    driver = _make_ack_driver("abc123")
    with pytest.raises(RuntimeError, match="schema required"):
        utils.apply_proxy_to_session(driver, {"url": "proxy:8080"})


def test_apply_proxy_to_session_raises_on_extension_failure(monkeypatch) -> None:
    """If the extension reports failure, we must raise."""
    driver = MagicMock()
    driver.current_url = "about:blank"
    driver._proxy_ext_id = "abc123"

    def fake_get(url: str) -> None:
        driver.current_url = url

    driver.get = MagicMock(side_effect=fake_get)

    def fake_execute(script: str):
        if "chrome.runtime.id" in script:
            return "abc123"
        if "chrome.runtime.sendMessage" in script:
            return None
        return {"success": False, "error": "bg error"}

    driver.execute_script = fake_execute
    monkeypatch.setattr(utils, "_check_proxy_reachable", lambda url: None)

    with pytest.raises(RuntimeError, match="bg error"):
        utils.apply_proxy_to_session(driver, {"url": "http://proxy:8080"})


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ("", None),
        ("0", None),
        ("-1", None),
        ("abc", None),
        ("8080", 8080),
        ("12345", 12345),
    ],
)
def test_get_config_agent_check_port(monkeypatch, env, expected):
    monkeypatch.setenv("AGENT_CHECK_PORT", env)
    assert utils.get_config_agent_check_port() == expected


def test_get_config_agent_check_port_unset(monkeypatch):
    monkeypatch.delenv("AGENT_CHECK_PORT", raising=False)
    assert utils.get_config_agent_check_port() is None


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ("", "127.0.0.1"),
        ("0.0.0.0", "0.0.0.0"),
        ("10.0.0.1", "10.0.0.1"),
    ],
)
def test_get_config_agent_check_host(monkeypatch, env, expected):
    monkeypatch.setenv("AGENT_CHECK_HOST", env)
    assert utils.get_config_agent_check_host() == expected


def test_get_config_agent_check_host_unset(monkeypatch):
    monkeypatch.delenv("AGENT_CHECK_HOST", raising=False)
    assert utils.get_config_agent_check_host() == "127.0.0.1"


def test_cleanup_orphaned_temp_dirs_removes_old_dirs(monkeypatch) -> None:
    """Old temp dirs matching known prefixes should be removed."""
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(utils.tempfile, "gettempdir", lambda: tmpdir)
    monkeypatch.setattr(utils, "_LAST_CLEANUP_TIME", 0.0)

    old_dir = os.path.join(tmpdir, "uc-chrome-old")
    os.makedirs(old_dir)
    # Set mtime to 10 minutes ago (past the 5-minute cutoff)
    os.utime(old_dir, (time.time() - 600, time.time() - 600))

    utils._cleanup_orphaned_temp_dirs()
    assert not os.path.exists(old_dir)


def test_cleanup_orphaned_temp_dirs_skips_recent_dirs(monkeypatch) -> None:
    """Recent temp dirs should not be removed to avoid deleting active sessions."""
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(utils.tempfile, "gettempdir", lambda: tmpdir)
    monkeypatch.setattr(utils, "_LAST_CLEANUP_TIME", 0.0)

    recent_dir = os.path.join(tmpdir, "flaresolverr-chrome-active")
    os.makedirs(recent_dir)

    utils._cleanup_orphaned_temp_dirs()
    assert os.path.exists(recent_dir)


def test_cleanup_orphaned_temp_dirs_skips_locked_dirs(monkeypatch) -> None:
    """Dirs with a SingletonLock should not be removed even if old."""
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(utils.tempfile, "gettempdir", lambda: tmpdir)
    monkeypatch.setattr(utils, "_LAST_CLEANUP_TIME", 0.0)

    locked_dir = os.path.join(tmpdir, "uc-chrome-locked")
    os.makedirs(locked_dir)
    open(os.path.join(locked_dir, "SingletonLock"), "w").close()
    os.utime(locked_dir, (time.time() - 600, time.time() - 600))

    utils._cleanup_orphaned_temp_dirs()
    assert os.path.exists(locked_dir)


def test_cleanup_orphaned_temp_dirs_runs_repeatedly(monkeypatch) -> None:
    """The cleanup function can be called multiple times and still cleans up."""
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(utils.tempfile, "gettempdir", lambda: tmpdir)
    monkeypatch.setattr(utils, "_LAST_CLEANUP_TIME", 0.0)

    old_dir = os.path.join(tmpdir, "fspe-old")
    os.makedirs(old_dir)
    os.utime(old_dir, (time.time() - 600, time.time() - 600))

    utils._cleanup_orphaned_temp_dirs()
    assert not os.path.exists(old_dir)

    # Simulate 2 minutes passing so the rate limit allows another run
    monkeypatch.setattr(utils, "_LAST_CLEANUP_TIME", time.time() - 120)

    # Second call should still clean up a newly leaked dir
    new_old_dir = os.path.join(tmpdir, "fspe-older")
    os.makedirs(new_old_dir)
    os.utime(new_old_dir, (time.time() - 600, time.time() - 600))
    utils._cleanup_orphaned_temp_dirs()
    assert not os.path.exists(new_old_dir)


def test_cleanup_orphaned_temp_dirs_rate_limited(monkeypatch) -> None:
    """Cleanup should be skipped if called again within 60 seconds."""
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(utils.tempfile, "gettempdir", lambda: tmpdir)
    monkeypatch.setattr(utils, "_LAST_CLEANUP_TIME", 0.0)

    old_dir = os.path.join(tmpdir, "fspe-old")
    os.makedirs(old_dir)
    os.utime(old_dir, (time.time() - 600, time.time() - 600))

    utils._cleanup_orphaned_temp_dirs()
    assert not os.path.exists(old_dir)

    # Create another old dir but call again immediately (within 60s)
    new_old_dir = os.path.join(tmpdir, "fspe-older")
    os.makedirs(new_old_dir)
    os.utime(new_old_dir, (time.time() - 600, time.time() - 600))
    utils._cleanup_orphaned_temp_dirs()
    assert os.path.exists(new_old_dir)


def test_get_webdriver_cleans_proxy_ext_dir_on_failure(monkeypatch) -> None:
    """If Chrome fails to start, the proxy extension temp dir must be removed."""
    tmpdir = tempfile.mkdtemp()
    ext_dir = os.path.join(tmpdir, "fspe-failtest")
    os.makedirs(ext_dir)
    monkeypatch.setattr(utils, "_build_stealth_extension_dir", lambda: (ext_dir, "extid"))
    monkeypatch.setattr(utils, "get_chrome_exe_path", lambda: "/fake/chrome")
    monkeypatch.setattr(utils, "_is_custom_chromium", lambda: True)
    monkeypatch.setattr(utils, "_configure_headless", lambda: False)
    monkeypatch.setattr(utils, "_find_free_port", lambda: 9999)
    monkeypatch.setattr(utils, "_resolve_driver_paths", lambda: (None, None))
    import subprocess

    def failing_popen(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(subprocess, "Popen", failing_popen)

    # A proxy is required for the proxy-manager extension to be loaded.
    with pytest.raises(OSError, match="No space left on device"):
        utils.get_webdriver(proxy={"url": "http://127.0.0.1:9"})
    assert not os.path.exists(ext_dir)


def _make_performance_log_entry(method: str, params: dict) -> dict:
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


def test_parse_performance_log_entries_extracts_method_and_params() -> None:
    logs = [
        _make_performance_log_entry("Network.requestWillBeSent", {"requestId": "1"}),
        _make_performance_log_entry("Network.responseReceived", {"requestId": "1"}),
    ]

    parsed = utils.parse_performance_log_entries(logs)

    assert len(parsed) == 2
    assert parsed[0]["method"] == "Network.requestWillBeSent"
    assert parsed[0]["params"]["requestId"] == "1"
    assert parsed[1]["method"] == "Network.responseReceived"


def test_parse_performance_log_entries_skips_malformed_entries() -> None:
    logs = [
        _make_performance_log_entry("Network.requestWillBeSent", {"requestId": "1"}),
        {"message": "not valid json"},
        {"message": json.dumps({"foo": "bar"})},
        {"foo": "bar"},
    ]

    parsed = utils.parse_performance_log_entries(logs)

    assert len(parsed) == 1
    assert parsed[0]["params"]["requestId"] == "1"


def test_get_performance_log_returns_empty_list_when_log_type_not_found() -> None:
    driver = MagicMock()
    driver.get_log.side_effect = Exception("log type 'performance' not found")

    assert utils.get_performance_log(driver) == []


def test_get_performance_log_re_raises_other_errors() -> None:
    driver = MagicMock()
    driver.get_log.side_effect = Exception("some other error")

    with pytest.raises(Exception, match="Error getting network logs"):
        utils.get_performance_log(driver)


def test_performance_logs_to_har_converts_request_response_and_finished() -> None:
    parsed = [
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "req1",
                "timestamp": 1000.0,
                "wallTime": 1700000000.0,
                "request": {
                    "method": "GET",
                    "url": "https://example.com/",
                    "headers": {"Accept": "text/html"},
                },
            },
        },
        {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "req1",
                "timestamp": 1001.0,
                "response": {
                    "status": 200,
                    "statusText": "OK",
                    "protocol": "h2",
                    "headers": {"Content-Type": "text/html"},
                    "mimeType": "text/html",
                },
            },
        },
        {
            "method": "Network.loadingFinished",
            "params": {
                "requestId": "req1",
                "timestamp": 1002.0,
            },
        },
    ]

    har = utils.performance_logs_to_har(parsed)

    assert har["log"]["version"] == "1.2"
    assert har["log"]["creator"]["name"] == "FlareSolverr"
    assert len(har["log"]["entries"]) == 1
    entry = har["log"]["entries"][0]
    assert entry["request"]["method"] == "GET"
    assert entry["request"]["url"] == "https://example.com/"
    assert entry["response"]["status"] == 200
    assert entry["response"]["content"]["mimeType"] == "text/html"
    assert entry["time"] == 2000.0


def test_performance_logs_to_har_includes_failed_requests_with_status_zero() -> None:
    parsed = [
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "req2",
                "timestamp": 2000.0,
                "wallTime": 1700000001.0,
                "request": {"method": "GET", "url": "https://blocked.example.com/", "headers": {}},
            },
        },
        {
            "method": "Network.loadingFailed",
            "params": {
                "requestId": "req2",
                "timestamp": 2001.0,
                "errorText": "net::ERR_BLOCKED_BY_CLIENT",
            },
        },
    ]

    har = utils.performance_logs_to_har(parsed)

    assert len(har["log"]["entries"]) == 1
    entry = har["log"]["entries"][0]
    assert entry["response"]["status"] == 0
    assert entry["response"]["statusText"] == "net::ERR_BLOCKED_BY_CLIENT"


def test_performance_logs_to_har_includes_requests_without_response() -> None:
    parsed = [
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "req3",
                "timestamp": 3000.0,
                "wallTime": 1700000002.0,
                "request": {"method": "GET", "url": "https://pending.example.com/", "headers": {}},
            },
        },
    ]

    har = utils.performance_logs_to_har(parsed)

    assert len(har["log"]["entries"]) == 1
    entry = har["log"]["entries"][0]
    assert entry["request"]["url"] == "https://pending.example.com/"
    assert entry["response"]["status"] == 0


def test_performance_logs_to_har_filters_internal_chrome_urls() -> None:
    parsed = [
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "ntp1",
                "timestamp": 1000.0,
                "wallTime": 1700000000.0,
                "request": {"method": "GET", "url": "chrome://new-tab-page/background.js", "headers": {}},
            },
        },
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "ext1",
                "timestamp": 1001.0,
                "wallTime": 1700000001.0,
                "request": {"method": "GET", "url": "chrome-extension://fake-id/script.js", "headers": {}},
            },
        },
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "real1",
                "timestamp": 1002.0,
                "wallTime": 1700000002.0,
                "request": {"method": "GET", "url": "https://example.com/", "headers": {}},
            },
        },
        {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "real1",
                "timestamp": 1003.0,
                "response": {"status": 200, "statusText": "OK", "headers": {}, "mimeType": "text/html"},
            },
        },
    ]

    har = utils.performance_logs_to_har(parsed)

    assert len(har["log"]["entries"]) == 1
    assert har["log"]["entries"][0]["request"]["url"] == "https://example.com/"


class TestChromeOptionsConsolidation:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        for var in [
            "CHROME_EXTRA_FLAGS",
            "STEALTH_OMIT_FLAGS",
            "CHROME_DISABLE_OPTIMIZATIONS",
            "MINIMAL_FINGERPRINT",
            "DISABLE_QUIC",
            "DISABLE_WEB_SECURITY",
        ]:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(utils, "_CUSTOM_CHROMIUM_MANIFEST", None)
        # Avoid spawning `chrome --version` for the --user-agent fallback path.
        monkeypatch.setattr(utils, "get_chrome_full_version", lambda: "151.0.0.0")
        monkeypatch.setattr(utils, "get_chrome_major_version", lambda: "151")

    def _options(self, monkeypatch, stealth_mode="off", custom=False, patches=None):
        monkeypatch.setattr(utils, "_is_custom_chromium", lambda: custom)
        monkeypatch.setattr(utils, "_get_custom_chromium_manifest", lambda: {"patches": list(patches or [])})
        return utils._build_chrome_options(stealth_mode)

    def test_single_disable_features_argument(self, monkeypatch):
        options = self._options(monkeypatch)
        disable_args = [a for a in options.arguments if a.startswith("--disable-features=")]
        assert len(disable_args) == 1
        features = disable_args[0].removeprefix("--disable-features=").split(",")
        for expected in [
            "MediaRouter",
            "OptimizationHints",
            "Translate",
            "LocalNetworkAccessChecks",
        ]:
            assert expected in features

    def test_disable_features_merges_all_sources(self, monkeypatch):
        monkeypatch.setenv("DISABLE_WEB_SECURITY", "true")
        monkeypatch.setenv("MINIMAL_FINGERPRINT", "false")
        options = self._options(monkeypatch)
        disable_args = [a for a in options.arguments if a.startswith("--disable-features=")]
        assert len(disable_args) == 1
        features = set(disable_args[0].removeprefix("--disable-features=").split(","))
        assert {"BlockInsecurePrivateNetworkRequests", "StrictOriginIsolation"} <= features

    def test_omit_flags_removes_stealth_switch(self, monkeypatch):
        monkeypatch.setenv("STEALTH_OMIT_FLAGS", "stealth-viewport-size")
        options = self._options(monkeypatch, stealth_mode="standard", custom=True, patches=["native-ua"])
        assert "--stealth-viewport-size" not in options.arguments
        assert "--stealth-no-media-devices" in options.arguments

    def test_native_ua_flag_from_manifest(self, monkeypatch):
        options = self._options(monkeypatch, stealth_mode="standard", custom=True, patches=["native-ua"])
        assert "--stealth-native-ua" in options.arguments
        # Native UA makes the --user-agent fallback unnecessary.
        assert not [a for a in options.arguments if a.startswith("--user-agent=")]

    def test_native_ua_flag_absent_without_manifest(self, monkeypatch):
        options = self._options(monkeypatch, stealth_mode="standard", custom=True, patches=[])
        assert "--stealth-native-ua" not in options.arguments
        # Legacy fallback keeps --user-agent for binaries without Patch 6b.
        assert [a for a in options.arguments if a.startswith("--user-agent=")]

    def test_extra_flags_added_once(self, monkeypatch):
        monkeypatch.setenv("CHROME_EXTRA_FLAGS", "--foo=1,--bar")
        options = self._options(monkeypatch)
        assert options.arguments.count("--foo=1") == 1
        assert "--bar" in options.arguments

    def test_webdriver_false_property_variant(self, monkeypatch):
        options = self._options(monkeypatch, stealth_mode="standard", custom=True, patches=["webdriver-false"])
        # False-property variant: property must stay present -> no AutomationControlled removal.
        assert "--disable-blink-features=AutomationControlled" not in options.arguments

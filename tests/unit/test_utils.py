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

    utils.apply_proxy_to_session(
        driver, {"url": "http://proxy:8080", "username": "user", "password": "pass"}
    )

    injected = [c[0][0] for c in driver.execute_script.call_args_list if "chrome.runtime.sendMessage" in c[0][0]]
    assert len(injected) == 1
    script = injected[0]
    assert '"username": "user"' in script
    assert '"password": "pass"' in script
    assert '"mode": "fixed_servers"' in script


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

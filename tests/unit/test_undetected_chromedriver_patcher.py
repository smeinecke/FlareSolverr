import gc
import os
import shutil
from pathlib import Path

import pytest

from flaresolverr.undetected_chromedriver.patcher import Patcher

_STEALTH_MARKER = "/opt/chromium/.stealth-patched"


def _make_fake_chromedriver(bin_dir: Path) -> Path:
    """Write a fake chromedriver executable that reports a version and
    contains a CDC injection block the patcher can replace.
    """
    script = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "ChromeDriver 148.0.7778.215 (abc)"
  exit 0
fi
# AA{window.cdc_123;}
"""
    fake = bin_dir / "chromedriver"
    fake.write_text(script)
    fake.chmod(0o755)
    return fake


def _hide_stealth_marker(monkeypatch):
    """Ensure /opt/chromium/.stealth-patched is seen as absent (dev machines may have it)."""
    _real = os.path.exists
    monkeypatch.setattr("os.path.exists", lambda p: False if p == _STEALTH_MARKER else _real(p))


def _make_patcher(data_path: str, version_main: int = 148, executable_path: str | None = None, platform_name: str | None = None) -> Patcher:
    p = Patcher(version_main=version_main)
    p.data_path = data_path
    p.executable_path = executable_path or os.path.join(data_path, "chromedriver")
    p._custom_exe_path = executable_path is not None
    if platform_name:
        p.platform_name = platform_name
        p.platform = platform_name
    return p


def _setup_patched_binary(patcher: Patcher, fake_chromedriver: Path) -> None:
    """Copy and patch a fake chromedriver into the patcher's executable_path."""
    shutil.copy(fake_chromedriver, patcher.executable_path)
    os.chmod(patcher.executable_path, 0o755)
    patcher.patch_exe()


def test_del_does_not_delete_binary(monkeypatch, tmp_path):
    """Patcher.__del__ must not delete the patched binary on any platform.

    The patched binary is reused between sessions (via version.txt on FreeBSD
    and via PATCHED_DRIVER_PATH on all platforms).  Deleting it in __del__
    causes a race condition where the next Patcher instance finds the file
    missing (issue #82).
    """
    _hide_stealth_marker(monkeypatch)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_path = str(data_dir)

    fake = _make_fake_chromedriver(tmp_path)

    p = _make_patcher(data_path)
    _setup_patched_binary(p, fake)
    exe_path = p.executable_path
    assert os.path.exists(exe_path)
    assert p.is_binary_patched(exe_path)

    # Trigger __del__ — the binary must survive.
    del p
    gc.collect()
    assert os.path.exists(exe_path), "__del__ deleted the patched binary"


def test_auto_recovers_with_custom_exe_path_when_file_missing(monkeypatch, tmp_path):
    """Regression test for issue #82: _custom_exe_path recovery.

    After the startup test, _save_patched_driver sets PATCHED_DRIVER_PATH.
    On the next request, Patcher is created with _custom_exe_path=True.
    If the binary is missing, auto() must fall through to the normal
    copy/download + patch logic instead of calling patch_exe() on a
    non-existent file.
    """
    _hide_stealth_marker(monkeypatch)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = _make_fake_chromedriver(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_path = str(data_dir)
    exe_path = os.path.join(data_path, "chromedriver")

    # Simulate the startup test: patcher with _custom_exe_path=False.
    p1 = _make_patcher(data_path, platform_name="freebsd")
    assert p1.auto() is True
    assert os.path.exists(exe_path)

    # Simulate the binary being deleted (e.g. by a previous __del__ before fix).
    os.unlink(exe_path)

    # Simulate the first request: PATCHED_DRIVER_PATH is set, so the patcher
    # gets _custom_exe_path=True pointing at the same path.
    p2 = _make_patcher(data_path, executable_path=exe_path, platform_name="freebsd")
    assert p2._custom_exe_path is True
    assert p2.auto() is True
    assert os.path.exists(p2.executable_path)
    assert p2.is_binary_patched(p2.executable_path)


def test_freebsd_patcher_recovers_when_patched_binary_deleted(monkeypatch, tmp_path):
    """Regression test for issue #82: FreeBSD version.txt recovery.

    On FreeBSD, auto() must re-copy the system chromedriver when the cached
    binary is missing, even if version.txt is still up-to-date.  Otherwise
    the next session fails with FileNotFoundError.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_fake_chromedriver(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_path = str(data_dir)

    _hide_stealth_marker(monkeypatch)

    p1 = _make_patcher(data_path, platform_name="freebsd")
    assert p1.auto() is True
    exe_path = p1.executable_path
    assert os.path.exists(exe_path)
    assert p1.is_binary_patched(exe_path)

    # Simulate the binary being removed while version.txt remains.
    os.unlink(exe_path)
    assert os.path.exists(os.path.join(data_path, "version.txt"))

    p2 = _make_patcher(data_path, platform_name="freebsd")
    assert p2.auto() is True
    assert os.path.exists(p2.executable_path)
    assert p2.is_binary_patched(p2.executable_path)

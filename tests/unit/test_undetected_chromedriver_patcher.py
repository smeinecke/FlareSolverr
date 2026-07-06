import gc
import os
import posixpath
import tempfile
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
    _real = posixpath.exists
    monkeypatch.setattr("os.path.exists", lambda p: False if p == _STEALTH_MARKER else _real(p))


def _make_freebsd_patcher(data_path: str, version_main: int = 148, executable_path: str | None = None) -> Patcher:
    p = Patcher(version_main=version_main)
    # Force the FreeBSD code path against an isolated data directory.
    p.platform = "freebsd15"
    p.platform_name = "freebsd"
    p.data_path = data_path
    p.executable_path = executable_path or os.path.join(data_path, "chromedriver")
    p._custom_exe_path = executable_path is not None
    return p


def test_freebsd_patcher_recovers_when_patched_binary_deleted(monkeypatch, tmp_path):
    """Regression test for issue #82.

    Patcher.__del__ now deletes the patched chromedriver binary.  On FreeBSD,
    auto() must re-copy the system chromedriver when the cached binary is
    missing, even if version.txt is still up-to-date.  Otherwise the next
    session fails with FileNotFoundError.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_fake_chromedriver(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_path = str(data_dir)

    _hide_stealth_marker(monkeypatch)

    p1 = _make_freebsd_patcher(data_path)
    assert p1.auto() is True
    exe_path = p1.executable_path
    assert os.path.exists(exe_path)
    assert p1.is_binary_patched(exe_path)

    # Simulate the cleanup that Patcher.__del__ performs after the driver is
    # closed: the patched binary is removed but version.txt remains.
    os.unlink(exe_path)
    assert os.path.exists(os.path.join(data_path, "version.txt"))

    p2 = _make_freebsd_patcher(data_path)
    assert p2.auto() is True
    assert os.path.exists(p2.executable_path)
    assert p2.is_binary_patched(p2.executable_path)


def test_freebsd_del_does_not_delete_binary(monkeypatch, tmp_path):
    """Patcher.__del__ must not delete the patched binary on FreeBSD.

    The binary is copied from the system chromedriver (not downloaded fresh
    each time).  Deleting it between sessions causes a race condition where
    the next Patcher instance finds the file missing (issue #82 follow-up).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_fake_chromedriver(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_path = str(data_dir)

    _hide_stealth_marker(monkeypatch)

    p = _make_freebsd_patcher(data_path)
    assert p.auto() is True
    exe_path = p.executable_path
    assert os.path.exists(exe_path)

    # Trigger __del__ — the binary must survive.
    del p
    gc.collect()
    assert os.path.exists(exe_path), "__del__ deleted the patched binary on FreeBSD"


def test_freebsd_auto_recovers_with_custom_exe_path_when_file_missing(monkeypatch, tmp_path):
    """Regression test for issue #82 follow-up: race condition.

    After the startup test, _save_patched_driver sets PATCHED_DRIVER_PATH.
    On the next request, Patcher is created with _custom_exe_path=True.
    If the binary was deleted by a previous __del__, auto() must fall
    through to the copy logic instead of calling patch_exe() on a
    non-existent file.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_fake_chromedriver(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_path = str(data_dir)
    exe_path = os.path.join(data_path, "chromedriver")

    _hide_stealth_marker(monkeypatch)

    # Simulate the startup test: patcher with _custom_exe_path=False.
    p1 = _make_freebsd_patcher(data_path)
    assert p1.auto() is True
    assert os.path.exists(exe_path)

    # Simulate a previous __del__ deleting the binary (pre-fix behaviour).
    os.unlink(exe_path)

    # Simulate the first request: PATCHED_DRIVER_PATH is set, so the patcher
    # gets _custom_exe_path=True pointing at the same path.
    p2 = _make_freebsd_patcher(data_path, executable_path=exe_path)
    assert p2._custom_exe_path is True
    assert p2.auto() is True
    assert os.path.exists(p2.executable_path)
    assert p2.is_binary_patched(p2.executable_path)

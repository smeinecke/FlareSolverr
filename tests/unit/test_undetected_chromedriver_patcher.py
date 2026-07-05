import os
import tempfile
from pathlib import Path

import pytest

from flaresolverr.undetected_chromedriver.patcher import Patcher


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


def _make_freebsd_patcher(data_path: str, version_main: int = 148) -> Patcher:
    p = Patcher(version_main=version_main)
    # Force the FreeBSD code path against an isolated data directory.
    p.platform = "freebsd15"
    p.platform_name = "freebsd"
    p.data_path = data_path
    p.executable_path = os.path.join(data_path, "chromedriver")
    p._custom_exe_path = False
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

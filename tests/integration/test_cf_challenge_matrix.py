"""Cloudflare challenge matrix harness.

Runs the same challenged targets through several browser attachment/display
arms and records per-(arm, target) results — including the Cloudflare Ray ID —
so attachment-related detection differences can be measured under identical
egress conditions.

Arms:
  manual-headless  custom Chromium via subprocess + CDP attach (production path)
  manual-headed    same, but HEADLESS=false (skipped without a display)
  uc-chromedriver  undetected_chromedriver (chromedriver-attached control)
  dump-dom         `chrome --headless=new --dump-dom` — zero CDP attachment

Configuration (env):
  FLARESOLVERR_CF_MATRIX   output JSON path (default /tmp/cf_challenge_matrix.json)
  CF_MATRIX_TARGETS        comma-separated URLs (default: live CF targets)
  CF_MATRIX_PROXY          e.g. socks5://127.0.0.1:1080 — same egress for all arms
  CF_MATRIX_TIMEOUT        per-(arm, target) timeout in seconds (default 60)

Run:
    PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest \
        tests/integration/test_cf_challenge_matrix.py -m integration -s
"""

import json
import os
import random
import re
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from flaresolverr import utils  # noqa: E402

pytestmark = pytest.mark.integration

DEFAULT_TARGETS = "https://tmailor.com/en/,https://tempmailo.com/"
OUT_PATH = os.environ.get("FLARESOLVERR_CF_MATRIX", "/tmp/cf_challenge_matrix.json")
TIMEOUT = int(os.environ.get("CF_MATRIX_TIMEOUT", "60"))
PROXY = os.environ.get("CF_MATRIX_PROXY", "").strip() or None

CF_RAY_RE = re.compile(r'"cRay"\s*:\s*"([^"]+)"')
CF_TYPE_RE = re.compile(r'"cType"\s*:\s*"([^"]+)"')


def _verdict_from_page(title: str, page_source: str, cookies: list[dict]) -> tuple[str, dict]:
    """Classify the final page state into a coarse verdict + CF metadata."""
    meta = {}
    m = CF_RAY_RE.search(page_source or "")
    if m:
        meta["cfRay"] = m.group(1)
    m = CF_TYPE_RE.search(page_source or "")
    if m:
        meta["cfType"] = m.group(1)
    meta["cfClearance"] = any(c.get("name") == "cf_clearance" for c in cookies)

    title_l = (title or "").lower()
    challenged_markers = ("just a moment", "performing security verification", "attention required")
    if meta.get("cfClearance"):
        return "passed", meta
    if any(t in title_l for t in challenged_markers) or '"cRay"' in (page_source or ""):
        return "challenged", meta
    return "passed", meta


def _driver_arm(url: str, headless: bool | None, use_uc: bool) -> dict:
    """Drive a real browser to the target and classify the result."""
    record: dict = {"headless": headless, "uc": use_uc}
    driver = None
    old_headless = os.environ.get("HEADLESS")
    try:
        if headless is not None:
            os.environ["HEADLESS"] = "true" if headless else "false"
        proxy = {"url": PROXY} if PROXY else None
        if use_uc:
            # Bypass get_webdriver's manual-launch path: let chromedriver own
            # the browser (adds --enable-automation — the detection control).
            from flaresolverr import undetected_chromedriver as uc  # noqa: PLC0415

            opts = uc.ChromeOptions()
            opts.binary_location = utils.get_chrome_exe_path()
            if PROXY:
                opts.add_argument(f"--proxy-server={PROXY}")
            if headless is not False:
                opts.add_argument("--headless=new")
            driver = uc.Chrome(options=opts)
        else:
            driver = utils.get_webdriver(proxy=proxy)
        driver.set_page_load_timeout(TIMEOUT)
        start = time.time()
        try:
            driver.get(url)
        except Exception as e:  # noqa: BLE001 - record the failure verbatim
            record["navError"] = f"{type(e).__name__}: {e}"
        # Give a managed challenge room to render/pass.
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            time.sleep(5)
            try:
                title = driver.title or ""
            except Exception as e:  # noqa: BLE001
                record["navError"] = f"{type(e).__name__}: {e}"
                break
            if "just a moment" not in title.lower() and "security verification" not in title.lower():
                break
        record["elapsed"] = round(time.time() - start, 1)
        try:
            record["title"] = driver.title
            record["finalUrl"] = driver.current_url
            verdict, meta = _verdict_from_page(
                driver.title, driver.page_source, driver.get_cookies()
            )
            record["verdict"] = verdict
            record.update(meta)
        except Exception as e:  # noqa: BLE001
            record["verdict"] = "browser_crash"
            record["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001
        record["verdict"] = "error"
        record["error"] = f"{type(e).__name__}: {e}"
    finally:
        if headless is not None:
            if old_headless is None:
                os.environ.pop("HEADLESS", None)
            else:
                os.environ["HEADLESS"] = old_headless
        if driver is not None:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
    return record


def _dump_dom_arm(url: str) -> dict:
    """Zero-CDP arm: plain `chrome --headless=new --dump-dom` subprocess."""
    record: dict = {"headless": True, "uc": False}
    chrome = utils.get_chrome_exe_path()
    cmd = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--user-data-dir=/tmp/cf-matrix-dom-{os.getpid()}",
        "--dump-dom",
    ]
    if PROXY:
        cmd.insert(-1, f"--proxy-server={PROXY}")
    cmd.append(url)
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        record["elapsed"] = round(time.time() - start, 1)
        record["exitCode"] = proc.returncode
        dom = proc.stdout or ""
        record["domLen"] = len(dom)
        verdict, meta = _verdict_from_page("", dom, [])
        record["verdict"] = verdict if proc.returncode == 0 else "error"
        record.update(meta)
        if proc.returncode != 0:
            record["error"] = (proc.stderr or "").strip()[:500]
    except subprocess.TimeoutExpired:
        record["elapsed"] = TIMEOUT
        record["verdict"] = "timeout"
    return record


ARMS = {
    "manual-headless": lambda url: _driver_arm(url, headless=True, use_uc=False),
    "manual-headed": lambda url: _driver_arm(url, headless=False, use_uc=False),
    "uc-chromedriver": lambda url: _driver_arm(url, headless=None, use_uc=True),
    "dump-dom": _dump_dom_arm,
}


def _headed_available() -> bool:
    if os.environ.get("DISPLAY"):
        return True
    return os.path.exists("/usr/bin/Xvfb") or os.path.exists("/usr/bin/xvfb-run")


@pytest.mark.integration
def test_cf_challenge_matrix():
    targets = [t.strip() for t in os.environ.get("CF_MATRIX_TARGETS", DEFAULT_TARGETS).split(",") if t.strip()]
    arm_names = list(ARMS)
    random.shuffle(arm_names)  # alternate arm order; recorded per result

    results = []
    for order, arm_name in enumerate(arm_names):
        if arm_name == "manual-headed" and not _headed_available():
            results.append({"arm": arm_name, "order": order, "skipped": "no display"})
            continue
        for url in targets:
            print(f"[matrix] arm={arm_name} order={order} url={url}", flush=True)
            rec = ARMS[arm_name](url)
            rec.update({"arm": arm_name, "order": order, "url": url, "proxy": PROXY})
            results.append(rec)
            print(f"[matrix]   -> {rec.get('verdict')} ray={rec.get('cfRay')} title={rec.get('title')!r}", flush=True)

    payload = {
        "timestamp": time.time(),
        "timeout": TIMEOUT,
        "proxy": PROXY,
        "chrome": utils.get_chrome_exe_path(),
        "stealthMode": utils.get_config_stealth_mode(),
        "results": results,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"[matrix] wrote {OUT_PATH}")

    # Diagnostic harness: assert only that the run produced data.
    assert any("verdict" in r for r in results)

"""Cloudflare challenge matrix harness.

Runs the same challenged targets through several browser attachment/display
arms and records per-(arm, target) results — including the Cloudflare Ray ID —
so attachment-related detection differences can be measured under identical
egress conditions.

Arms (all share the production launch flags; only the launch/attach
mechanism differs):
  manual-headless  custom Chromium via subprocess + CDP attach (production path)
  manual-headed    same, but HEADLESS=false (skipped without a display)
  uc-chromedriver  same flags, but chromedriver owns the browser launch
                   (adds --enable-automation etc.) — isolates attachment
  dump-dom         `chrome --headless=new --dump-dom` — no external attach,
                   but NOT zero-CDP (internal DevTools machinery, exits at
                   load + virtual-time-budget) — weak signal only

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
import shutil
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from flaresolverr import utils

pytestmark = pytest.mark.integration

DEFAULT_TARGETS = "https://tmailor.com/en/,https://tempmailo.com/"
OUT_PATH = os.environ.get("FLARESOLVERR_CF_MATRIX", "/tmp/cf_challenge_matrix.json")
TIMEOUT = int(os.environ.get("CF_MATRIX_TIMEOUT", "60"))
PROXY = os.environ.get("CF_MATRIX_PROXY", "").strip() or None

# _cf_chl_opt keys are unquoted JS object properties (cRay: "..."), so the
# key itself must be matched with optional quotes.
CF_RAY_RE = re.compile(r'["\']?cRay["\']?\s*:\s*["\']([^"\']+)["\']')
CF_TYPE_RE = re.compile(r'["\']?cType["\']?\s*:\s*["\']([^"\']+)["\']')

# Challenge interstitial markers — only present on the CF "Just a moment"
# page itself (titles are localized — e.g. "Nur einen Moment…").
CF_INTERSTITIAL_MARKERS = (
    "_cf_chl_opt",
    "cf-challenge-running",
    "challenge-stage",
)
# Weak markers — real pages legitimately embed Turnstile widgets, and
# cdn-cgi/challenge-platform scripts also run on ordinary pages with JS
# Detections enabled, so these alone do not prove an interstitial.
CF_WIDGET_MARKERS = (
    "cdn-cgi/challenge-platform",
    "challenges.cloudflare.com",
    "cf-turnstile",
)
# Localized CF interstitial titles seen in the wild.
CF_CHALLENGE_TITLES = (
    "just a moment",
    "nur einen moment",
    "performing security verification",
    "attention required",
    "un instant",
    "un momento",
)


def _verdict_from_page(
    title: str,
    page_source: str,
    cookies: list[dict],
    final_url: str = "",
    nav_error: str | None = None,
) -> tuple[str, dict]:
    """Classify the final page state into a coarse verdict + CF metadata.

    "passed" requires positive evidence of a real document — navigation
    failures, chrome-error pages and empty bodies are never passes, and a
    stale cf_clearance cookie does not override a visible challenge.
    """
    meta = {}
    m = CF_RAY_RE.search(page_source or "")
    if m:
        meta["cfRay"] = m.group(1)
    m = CF_TYPE_RE.search(page_source or "")
    if m:
        meta["cfType"] = m.group(1)
    meta["cfClearance"] = any(c.get("name") == "cf_clearance" for c in cookies)

    src = page_source or ""
    title_l = (title or "").lower()
    markers = [m for m in CF_INTERSTITIAL_MARKERS + CF_WIDGET_MARKERS if m in src]
    if markers:
        meta["markers"] = markers
    meta["domLen"] = len(src)
    interstitial = any(m in src for m in CF_INTERSTITIAL_MARKERS)
    challenge_title = any(t in title_l for t in CF_CHALLENGE_TITLES)

    # chrome-error:// is definitive; a driver.get() TimeoutException alone is
    # not (challenge pages keep network busy past the load timeout).
    if final_url.startswith(("chrome-error://", "chrome://")):
        return "nav_error", meta
    if interstitial or challenge_title:
        return "challenged", meta
    if nav_error:
        return "nav_error", meta
    # Browser-rendered network/server error pages are large enough to clear
    # the byte threshold but are not passes.
    if 'id="main-frame-error"' in src or re.search(r"net::ERR_|ERR_CONNECTION|ERR_NAME_|ERR_TIMED", src):
        return "nav_error", meta
    if len(src.strip()) < 256:
        return "empty", meta
    if not (title or "").strip():
        # No challenge evidence, but also no positive evidence of a real
        # rendered document — a bare byte count is not a pass.
        return "unknown", meta
    return "passed", meta


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _title_from_html(html: str) -> str:
    m = _TITLE_RE.search(html or "")
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


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
            # ChromeDriver owns the browser launch (adds --enable-automation
            # and friends) — but the browser flags are identical to the
            # production path so attachment is the only changed variable.
            from flaresolverr import undetected_chromedriver as uc

            opts = utils._build_chrome_options(
                utils.get_config_stealth_mode(), load_extension=bool(PROXY)
            )
            opts.binary_location = utils.get_chrome_exe_path()
            proxy_ext_dir = None
            proxy_ext_id = None
            if PROXY:
                proxy_ext_dir, proxy_ext_id = utils._build_stealth_extension_dir()
                opts.add_argument(f"--load-extension={os.path.abspath(proxy_ext_dir)}")
            if headless is not False:
                opts.add_argument("--headless=new")
            driver = uc.Chrome(options=opts)
            if PROXY and proxy_ext_id:
                driver._proxy_ext_id = proxy_ext_id
                driver._proxy_ext_dir = proxy_ext_dir
                utils.apply_proxy_to_session(driver, proxy)
            # Recorded flags are the requested ones — chromedriver adds its
            # own (e.g. --enable-automation) at launch.
            record["launchArgs"] = list(opts.arguments)
        else:
            driver = utils.get_webdriver(proxy=proxy)
            record["launchArgs"] = getattr(driver, "_flaresolverr_launch_args", None)
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
            if not any(t in title.lower() for t in CF_CHALLENGE_TITLES):
                break
        record["elapsed"] = round(time.time() - start, 1)
        try:
            record["title"] = driver.title
            record["finalUrl"] = driver.current_url
            verdict, meta = _verdict_from_page(
                driver.title,
                driver.page_source,
                driver.get_cookies(),
                final_url=driver.current_url or "",
                nav_error=record.get("navError"),
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
            ext_dir = getattr(driver, "_proxy_ext_dir", None)
            try:
                driver.quit()
            except Exception as exc:  # noqa: BLE001
                print(f"[matrix] driver.quit failed: {exc}")
            if ext_dir and os.path.isdir(ext_dir):
                shutil.rmtree(ext_dir, ignore_errors=True)
    return record


def _dump_dom_arm(url: str) -> dict:
    """No-external-attach arm: `chrome --headless=new --dump-dom` subprocess.

    NOTE: this is NOT a zero-CDP control — Chromium implements --dump-dom via
    internal DevTools machinery (Target.attachToTarget / Runtime.evaluate) and
    exits right after page load, so a managed challenge only gets
    --virtual-time-budget worth of virtual time to resolve. Treat its verdicts
    as a weak signal only.
    """
    record: dict = {"headless": True, "uc": False}
    chrome = utils.get_chrome_exe_path()
    # Reuse the production launch flags so this arm differs only in the
    # absence of an external driver/attachment.
    prod = utils._build_chrome_options(utils.get_config_stealth_mode(), load_extension=False)
    cmd = [
        chrome,
        *prod.arguments,
        "--headless=new",
        f"--user-data-dir=/tmp/cf-matrix-dom-{os.getpid()}",
        f"--virtual-time-budget={TIMEOUT * 1000}",
        "--dump-dom",
        url,
    ]
    if PROXY:
        # The proxy extension cannot be configured from a one-shot process;
        # --proxy-server only supports proxies without auth here.
        cmd.insert(-1, f"--proxy-server={PROXY}")
    record["launchArgs"] = cmd[1:]
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
        record["elapsed"] = round(time.time() - start, 1)
        record["exitCode"] = proc.returncode
        dom = proc.stdout or ""
        record["title"] = _title_from_html(dom)
        verdict, meta = _verdict_from_page(record["title"], dom, [])
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

"""Cross-vendor WAF/anti-bot challenge matrix harness.

Runs live targets behind non-Cloudflare challenge systems (Vercel
checkpoint, Hetzner HeRay, Anubis PoW, DataDome, PerimeterX) through each
available driver backend and records per-(backend, target) verdicts so
backend-specific regressions can be compared under identical egress.

Arms are real DRIVER_BACKEND launches (same code path as production
utils.get_webdriver); backends whose optional packages are not installed
are skipped.

Configuration (env):
  FLARESOLVERR_WAF_MATRIX   output JSON path (default /tmp/waf_challenge_matrix.json)
  WAF_MATRIX_TARGETS        comma-separated URLs (default: verified live targets)
  WAF_MATRIX_BACKENDS       comma-separated backends (default: undetected_chromedriver,camoufox)
  WAF_MATRIX_PROXY          e.g. socks5://127.0.0.1:1080 — same egress for all arms
  WAF_MATRIX_TIMEOUT        per-(backend, target) settle window in seconds (default 60)

Run:
    PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest \
        tests/integration/test_waf_challenge_matrix.py -m integration -s
"""

import contextlib
import json
import os
import random
import re
import sys
import time
from urllib.parse import urlparse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from flaresolverr import utils

pytestmark = pytest.mark.integration

# Verified live targets (2026-10-06):
#   svgrepo.com      Vercel Security Checkpoint (CF JSD + challenge.v2.wasm)
#   anubis.techaro.lol  Anubis PoW
#   leboncoin.fr     DataDome
#   zillow.com       PerimeterX (crashes Chromium renderers pre-dcheck-fix)
#   robot.your-server.de/server  Hetzner HeRay PoW
DEFAULT_TARGETS = (
    "https://www.svgrepo.com/,"
    "https://anubis.techaro.lol/,"
    "https://www.leboncoin.fr/,"
    "https://www.zillow.com/,"
    "https://robot.your-server.de/server"
)
DEFAULT_BACKENDS = "undetected_chromedriver,camoufox"
OUT_PATH = os.environ.get("FLARESOLVERR_WAF_MATRIX", "/tmp/waf_challenge_matrix.json")
TIMEOUT = int(os.environ.get("WAF_MATRIX_TIMEOUT", "60"))
PROXY = os.environ.get("WAF_MATRIX_PROXY", "").strip() or None

# Challenge-page markers, grouped by vendor. These are page-structure
# strings, not titles — titles are localized and generic ("Security Check"
# alone is not distinctive enough).
WAF_INTERSTITIAL_MARKERS = (
    "_cf_chl_opt",                    # Cloudflare
    "cf-challenge-running",
    "challenge-stage",
    "Vercel Security Checkpoint",     # Vercel checkpoint body/title
    "/__ray_static/",                 # Hetzner HeRay (both stages)
    "_ray/pow",
    "challenge-platform/scripts/jsd", # CF JSD embed (incl. Vercel shell)
    "captcha-delivery.com",           # DataDome interstitial/captcha
    "x-datadome",
    "px-captcha",                     # PerimeterX captcha
    "_pxhd",                          # PerimeterX sensor marker
    "/.within.website/x/cmd/anubis/", # Anubis pass-challenge endpoint path
)
WAF_BLOCK_TITLES = (
    "access to this page has been denied",  # PerimeterX deny page
    "access denied",
    "request on hold",                      # HeRay wait queue
    "security check",                       # HeRay PoW stage
    "vercel security checkpoint",
    "making sure you",                      # Anubis "Making sure you're not a bot!"
    "just a moment",
    "nur einen moment",
    "attention required",
    "too many requests",
)
ERROR_TITLES = (
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "internal server error",
    "temporarily unavailable",
)


def _verdict_from_page(
    title: str,
    page_source: str,
    cookies: list[dict],
    final_url: str = "",
    nav_error: str | None = None,
    http_status: int | None = None,
    expected_host: str | None = None,
) -> tuple[str, dict]:
    """Classify final page state for arbitrary WAF challenge systems.

    Unlike the CF matrix, "challenged" here means any recognized WAF
    interstitial/block page. "passed" still requires positive evidence of
    a real document on the target host.
    """
    meta: dict = {}
    src = page_source or ""
    title_l = (title or "").lower()
    if http_status is not None:
        meta["httpStatus"] = http_status
    markers = [m for m in WAF_INTERSTITIAL_MARKERS if m in src]
    if markers:
        meta["markers"] = markers
    meta["domLen"] = len(src)
    cookie_names = {c.get("name", "") for c in cookies}
    interesting = cookie_names & {
        "cf_clearance", "_vcrcs", "heray-clearance", "datadome", "_px3",
    }
    if interesting:
        meta["clearanceCookies"] = sorted(interesting)

    if final_url.startswith(("chrome-error://", "chrome://")):
        return "nav_error", meta
    interstitial = bool(markers)
    block_title = any(t in title_l for t in WAF_BLOCK_TITLES)
    if interstitial or block_title:
        # A challenge page visible at capture time is never a pass, even if
        # a clearance cookie is already present (the navigation to the real
        # page may not have happened yet).
        return "challenged", meta
    if nav_error:
        return "nav_error", meta
    if 'id="main-frame-error"' in src or re.search(r"net::ERR_|ERR_CONNECTION|ERR_NAME_|ERR_TIMED", src):
        return "nav_error", meta
    if len(src.strip()) < 256:
        return "empty", meta
    if http_status is not None and http_status >= 400:
        return "unknown", meta
    if any(t in title_l for t in ERROR_TITLES):
        return "unknown", meta
    if expected_host and final_url:
        final_host = urlparse(final_url).netloc
        if final_host and final_host != expected_host:
            meta["redirectedTo"] = final_host
            return "unknown", meta
    if not (title or "").strip():
        return "unknown", meta
    return "passed", meta


def _backend_available(name: str) -> str | None:
    """Return a skip reason if the backend's optional deps are missing."""
    if name == "camoufox":
        try:
            import camoufox  # noqa: F401
        except ImportError:
            return "camoufox package not installed"
    if name == "seleniumbase":
        try:
            import seleniumbase  # noqa: F401
        except ImportError:
            return "seleniumbase package not installed"
    if name == "playwright":
        try:
            import playwright  # noqa: F401
        except ImportError:
            return "playwright package not installed"
    return None


def _backend_arm(backend: str, url: str) -> dict:
    """Launch the given backend via the production path and classify."""
    record: dict = {"backend": backend}
    driver = None
    old_backend = os.environ.get("DRIVER_BACKEND")
    try:
        os.environ["DRIVER_BACKEND"] = backend
        proxy = {"url": PROXY} if PROXY else None
        driver = utils.get_webdriver(proxy=proxy)
        record["launchArgs"] = getattr(driver, "_flaresolverr_launch_args", None)
        with contextlib.suppress(Exception):  # some backends lack this
            driver.set_page_load_timeout(TIMEOUT)
        start = time.time()
        try:
            driver.get(url)
        except Exception as e:  # noqa: BLE001 — record verbatim
            record["navError"] = f"{type(e).__name__}: {e}"

        # Challenge PoW/checkpoint pages need wall-clock time to self-solve;
        # poll until the page leaves a known challenge state or the window ends.
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            time.sleep(5)
            try:
                title = driver.title or ""
                src_head = driver.page_source or ""
            except Exception as e:  # noqa: BLE001
                record["navError"] = f"{type(e).__name__}: {e}"
                break
            verdict, _ = _verdict_from_page(title, src_head, [], final_url=driver.current_url or "")
            if verdict not in ("challenged",):
                break
        record["elapsed"] = round(time.time() - start, 1)

        try:
            http_status = None
            with contextlib.suppress(Exception):  # perf log optional
                http_status = utils.get_document_response_evidence(driver).get("status")
            verdict, meta = _verdict_from_page(
                driver.title or "",
                driver.page_source or "",
                driver.get_cookies(),
                final_url=driver.current_url or "",
                nav_error=record.get("navError"),
                http_status=http_status,
                expected_host=urlparse(url).netloc,
            )
            record["verdict"] = verdict
            record["title"] = driver.title
            record["finalUrl"] = driver.current_url
            record.update(meta)
        except Exception as e:  # noqa: BLE001
            # A driver call failing outright mid-inspection usually means the
            # browser process died (e.g. DCHECK abort on zillow.com).
            record["verdict"] = "browser_crash"
            record["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001
        record["verdict"] = "error"
        record["error"] = f"{type(e).__name__}: {e}"
    finally:
        if old_backend is None:
            os.environ.pop("DRIVER_BACKEND", None)
        else:
            os.environ["DRIVER_BACKEND"] = old_backend
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:  # noqa: BLE001
                print(f"[waf-matrix] driver.quit failed: {exc}")
    return record


@pytest.mark.integration
def test_waf_challenge_matrix():
    targets = [t.strip() for t in os.environ.get("WAF_MATRIX_TARGETS", DEFAULT_TARGETS).split(",") if t.strip()]
    backends = [b.strip() for b in os.environ.get("WAF_MATRIX_BACKENDS", DEFAULT_BACKENDS).split(",") if b.strip()]
    random.shuffle(backends)

    results = []
    for order, backend in enumerate(backends):
        skip = _backend_available(backend)
        if skip:
            results.append({"backend": backend, "order": order, "skipped": skip})
            print(f"[waf-matrix] backend={backend} skipped: {skip}", flush=True)
            continue
        for url in targets:
            print(f"[waf-matrix] backend={backend} order={order} url={url}", flush=True)
            rec = _backend_arm(backend, url)
            rec.update({"backend": backend, "order": order, "url": url, "proxy": PROXY})
            results.append(rec)
            print(f"[waf-matrix]   -> {rec.get('verdict')} title={rec.get('title')!r}", flush=True)

    payload = {
        "timestamp": time.time(),
        "timeout": TIMEOUT,
        "proxy": PROXY,
        "results": results,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"[waf-matrix] wrote {OUT_PATH}")

    # Diagnostic harness: assert only that the run produced data. Verdicts are
    # empirical and recorded for comparison across backends/runs.
    assert any("verdict" in r for r in results)


class TestWafVerdictClassifier:
    """Deterministic coverage: WAF challenge pages classify 'challenged',
    real documents pass, error pages never pass."""

    BIG_PAGE = "<html><body>" + "x" * 1024 + "</body></html>"

    def test_vercel_checkpoint_is_challenged(self):
        html = '<html><head><title>Vercel Security Checkpoint</title></head><body>' + "x" * 1024 + "</body></html>"
        verdict, _ = _verdict_from_page("Vercel Security Checkpoint", html, [])
        assert verdict == "challenged"

    def test_heray_wait_page_is_challenged(self):
        html = '<html><head><title>Request on Hold</title><script src="/__ray_static/1.js"></script></head><body>' + "x" * 1024 + "</body></html>"
        verdict, meta = _verdict_from_page("Request on Hold", html, [], http_status=429)
        assert verdict == "challenged"
        assert "/__ray_static/" in meta["markers"]

    def test_anubis_page_is_challenged(self):
        html = ('<html><head><title>Making sure you&#39;re not a bot!</title>'
                '<meta http-equiv="refresh" content="2; url=/.within.website/x/cmd/anubis/api/pass-challenge?challenge=x">'
                '</head><body>' + "x" * 1024 + "</body></html>")
        verdict, _ = _verdict_from_page("Making sure you're not a bot!", html, [])
        assert verdict == "challenged"

    def test_anubis_docs_site_is_not_challenged(self):
        # The real anubis.techaro.lol landing page mentions Anubis by name —
        # only the endpoint path/title may trigger, not the word itself.
        verdict, _ = _verdict_from_page(
            "Anubis: Web AI Firewall Utility | Anubis", self.BIG_PAGE,
            [{"name": "techaro.lol-anubis-auth-x", "value": "x"}],
            final_url="https://anubis.techaro.lol/",
            http_status=200,
            expected_host="anubis.techaro.lol",
        )
        assert verdict == "passed"

    def test_px_denied_is_challenged(self):
        verdict, _ = _verdict_from_page(
            "Access to this page has been denied", self.BIG_PAGE, [], http_status=403,
        )
        assert verdict == "challenged"

    def test_datadome_marker_is_challenged(self):
        html = '<html><body><iframe src="https://geo.captcha-delivery.com/interstitial/"></iframe>' + "x" * 1024 + "</body></html>"
        verdict, _ = _verdict_from_page("leboncoin", html, [])
        assert verdict == "challenged"

    def test_real_document_passes(self):
        verdict, meta = _verdict_from_page(
            "SVG Repo - Free SVG Vectors and Icons", self.BIG_PAGE,
            [{"name": "_vcrcs", "value": "x"}],
            final_url="https://www.svgrepo.com/",
            http_status=200,
            expected_host="www.svgrepo.com",
        )
        assert verdict == "passed"
        assert meta["clearanceCookies"] == ["_vcrcs"]

    def test_http_error_status_is_not_a_pass(self):
        for status in (403, 429, 500, 503):
            verdict, _ = _verdict_from_page("Some Page", self.BIG_PAGE, [], http_status=status)
            assert verdict == "unknown", status

    def test_clearance_cookie_does_not_override_visible_challenge(self):
        html = '<html><head><title>Vercel Security Checkpoint</title></head><body>' + "x" * 1024 + "</body></html>"
        verdict, _ = _verdict_from_page(
            "Vercel Security Checkpoint", html, [{"name": "_vcrcs", "value": "x"}],
            http_status=429,
        )
        assert verdict == "challenged"

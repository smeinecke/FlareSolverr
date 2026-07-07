import glob
import hashlib
import json
import logging
import os
import platform
import random
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
from typing import Any
from datetime import datetime, timedelta, timezone
from importlib.metadata import version

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import pefile  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError:
    pefile = None  # type: ignore[misc]

try:
    from xvfbwrapper import Xvfb  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError:
    Xvfb = None  # type: ignore[misc,assignment]

from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.action_chains import ActionChains
from flaresolverr import undetected_chromedriver as uc  # type: ignore[import-untyped]

FLARESOLVERR_VERSION: str | None = None
PLATFORM_VERSION: str | None = None
CHROME_EXE_PATH: str | None = None
CHROME_MAJOR_VERSION: str | None = None
CHROME_FULL_VERSION: str | None = None
USER_AGENT: str | None = None
XVFB_DISPLAY = None
PATCHED_DRIVER_PATH: str | None = None
_STEALTH_SCRIPT: str | None = None
_STEALTH_FALLBACK_SCRIPT: str | None = None
_CUSTOM_CHROMIUM: bool | None = None

STEALTH_MODE_OFF = "off"
STEALTH_MODE_STANDARD = "standard"
STEALTH_MODE_CSP_SAFE = "csp-safe"
VALID_STEALTH_MODES = {STEALTH_MODE_OFF, STEALTH_MODE_STANDARD, STEALTH_MODE_CSP_SAFE}

_TEXT_CONTENT_PREFIXES = (
    "text/",
    "application/json",
    "application/javascript",
    "application/xml",
    "application/xhtml+xml",
    "application/ld+json",
)


def is_binary_content_type(content_type: str | None) -> bool:
    """Return True if the content-type indicates binary data."""
    if not content_type:
        return True
    ct = content_type.lower()
    return not ct.startswith(_TEXT_CONTENT_PREFIXES)


def _load_stealth_script(fallback: bool = False) -> str:
    global _STEALTH_SCRIPT, _STEALTH_FALLBACK_SCRIPT
    if fallback:
        if _STEALTH_FALLBACK_SCRIPT is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stealth_fallback.js")
            with open(path) as f:
                _STEALTH_FALLBACK_SCRIPT = f.read()
        return _STEALTH_FALLBACK_SCRIPT
    if _STEALTH_SCRIPT is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stealth.js")
        with open(path) as f:
            _STEALTH_SCRIPT = f.read()
    return _STEALTH_SCRIPT


def _is_custom_chromium() -> bool:
    global _CUSTOM_CHROMIUM
    if _CUSTOM_CHROMIUM is not None:
        return _CUSTOM_CHROMIUM

    machine = platform.machine().lower()
    if machine not in ("x86_64", "amd64", "aarch64", "arm64"):
        _CUSTOM_CHROMIUM = False
        return False

    # The chromium-patches Dockerfile writes this sentinel to /opt/chromium/
    # and the main Dockerfile copies it alongside the binary to /usr/bin/.
    # Checking for it avoids spawning a Chrome subprocess and is reliable.
    # Also accept a sentinel next to the extracted local chrome binary.
    chrome_dir = os.path.dirname(get_chrome_exe_path() or "")
    _CUSTOM_CHROMIUM = os.path.exists("/opt/chromium/.stealth-patched") or (chrome_dir != "" and os.path.exists(os.path.join(chrome_dir, ".stealth-patched")))
    return bool(_CUSTOM_CHROMIUM)


def get_config_log_html() -> bool:
    return os.environ.get("LOG_HTML", "false").lower() == "true"


def get_config_headless() -> bool:
    return os.environ.get("HEADLESS", "true").lower() == "true"


def get_config_disable_media() -> bool:
    return os.environ.get("DISABLE_MEDIA", "false").lower() == "true"


def get_config_js_injection_enabled() -> bool:
    """Master switch for JavaScript injection features (issue #38).

    Disabled by default for security. Must be explicitly enabled via the
    JS_INJECTION_ENABLED environment variable.
    """
    return os.environ.get("JS_INJECTION_ENABLED", "false").lower() == "true"


def get_config_disable_quic() -> bool:
    return os.environ.get("DISABLE_QUIC", "true").lower() == "true"


def get_config_minimal_fingerprint() -> bool:
    return os.environ.get("MINIMAL_FINGERPRINT", "true").lower() == "true"


def get_config_session_max_runtime() -> timedelta | None:
    raw = os.environ.get("SESSION_MAX_RUNTIME", "").strip()
    if raw == "":
        return None
    try:
        return timedelta(minutes=int(raw))
    except ValueError:
        return None


def get_config_session_idle_timeout() -> timedelta:
    raw = os.environ.get("SESSION_IDLE_TIMEOUT", "15").strip()
    if raw == "":
        return timedelta(minutes=15)
    try:
        return timedelta(minutes=int(raw))
    except ValueError:
        return timedelta(minutes=15)


def get_config_session_max_count() -> int | None:
    raw = os.environ.get("SESSION_MAX_COUNT", "").strip()
    if raw == "":
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except ValueError:
        return None


def get_config_max_parallel_requests() -> int | None:
    raw = os.environ.get("MAX_PARALLEL_REQUESTS", "").strip()
    if raw == "":
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except ValueError:
        return None


def get_config_chrome_disable_optimizations() -> bool:
    return os.environ.get("CHROME_DISABLE_OPTIMIZATIONS", "false").lower() == "true"


def get_config_chrome_extra_flags() -> list[str]:
    raw = os.environ.get("CHROME_EXTRA_FLAGS", "").strip()
    if not raw:
        return []
    return [flag.strip() for flag in raw.split(",") if flag.strip()]


def get_config_agent_check_port() -> int | None:
    raw = os.environ.get("AGENT_CHECK_PORT", "").strip()
    if raw == "":
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except ValueError:
        return None


def get_config_agent_check_host() -> str:
    return os.environ.get("AGENT_CHECK_HOST", "127.0.0.1").strip() or "127.0.0.1"


def normalize_stealth_mode(value: str | bool | None) -> str:
    """Normalize boolean/legacy values to a stealth mode enum value."""
    if value is None:
        return STEALTH_MODE_OFF
    if isinstance(value, bool):
        return STEALTH_MODE_STANDARD if value else STEALTH_MODE_OFF
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "on"}:
        return STEALTH_MODE_STANDARD
    if raw in {"false", "0", "no", "off"}:
        return STEALTH_MODE_OFF
    if raw in VALID_STEALTH_MODES:
        return raw
    raise ValueError(f"Invalid stealth mode: {value!r}. Valid values: {sorted(VALID_STEALTH_MODES)}")


def get_config_stealth_mode() -> str:
    return normalize_stealth_mode(os.environ.get("STEALTH_MODE", STEALTH_MODE_OFF))


def get_config_accept_language() -> str:
    return os.environ.get("ACCEPT_LANGUAGE", "en-US,en")


def _apply_stealth_patches(driver: WebDriver, stealth_mode: str) -> None:
    # standard mode: enable WebGL spoofing - the worker wrapper also patches workers
    # so main/worker WebGL values stay consistent.
    # csp-safe mode: disable WebGL spoofing - blob: worker injection is skipped
    # (BLOB_BYPASS=true), so the worker would see real renderer values and a
    # main-thread spoof would create a detectable inconsistency.
    patch_webgl = stealth_mode == STEALTH_MODE_STANDARD
    patch_blob_bypass = stealth_mode == STEALTH_MODE_CSP_SAFE
    prelude = (
        f"window.__FS_STEALTH_PATCH_WEBGL = {'true' if patch_webgl else 'false'};\n"
        f"window.__FS_STEALTH_BLOB_BYPASS = {'true' if patch_blob_bypass else 'false'};\n"
    )
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": prelude + _load_stealth_script(fallback=True)})


def apply_user_agent_override(driver: WebDriver, user_agent: str, accept_language: str | None = None) -> None:
    """Apply a custom user agent string at the CDP level with full metadata.

    Uses Emulation.setUserAgentOverride with userAgentMetadata to ensure
    navigator.userAgentData is consistent with navigator.userAgent.
    """
    # Parse UA to extract platform and Chrome version
    # e.g., "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    platform_match = re.search(r"\(([^)]+)\)", user_agent)
    platform_str = platform_match.group(1) if platform_match else "Windows NT 10.0; Win64; x64"

    # Determine platform and architecture from UA
    if "Linux" in platform_str:
        platform = "Linux"
        platform_version = ""
        architecture = "x64" if "x86_64" in platform_str or "x64" in platform_str else "x86"
    elif "Mac" in platform_str or "Darwin" in platform_str:
        platform = "macOS"
        platform_version = "14.0.0"  # Generic macOS version
        architecture = "arm" if "arm" in user_agent.lower() else "x64"
    elif "Win" in platform_str:
        platform = "Windows"
        platform_version = "10.0.0"
        architecture = "x64" if "Win64" in platform_str or "x64" in platform_str else "x86"
    else:
        platform = "Windows"
        platform_version = "10.0.0"
        architecture = "x64"

    # Extract Chrome version
    chrome_match = re.search(r"Chrome/(\d+)\.", user_agent)
    chrome_major = chrome_match.group(1) if chrome_match else "130"
    chrome_full = get_chrome_full_version()
    if not chrome_full:
        chrome_full = f"{chrome_major}.0.0.0"

    # Build brands array (Chrome's GREASEd brand format)
    brands = [
        {"brand": "Chromium", "version": chrome_major},
        {"brand": "Google Chrome", "version": chrome_major},
        {"brand": "Not.A/Brand", "version": "24"},
    ]

    driver.execute_cdp_cmd(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": user_agent,
            "acceptLanguage": accept_language if accept_language is not None else get_config_accept_language(),
            "userAgentMetadata": {
                "platform": platform,
                "platformVersion": platform_version,
                "architecture": architecture,
                "model": "",
                "mobile": False,
                "brands": brands,
                "fullVersionList": [
                    {"brand": "Chromium", "version": chrome_full},
                    {"brand": "Google Chrome", "version": chrome_full},
                    {"brand": "Not.A/Brand", "version": "24.0.0.0"},
                ],
            },
        },
    )


def sanitize_user_agent(user_agent: str) -> str:
    """Normalize default headless UA tokens to regular Chrome tokens."""
    return user_agent.replace("HeadlessChrome/", "Chrome/")


def get_flaresolverr_version() -> str:
    global FLARESOLVERR_VERSION
    if FLARESOLVERR_VERSION is not None:
        return FLARESOLVERR_VERSION

    # Prefer installed package metadata (works in Docker and after pip install).
    try:
        FLARESOLVERR_VERSION = version("flaresolverr")
        return FLARESOLVERR_VERSION
    except Exception:
        pass

    # Fall back to pyproject.toml for in-tree development runs.
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, os.pardir, "pyproject.toml"),  # src/pyproject.toml
        os.path.join(here, os.pardir, os.pardir, "pyproject.toml"),  # repo root
    ]
    for pyproject_path in candidates:
        if os.path.isfile(pyproject_path):
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                FLARESOLVERR_VERSION = data["project"]["version"]
                assert FLARESOLVERR_VERSION is not None
                return FLARESOLVERR_VERSION

    raise RuntimeError("Could not determine FlareSolverr version")


def get_current_platform() -> str:
    global PLATFORM_VERSION
    if PLATFORM_VERSION is not None:
        return PLATFORM_VERSION
    PLATFORM_VERSION = os.name
    return PLATFORM_VERSION


def _get_proxy_extension_dir() -> str:
    """Return the path to the static proxy-manager Chrome extension."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_extension")


def _compute_extension_id(extension_path: str) -> str:
    """Compute the Chrome extension ID for an unpacked extension.

    Chrome derives the extension ID from the SHA-256 of the absolute path.
    The first 16 bytes of the digest are encoded with alphabet a-p.
    """
    normalized = extension_path.replace("\\", "/").encode("utf-8")
    digest = hashlib.sha256(normalized).digest()[:16]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[b >> 4] + alphabet[b & 0x0F] for b in digest)


def _build_stealth_extension_dir() -> tuple[str, str]:
    """Create a temporary copy of the proxy extension.

    Returns (temp_extension_dir, extension_id) so the caller can
    navigate to the extension's proxy.html page directly.
    """
    static_dir = _get_proxy_extension_dir()
    temp_dir = tempfile.mkdtemp(prefix="fspe-")

    for fname in os.listdir(static_dir):
        src = os.path.join(static_dir, fname)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(temp_dir, fname)
        shutil.copy2(src, dst)

    ext_id = _compute_extension_id(temp_dir)
    return temp_dir, ext_id


def _build_chrome_options(effective_stealth_mode: str) -> ChromeOptions:
    """Build and configure ChromeOptions based on settings."""
    options = ChromeOptions()
    options.set_capability("unhandledPromptBehavior", "accept")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-search-engine-choice-screen")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-zygote")
    options.add_argument("--disk-cache-size=1")
    options.add_argument("--media-cache-size=1")

    if not get_config_chrome_disable_optimizations():
        options.add_argument("--renderer-process-limit=1")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-background-networking")
        options.add_argument("--enable-features=NetworkServiceInProcess")
        options.add_argument("--disable-component-update")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-pings")
        options.add_argument("--disable-features=MediaRouter,GlobalMediaControls,AutofillServerCommunication,OptimizationHints,Translate")

    for extra_flag in get_config_chrome_extra_flags():
        options.add_argument(extra_flag)

    minimal_fingerprint = get_config_minimal_fingerprint()

    if get_config_disable_quic():
        options.add_argument("--disable-quic")
        options.add_argument("--disable-http3")

    if not minimal_fingerprint:
        options.add_argument("--disable-features=StrictOriginIsolation")
        options.add_argument("--disable-features=IsolateOrigins")
        options.add_argument("--disable-site-isolation-trials")

    if os.environ.get("DISABLE_WEB_SECURITY", "false").lower() == "true":
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-features=BlockInsecurePrivateNetworkRequests")

    if platform.machine().startswith(("arm", "aarch")):
        options.add_argument("--disable-gpu-sandbox")

    if get_config_headless() and os.name != "nt":
        # Force SwiftShader (software GL) so the GPU process doesn't try to
        # open a real GL context and crash with a CHECK failure when no GPU is
        # available (e.g. CI, Docker, headless servers).  WebGL still works via
        # SwiftShader; --webgl-unmasked-* flags still override the fingerprint.
        options.add_argument("--use-gl=swiftshader")

    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--disable-features=LocalNetworkAccessChecks")

    if not minimal_fingerprint:
        options.add_argument("--disable-blink-features=AutomationControlled")

    if effective_stealth_mode != STEALTH_MODE_OFF and _is_custom_chromium():
        options.add_argument("--enable-trusted-synthetic-events")
        # --preload-script causes renderer crash; use CDP injection instead.
        options.add_argument("--webgl-unmasked-vendor=Intel Inc.")
        options.add_argument("--webgl-unmasked-renderer=Intel(R) Iris(TM) Graphics 6100")
        options.add_argument("--stealth-navigator-languages")
        options.add_argument("--stealth-viewport-size")
        logging.debug("Applied custom Chromium stealth flags.")

    return options


def _check_proxy_reachable(proxy_url: str) -> None:
    """Raise RuntimeError if the proxy host:port is not reachable.

    Chrome silently falls back to direct when a proxy is unreachable - its
    internal background requests (telemetry, safe browsing) fail first,
    poisoning the bad-proxy cache, so the user's actual requests use DIRECT
    without any visible error.  Checking upfront gives a fast, clear failure
    instead of a silent privacy bypass.
    """
    parsed = urllib.parse.urlparse(proxy_url)
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        raise RuntimeError(f"Invalid proxy URL (cannot parse host/port): {proxy_url!r}")
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
    except OSError as e:
        raise RuntimeError(f"Proxy {host}:{port} is not reachable: {e}") from e


def _is_proxy_empty(proxy: dict[str, Any] | None) -> bool:
    """Return True if the proxy dict represents an explicit clear/empty proxy."""
    if proxy is None:
        return False
    url = proxy.get("url", "")
    return url == ""


def _is_proxy_valid(proxy: dict[str, Any] | None) -> bool:
    """Return True if the proxy dict contains a valid proxy URL."""
    if proxy is None:
        return False
    url = proxy.get("url", "")
    return bool(url) and "://" in url


def apply_proxy_to_session(driver: WebDriver, proxy: dict[str, Any] | None) -> None:
    """Dynamically update proxy on a running Chrome session via the proxy-manager extension.

    Navigates to the extension's proxy.html page and calls chrome.runtime.sendMessage
    directly to the background service worker, which updates chrome.proxy.settings.set.
    Waits for an acknowledgement from the extension and raises on failure/timeout.
    """
    if proxy is None:
        return

    # Determine whether this is a clear or set operation
    if _is_proxy_empty(proxy):
        payload = {"mode": "direct"}
        logging.debug("Clearing proxy on session via extension")
    elif not _is_proxy_valid(proxy):
        raise RuntimeError(f"Invalid proxy config (schema required, e.g. http:// or socks5://): {proxy!r}")
    else:
        proxy_url = proxy["url"]
        _check_proxy_reachable(proxy_url)
        parsed = urllib.parse.urlparse(proxy_url)
        scheme = parsed.scheme
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            raise RuntimeError(f"Invalid proxy URL (cannot parse host/port): {proxy_url!r}")
        payload = {
            "mode": "fixed_servers",
            "rules": {
                "singleProxy": {
                    "scheme": scheme,
                    "host": host,
                    "port": port,
                },
                "bypassList": ["localhost"],
            },
        }
        username = proxy.get("username")
        password = proxy.get("password")
        if username:
            payload["auth"] = {"username": username, "password": password or ""}
        logging.debug("Applying proxy to session via extension: %s:%d", host, port)

    # Navigate to the extension's proxy.html page so we have a stable
    # extension context where chrome.runtime.sendMessage is available.
    ext_id = getattr(driver, "_proxy_ext_id", None)
    if not ext_id:
        raise RuntimeError("Extension ID not available on driver; cannot apply proxy")
    driver.get("chrome-extension://%s/proxy.html" % ext_id)

    # Smoke check: verify we are on a live extension page by reading chrome.runtime.id
    actual_ext_id = driver.execute_script("return chrome.runtime.id")
    if actual_ext_id != ext_id:
        raise RuntimeError(
            f"Extension ID mismatch: expected {ext_id!r}, got {actual_ext_id!r}. The computed extension ID does not match Chrome's actual extension ID."
        )

    # Directly call chrome.runtime.sendMessage from the extension page
    script = """
        (function() {
            window.__FS_PROXY_RESULT = null;
            chrome.runtime.sendMessage(%s, function(response) {
                window.__FS_PROXY_RESULT = response || {success: false, error: "no response"};
            });
        })();
    """ % json.dumps(payload)
    driver.execute_script(script)

    # Poll for acknowledgement (max 5 seconds)
    deadline = time.time() + 5
    while time.time() < deadline:
        result = driver.execute_script("return window.__FS_PROXY_RESULT")
        if result is not None:
            if result.get("success"):
                return
            raise RuntimeError(f"Proxy extension failed to apply proxy: {result.get('error', 'unknown')}")
        time.sleep(0.05)

    raise RuntimeError("Proxy extension did not acknowledge within timeout")


def _resolve_driver_paths() -> tuple[str | None, str | None]:
    """Return (driver_exe_path, version_main) tuple."""
    global PATCHED_DRIVER_PATH

    if os.path.exists("/app/chromedriver"):
        return "/app/chromedriver", None

    # Local dev: custom chromedriver sits next to the custom chrome binary.
    if _is_custom_chromium():
        chrome_path = get_chrome_exe_path()
        if chrome_path:
            local_cd = os.path.join(os.path.dirname(chrome_path), "chromedriver")
            if os.path.exists(local_cd):
                return local_cd, None

    version_main = get_chrome_major_version()
    driver_exe_path = PATCHED_DRIVER_PATH if PATCHED_DRIVER_PATH is not None else None
    return driver_exe_path, version_main


def _configure_headless(options: "uc.ChromeOptions | None" = None) -> bool:
    """Configure headless mode and return windows_headless flag."""
    if not get_config_headless():
        return False

    if os.name == "nt":
        return True

    start_xvfb_display()
    return False


def _maybe_normalize_user_agent(driver: WebDriver, effective_stealth_mode: str) -> None:
    """Normalize user agent by removing HeadlessChrome token and applying consistent UA metadata."""
    try:
        default_ua = driver.execute_script("return navigator.userAgent")
        if not isinstance(default_ua, str):
            return

        normalized_ua = sanitize_user_agent(default_ua)
        ua_changed = normalized_ua != default_ua

        # Replace reduced version (e.g. Chrome/148.0.0.0) with the full binary version
        full_version = get_chrome_full_version()
        if full_version:
            reduced_pattern = re.compile(r"Chrome/(\d+)\.0\.0\.0")
            if reduced_pattern.search(normalized_ua):
                normalized_ua = reduced_pattern.sub(f"Chrome/{full_version}", normalized_ua)
                ua_changed = True

        if ua_changed or effective_stealth_mode != STEALTH_MODE_OFF:
            apply_user_agent_override(driver, normalized_ua, get_config_accept_language())
            if ua_changed:
                logging.info("Normalized default user-agent by removing HeadlessChrome token.")
    except Exception as e:
        logging.warning("Failed normalizing default user-agent: %s", e)


def _apply_screen_size_override(driver: WebDriver) -> None:
    """Override screen dimensions via CDP to avoid headless 800x600 default."""
    try:
        sw = driver.execute_script("return screen.width")
        sh = driver.execute_script("return screen.height")
        if sw == 800 and sh == 600:
            # Set viewport + screen to 1920x1080 (matches --window-size flag).
            driver.execute_cdp_cmd(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1920,
                    "height": 1080,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                    "screenWidth": 1920,
                    "screenHeight": 1080,
                },
            )
            logging.info("Applied screen size override: 1920x1080 (was 800x600 headless default).")
    except Exception as e:
        logging.debug("Screen size override skipped: %s", e)


def _maybe_apply_stealth(driver: WebDriver, effective_stealth_mode: str) -> None:
    """Apply stealth patches based on mode and Chromium type."""
    # navigator.webdriver is handled natively via Patch 2:
    # [RuntimeEnabled=AutomationControlled] IDL gating + --disable-blink-features=AutomationControlled
    # flag in get_webdriver() makes navigator.webdriver === undefined (property absent).
    # No JS override needed here.

    if effective_stealth_mode == STEALTH_MODE_OFF:
        return

    _apply_screen_size_override(driver)

    try:
        if _is_custom_chromium():
            # C++ flags handle WebGL, languages, isTrusted at binary level.
            # Inject stealth.js (not stealth_fallback.js) via CDP - stealth.js does NOT
            # patch Navigator.prototype.languages so getter-tampering detections
            # (languagesProtoGetterPatched) are avoided.
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": _load_stealth_script(fallback=False)})
            logging.info("Applied custom Chromium stealth (C++ flags + CDP stealth.js, mode=%s).", effective_stealth_mode)
        else:
            _apply_stealth_patches(driver, effective_stealth_mode)
            logging.info("Applied CDP stealth patches (fallback mode=%s).", effective_stealth_mode)
    except Exception as e:
        logging.warning("Failed applying stealth patches: %s", e)


def _save_patched_driver(driver: WebDriver, driver_exe_path: str | None) -> None:
    """Save patched driver path to avoid re-downloads."""
    global PATCHED_DRIVER_PATH

    if driver_exe_path is not None:
        return

    patcher = getattr(driver, "patcher", None)
    if patcher is None:
        return

    PATCHED_DRIVER_PATH = os.path.join(patcher.data_path, patcher.exe_name)
    assert PATCHED_DRIVER_PATH is not None

    if PATCHED_DRIVER_PATH != patcher.executable_path:
        shutil.copy(patcher.executable_path, PATCHED_DRIVER_PATH)


def _build_chrome_env() -> dict[str, str]:
    """Build environment for the Chrome subprocess.

    Accept-Language is controlled via CDP Emulation.setUserAgentOverride
    (acceptLanguage parameter), so no locale manipulation is needed here.
    We simply inherit the parent environment unchanged.
    """
    return os.environ.copy()


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_debug_port(port: int, timeout: int = 30) -> None:
    """Poll until Chrome's remote-debugging port is accepting connections."""
    start = time.time()
    deadline = start + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                elapsed = time.time() - start
                logging.debug("Chrome debug port %d ready after %.1fs", port, elapsed)
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    elapsed = time.time() - start
    raise RuntimeError(f"Chrome debug port {port} did not become ready within {elapsed:.1f}s")


_LAST_CLEANUP_TIME = 0.0
_CLEANUP_LOCK = threading.Lock()


def _cleanup_orphaned_temp_dirs() -> None:
    """Remove leftover Chrome profile and extension temp directories.

    This is safe to call repeatedly (e.g. on every session destroy). It skips
    directories that still have a SingletonLock (Chrome is still running) and
    only removes directories older than a short cutoff to avoid interfering with
    active sessions.  Rate-limited to at most once per minute.
    """
    global _LAST_CLEANUP_TIME
    now = time.time()
    with _CLEANUP_LOCK:
        if now - _LAST_CLEANUP_TIME < 60:
            return
        _LAST_CLEANUP_TIME = now

    tmpdir = tempfile.gettempdir()
    patterns = ["flaresolverr-chrome-*", "fspe-*", "uc-chrome-*"]
    cutoff = now - 300  # 5 minutes old

    for pattern in patterns:
        for path in glob.glob(os.path.join(tmpdir, pattern)):
            try:
                if not os.path.isdir(path):
                    continue
                # Skip if Chrome still holds a lock on this profile
                if os.path.exists(os.path.join(path, "SingletonLock")):
                    continue
                mtime = os.stat(path).st_mtime
                if mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    logging.debug("Cleaned up orphaned temp dir: %s", path)
            except OSError:
                pass


def parse_performance_log_entries(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse raw Selenium performance log entries into CDP {method, params} messages.

    Malformed entries are skipped silently, matching the behavior of sessions.network.
    """
    parsed = []
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            parsed.append(
                {
                    "method": msg.get("method"),
                    "params": msg.get("params"),
                }
            )
        except Exception:  # nosec B110
            logging.debug(f"Skipping malformed performance log entry: {entry}")
    return parsed


def get_performance_log(driver: WebDriver) -> list[dict[str, Any]]:
    """Safely retrieve and parse the browser's performance log.

    Returns an empty list if the backend does not expose performance logs.
    Note: driver.get_log() drains Selenium's internal CDP queue, so later calls
    only see entries produced after this one.
    """
    try:
        logs = driver.get_log("performance")
    except Exception as e:
        error_msg = str(e)
        if "log type" in error_msg.lower() and "not found" in error_msg.lower():
            logging.warning(f"Performance logs not available for this backend: {e}")
            return []
        raise Exception(f"Error getting network logs: {e}") from e
    return parse_performance_log_entries(logs)


def _cdp_headers_to_har(headers: dict[str, Any]) -> list[dict[str, str]]:
    """Convert CDP header dict to HAR header list."""
    har_headers = []
    for name, value in headers.items():
        har_headers.append({"name": str(name), "value": str(value)})
    return har_headers


def _is_internal_chrome_url(url: str) -> bool:
    """Return True for URLs that belong to Chrome internals or extensions."""
    return url.startswith("chrome://") or url.startswith("chrome-extension://")


def performance_logs_to_har(parsed_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert parsed CDP Network events into a minimal HAR 1.2 object."""
    requests_by_id: dict[str, dict[str, Any]] = {}
    responses_by_id: dict[str, dict[str, Any]] = {}
    finished_by_id: dict[str, dict[str, Any]] = {}
    failed_by_id: dict[str, dict[str, Any]] = {}

    for entry in parsed_entries:
        method = entry.get("method")
        params = entry.get("params") or {}
        request_id = params.get("requestId")
        if not request_id:
            continue
        if method == "Network.requestWillBeSent":
            request_url = params.get("request", {}).get("url", "")
            if _is_internal_chrome_url(request_url):
                continue
            requests_by_id[request_id] = params
        elif method == "Network.responseReceived":
            responses_by_id[request_id] = params
        elif method == "Network.loadingFinished":
            finished_by_id[request_id] = params
        elif method == "Network.loadingFailed":
            failed_by_id[request_id] = params

    har_entries = []
    for request_id, request_params in requests_by_id.items():
        request = request_params.get("request") or {}
        response_params = responses_by_id.get(request_id)
        finished_params = finished_by_id.get(request_id)
        failed_params = failed_by_id.get(request_id)

        started_timestamp = request_params.get("wallTime") or request_params.get("timestamp") or 0
        started_datetime = datetime.fromtimestamp(started_timestamp, timezone.utc).isoformat().replace("+00:00", "Z")

        request_ts = request_params.get("timestamp") or 0
        end_ts = (
            (finished_params.get("timestamp") if finished_params else None) or (response_params.get("timestamp") if response_params else None) or request_ts
        )
        total_time = max(0, (end_ts - request_ts) * 1000)

        har_request = {
            "method": request.get("method", "GET"),
            "url": request.get("url", ""),
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": _cdp_headers_to_har(request.get("headers") or {}),
            "queryString": [],
            "headersSize": -1,
            "bodySize": -1,
        }
        post_data = request.get("postData")
        if post_data:
            har_request["postData"] = {
                "mimeType": "application/octet-stream",
                "text": post_data,
            }

        if response_params:
            response = response_params.get("response") or {}
            har_response = {
                "status": response.get("status", 0),
                "statusText": response.get("statusText", ""),
                "httpVersion": response.get("protocol", "HTTP/1.1"),
                "cookies": [],
                "headers": _cdp_headers_to_har(response.get("headers") or {}),
                "redirectURL": response.get("redirectURL", ""),
                "headersSize": -1,
                "bodySize": -1,
                "content": {
                    "size": -1,
                    "compression": 0,
                    "mimeType": response.get("mimeType", "text/plain"),
                },
            }
        elif failed_params:
            har_response = {
                "status": 0,
                "statusText": failed_params.get("errorText", ""),
                "httpVersion": "",
                "cookies": [],
                "headers": [],
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": -1,
                "content": {
                    "size": 0,
                    "compression": 0,
                    "mimeType": "x-unknown",
                },
            }
        else:
            har_response = {
                "status": 0,
                "statusText": "",
                "httpVersion": "",
                "cookies": [],
                "headers": [],
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": -1,
                "content": {
                    "size": 0,
                    "compression": 0,
                    "mimeType": "x-unknown",
                },
            }

        har_entry = {
            "startedDateTime": started_datetime,
            "time": total_time,
            "request": har_request,
            "response": har_response,
            "cache": {},
            "timings": {
                "blocked": -1,
                "dns": -1,
                "connect": -1,
                "ssl": -1,
                "send": 0,
                "wait": total_time,
                "receive": 0,
            },
            "connection": request_id,
        }
        har_entries.append(har_entry)

    return {
        "log": {
            "version": "1.2",
            "creator": {
                "name": "FlareSolverr",
                "version": get_flaresolverr_version() or "unknown",
            },
            "entries": har_entries,
        },
    }


def get_webdriver(proxy: dict[str, Any] | None = None, stealth_mode: str | bool | None = None, logging_prefs: dict[str, str] | None = None) -> WebDriver:
    global PATCHED_DRIVER_PATH

    logging.debug("Launching web browser...")

    effective_stealth_mode = get_config_stealth_mode() if stealth_mode is None else normalize_stealth_mode(stealth_mode)

    options = _build_chrome_options(effective_stealth_mode)
    proxy_ext_dir, proxy_ext_id = _build_stealth_extension_dir()
    options.add_argument("--disable-features=DisableLoadExtensionCommandLineSwitch")
    options.add_argument("--load-extension=%s" % os.path.abspath(proxy_ext_dir))
    windows_headless = _configure_headless()
    driver_exe_path, version_main = _resolve_driver_paths()
    browser_executable_path = get_chrome_exe_path()
    custom_chromium = _is_custom_chromium()

    if browser_executable_path:
        options.binary_location = browser_executable_path

    user_data_dir = None
    try:
        if custom_chromium:
            if not browser_executable_path:
                raise RuntimeError("Custom chromium enabled but no browser executable path found")
            # Custom stealth-patched Chromium: start Chrome manually and
            # connect via debugger address to avoid chromedriver injecting
            # detection-prone default flags like --enable-automation.
            debug_port = _find_free_port()
            user_data_dir = tempfile.mkdtemp(prefix="flaresolverr-chrome-")
            cmd = (
                [browser_executable_path]
                + list(options.arguments)
                + [
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--homepage=about:blank",
                    f"--user-data-dir={user_data_dir}",
                    "--remote-debugging-host=127.0.0.1",
                    f"--remote-debugging-port={debug_port}",
                ]
            )
            if get_config_headless():
                cmd.append("--headless=new")
            chrome_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_build_chrome_env(), start_new_session=True)
            logging.debug("Started custom Chromium manually (PID %d, debug port %d)", chrome_proc.pid, debug_port)

            # Wait for Chrome to open the debug port
            try:
                _wait_for_debug_port(debug_port)
            except RuntimeError:
                alive = chrome_proc.poll() is None
                logging.debug("Chrome process alive=%s, returncode=%s", alive, chrome_proc.poll())
                raise

            opts = ChromeOptions()
            opts.set_capability("unhandledPromptBehavior", "accept")
            opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
            if logging_prefs:
                opts.set_capability("goog:loggingPrefs", logging_prefs)
            if driver_exe_path:
                service = ChromeService(executable_path=driver_exe_path)
            else:
                service = ChromeService()
                logging.warning("Custom chromium chromedriver not found at expected path, using system chromedriver.")
            driver = webdriver.Chrome(options=opts, service=service)

            # Store subprocess so it can be terminated on quit
            driver._chrome_proc = chrome_proc  # type: ignore[attr-defined]
            driver._chrome_user_data_dir = user_data_dir  # type: ignore[attr-defined]
            driver._proxy_ext_dir = proxy_ext_dir  # type: ignore[attr-defined]
            driver._proxy_ext_id = proxy_ext_id  # type: ignore[attr-defined]
            _orig_quit = driver.quit

            def _quit_with_cleanup() -> None:
                try:
                    _orig_quit()
                finally:
                    proc = getattr(driver, "_chrome_proc", None)
                    if proc is not None and proc.poll() is None:
                        try:
                            os.killpg(os.getpgid(proc.pid), 9)
                        except (ProcessLookupError, OSError):
                            proc.kill()
                            proc.wait()
                        time.sleep(0.5)
                    udd = getattr(driver, "_chrome_user_data_dir", None)
                    if udd and os.path.isdir(udd):
                        shutil.rmtree(udd, ignore_errors=True)
                    ext_dir = getattr(driver, "_proxy_ext_dir", None)
                    if ext_dir and os.path.isdir(ext_dir):
                        shutil.rmtree(ext_dir, ignore_errors=True)

            driver.quit = _quit_with_cleanup  # type: ignore[method-assign]
        else:
            # Stock Chromium: use undetected_chromedriver for patcher benefits.
            if logging_prefs:
                options.set_capability("goog:loggingPrefs", logging_prefs)
            driver = uc.Chrome(
                options=options,
                browser_executable_path=browser_executable_path,
                driver_executable_path=driver_exe_path,
                version_main=version_main,
                windows_headless=windows_headless,
                headless=get_config_headless(),
            )
            driver._proxy_ext_dir = proxy_ext_dir  # type: ignore[attr-defined]
            driver._proxy_ext_id = proxy_ext_id  # type: ignore[attr-defined]
            # Wrap quit to clean up temp extension dir
            _orig_uc_quit = driver.quit

            def _uc_quit_with_cleanup() -> None:
                try:
                    _orig_uc_quit()
                finally:
                    ext_dir = getattr(driver, "_proxy_ext_dir", None)
                    if ext_dir and os.path.isdir(ext_dir):
                        shutil.rmtree(ext_dir, ignore_errors=True)

            driver.quit = _uc_quit_with_cleanup  # type: ignore[method-assign]
    except Exception as e:
        logging.error("Error starting Chrome: %s", e)
        # If Chrome failed to start, the proxy extension temp dir and the
        # user data dir were already created but will never be cleaned up by
        # driver.quit(). Remove them now.
        if proxy_ext_dir and os.path.isdir(proxy_ext_dir):
            shutil.rmtree(proxy_ext_dir, ignore_errors=True)
        if user_data_dir and os.path.isdir(user_data_dir):
            shutil.rmtree(user_data_dir, ignore_errors=True)
        raise e

    _maybe_normalize_user_agent(driver, effective_stealth_mode)
    _maybe_apply_stealth(driver, effective_stealth_mode)

    if proxy is not None:
        apply_proxy_to_session(driver, proxy)

    if not custom_chromium:
        _save_patched_driver(driver, driver_exe_path)

    return driver


def get_chrome_exe_path() -> str | None:
    global CHROME_EXE_PATH
    if CHROME_EXE_PATH is not None:
        return CHROME_EXE_PATH
    # linux pyinstaller bundle
    chrome_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome", "chrome")
    if os.path.exists(chrome_path):
        if not os.access(chrome_path, os.X_OK):
            raise Exception(f'Chrome binary "{chrome_path}" is not executable. Please, extract the archive with "tar xzf <file.tar.gz>".')
        CHROME_EXE_PATH = chrome_path
        return CHROME_EXE_PATH
    # windows pyinstaller bundle
    chrome_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome", "chrome.exe")
    if os.path.exists(chrome_path):
        CHROME_EXE_PATH = chrome_path
        return CHROME_EXE_PATH
    # system
    CHROME_EXE_PATH = uc.find_chrome_executable()
    return CHROME_EXE_PATH


def _get_chrome_complete_version() -> str:
    """Fetch the raw Chrome version string (Windows or Linux)."""
    if os.name == "nt":
        try:
            return extract_version_nt_executable(get_chrome_exe_path())
        except Exception:
            try:
                return extract_version_nt_registry()
            except Exception:
                return extract_version_nt_folder()
    else:
        chrome_path = get_chrome_exe_path()
        if chrome_path is None:
            return ""
        process = os.popen(f'"{chrome_path}" --version')
        complete_version = process.read()
        process.close()
        return complete_version


def get_chrome_major_version() -> str:
    global CHROME_MAJOR_VERSION
    if CHROME_MAJOR_VERSION is not None:
        return CHROME_MAJOR_VERSION

    complete_version = _get_chrome_complete_version()
    result = complete_version.split(".")[0].split(" ")[-1]
    CHROME_MAJOR_VERSION = result
    return result


def get_chrome_full_version() -> str:
    global CHROME_FULL_VERSION
    if CHROME_FULL_VERSION is not None:
        return CHROME_FULL_VERSION

    complete_version = _get_chrome_complete_version()
    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", complete_version)
    result = match.group(1) if match else ""
    CHROME_FULL_VERSION = result
    return result


def extract_version_nt_executable(exe_path: str) -> str:
    if pefile is None:
        raise RuntimeError("pefile is required to extract version from Windows executables")
    pe = pefile.PE(exe_path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    return pe.FileInfo[0][0].StringTable[0].entries[b"FileVersion"].decode("utf-8")


def extract_version_nt_registry() -> str:
    stream = os.popen('reg query "HKLM\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Google Chrome"')
    output = stream.read()
    google_version = ""
    for letter in output[output.rindex("DisplayVersion    REG_SZ") + 24 :]:
        if letter != "\n":
            google_version += letter
        else:
            break
    return google_version.strip()


def extract_version_nt_folder() -> str:
    # Check if the Chrome folder exists in the x32 or x64 Program Files folders.
    for i in range(2):
        path = "C:\\Program Files" + (" (x86)" if i else "") + "\\Google\\Chrome\\Application"
        if os.path.isdir(path):
            paths = [f.path for f in os.scandir(path) if f.is_dir()]
            for path in paths:
                filename = os.path.basename(path)
                pattern = r"\d+\.\d+\.\d+\.\d+"
                match = re.search(pattern, filename)
                if match and match.group():
                    # Found a Chrome version.
                    return match.group(0)
    return ""


def wait_for_page_stable(driver: WebDriver, timeout: float = 15.0, poll: float = 0.5) -> None:
    """Wait until document.readyState is 'complete' and the execution context is stable.

    After a navigation triggered by a challenge resolver the new page may not be
    ready to receive JavaScript calls for several seconds.  Plain retries on
    individual driver reads burn time waiting for ChromeDriver's own command
    timeout (~2-3 s per attempt).  This function uses a tight poll loop so we
    detect readiness as soon as it becomes available.
    """
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        try:
            state = driver.execute_script("return document.readyState")
            if state == "complete":
                return
        except WebDriverException as exc:
            msg = str(exc).lower()
            if "no such execution context" not in msg and "aborted by navigation" not in msg:
                raise
        _time.sleep(poll)
    logging.debug("wait_for_page_stable: timed out after %.0fs, proceeding anyway", timeout)


def retry_driver_read(read_fn, retries: int = 10, delay: float = 0.5):
    """Retry a driver property read that may transiently fail during navigation."""
    last_exc: WebDriverException | None = None
    for attempt in range(1, retries + 1):
        try:
            result = read_fn()
            if attempt > 1:
                logging.debug("Driver read succeeded after %d retries", attempt - 1)
            return result
        except WebDriverException as exc:
            msg = str(exc).lower()
            if "no such execution context" in msg or "aborted by navigation" in msg:
                logging.debug("Driver read failed transiently (%s), retry %d/%d", exc, attempt, retries)
                last_exc = exc
                time.sleep(delay)
                continue
            raise
    if last_exc is None:
        raise RuntimeError("retry_driver_read exhausted retries without a captured exception")
    raise last_exc


def _fetch_user_agent(driver: WebDriver) -> str:
    """Execute JS to get navigator.userAgent and validate it."""
    user_agent_value = driver.execute_script("return navigator.userAgent")
    if not isinstance(user_agent_value, str):
        raise Exception("Error getting browser User-Agent. The returned value is not a string.")
    return user_agent_value


def get_user_agent(driver=None) -> str:
    global USER_AGENT
    if driver is not None:
        try:
            return re.sub("HEADLESS", "", _fetch_user_agent(driver), flags=re.IGNORECASE)
        except Exception as e:
            raise Exception("Error getting browser User-Agent. " + str(e))

    if USER_AGENT is not None:
        return USER_AGENT

    try:
        if driver is None:
            driver = get_webdriver()
        raw_ua = _fetch_user_agent(driver)
        # Fix for Chrome 117 | https://github.com/FlareSolverr/FlareSolverr/issues/910
        USER_AGENT = re.sub("HEADLESS", "", raw_ua, flags=re.IGNORECASE)
        # Replace reduced version (e.g. Chrome/148.0.0.0) with the full binary version
        full_version = get_chrome_full_version()
        if full_version:
            USER_AGENT = re.sub(r"Chrome/(\d+)\.0\.0\.0", f"Chrome/{full_version}", USER_AGENT)
        assert USER_AGENT is not None
        return USER_AGENT
    except Exception as e:
        raise Exception("Error getting browser User-Agent. " + str(e))
    finally:
        if driver is not None:
            if PLATFORM_VERSION == "nt":
                driver.close()
            driver.quit()


def start_xvfb_display() -> None:
    global XVFB_DISPLAY
    if XVFB_DISPLAY is None:
        if Xvfb is None:
            raise RuntimeError("xvfbwrapper is required to start a virtual display")
        width = int(os.environ.get("XVFB_WIDTH", "1920"))
        height = int(os.environ.get("XVFB_HEIGHT", "1080"))
        colordepth = int(os.environ.get("XVFB_COLORDEPTH", "24"))
        XVFB_DISPLAY = Xvfb(width=width, height=height, colordepth=colordepth)
        XVFB_DISPLAY.start()


def object_to_dict(_object: Any) -> dict[str, Any]:
    json_dict = json.loads(json.dumps(_object, default=lambda o: o.__dict__))
    # remove hidden fields
    return {k: v for k, v in json_dict.items() if not k.startswith("__")}


def _random_delay(min_sec: float, max_sec: float) -> float:
    """Generate a random delay with slight gaussian distribution for natural feel."""
    mean = (min_sec + max_sec) / 2
    std_dev = (max_sec - min_sec) / 6
    delay = random.gauss(mean, std_dev)
    return max(min_sec, min(max_sec, delay))


def _generate_bezier_curve(start: tuple[float, float], end: tuple[float, float], control_points: int = 1) -> list[tuple[float, float]]:
    """Generate points along a bezier curve for natural mouse movement."""
    points = [start]

    for i in range(control_points):
        t = (i + 1) / (control_points + 1)
        base_x = start[0] + (end[0] - start[0]) * t
        base_y = start[1] + (end[1] - start[1]) * t
        deviation = max(abs(end[0] - start[0]), abs(end[1] - start[1])) * random.uniform(0.1, 0.3)  # nosec B311
        ctrl_x = base_x + deviation * random.gauss(0, 0.5)
        ctrl_y = base_y + deviation * random.gauss(0, 0.5)
        points.append((ctrl_x, ctrl_y))

    points.append(end)

    num_steps = random.randint(15, 25)  # nosec B311
    curve_points = []

    for t in [i / num_steps for i in range(num_steps + 1)]:
        temp_points = points.copy()
        while len(temp_points) > 1:
            new_points = []
            for j in range(len(temp_points) - 1):
                x = temp_points[j][0] + (temp_points[j + 1][0] - temp_points[j][0]) * t
                y = temp_points[j][1] + (temp_points[j + 1][1] - temp_points[j][1]) * t
                new_points.append((x, y))
            temp_points = new_points
        curve_points.append(temp_points[0])

    return curve_points


def _human_like_click(driver: WebDriver, element) -> None:
    """Perform a human-like mouse movement and click with bezier curves and randomness."""
    location = element.location
    size = element.size
    element_center_x = location["x"] + size["width"] / 2
    element_center_y = location["y"] + size["height"] / 2

    offset_x = random.gauss(0, size["width"] / 8)
    offset_y = random.gauss(0, size["height"] / 8)
    target_x = element_center_x + offset_x
    target_y = element_center_y + offset_y

    viewport_width = driver.execute_script("return window.innerWidth")
    viewport_height = driver.execute_script("return window.innerHeight")

    start_edge = random.choice(["top", "bottom", "left", "right"])  # nosec B311
    if start_edge == "top":
        start_x = random.uniform(0, viewport_width)  # nosec B311
        start_y = random.uniform(0, 100)  # nosec B311
    elif start_edge == "bottom":
        start_x = random.uniform(0, viewport_width)  # nosec B311
        start_y = random.uniform(viewport_height - 100, viewport_height)  # nosec B311
    elif start_edge == "left":
        start_x = random.uniform(0, 100)  # nosec B311
        start_y = random.uniform(0, viewport_height)  # nosec B311
    else:
        start_x = random.uniform(viewport_width - 100, viewport_width)  # nosec B311
        start_y = random.uniform(0, viewport_height)  # nosec B311

    points = _generate_bezier_curve((start_x, start_y), (target_x, target_y), control_points=random.randint(1, 2))  # nosec B311

    actions = ActionChains(driver)
    first_x, first_y = points[0]
    anchor_dx = round(first_x - element_center_x)
    anchor_dy = round(first_y - element_center_y)
    actions.move_to_element_with_offset(element, anchor_dx, anchor_dy)
    actions.pause(_random_delay(0.02, 0.06))

    actual_x = round(element_center_x) + anchor_dx
    actual_y = round(element_center_y) + anchor_dy
    prev_x = float(actual_x)
    prev_y = float(actual_y)
    acc_x = 0.0
    acc_y = 0.0

    for i, (x, y) in enumerate(points[1:], start=1):
        desired_dx = (x - prev_x) + acc_x
        desired_dy = (y - prev_y) + acc_y
        int_dx = round(desired_dx)
        int_dy = round(desired_dy)
        acc_x = desired_dx - int_dx
        acc_y = desired_dy - int_dy
        actions.move_by_offset(int_dx, int_dy)
        actual_x += int_dx
        actual_y += int_dy
        prev_x, prev_y = x, y

        progress = i / len(points)
        delay = 0.01 + 0.03 * (1 - abs(progress - 0.5) * 2)
        actions.pause(delay)

    target_int_x = round(target_x)
    target_int_y = round(target_y)
    if actual_x != target_int_x or actual_y != target_int_y:
        fix_dx = target_int_x - actual_x
        fix_dy = target_int_y - actual_y
        actions.move_by_offset(fix_dx, fix_dy)
        actual_x = target_int_x
        actual_y = target_int_y

    actions.pause(_random_delay(0.05, 0.15))
    actions.click_and_hold()
    actions.move_by_offset(int(random.gauss(0, 1)), int(random.gauss(0, 1)))
    actions.pause(_random_delay(0.03, 0.08))
    actions.release()

    actions.perform()

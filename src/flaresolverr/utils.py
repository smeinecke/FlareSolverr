import glob
import hashlib
import json
import logging

logger = logging.getLogger(__name__)
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
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import Any

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
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains

from flaresolverr import undetected_chromedriver as uc  # type: ignore[import-untyped]

FLARESOLVERR_VERSION: str | None = None
PLATFORM_VERSION: str | None = None
CHROME_EXE_PATH: str | None = os.environ.get("CHROME_EXE_PATH") or None
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


_CUSTOM_CHROMIUM_MANIFEST: dict[str, Any] | None = None


def _get_custom_chromium_manifest() -> dict[str, Any]:
    """Read the .stealth-manifest.json shipped next to the custom binary.

    The self-hosted build writes this file recording the Chromium revision,
    patch IDs, GN args and binary hashes. Returns {} when absent (older builds
    or non-custom binaries). Result is cached.
    """
    global _CUSTOM_CHROMIUM_MANIFEST
    if _CUSTOM_CHROMIUM_MANIFEST is not None:
        return _CUSTOM_CHROMIUM_MANIFEST
    _CUSTOM_CHROMIUM_MANIFEST = {}
    # Prefer the manifest adjacent to the binary actually being launched;
    # a stale /opt/chromium copy must not gate flags for a different binary.
    chrome_dir = os.path.dirname(get_chrome_exe_path() or "")
    candidates = [os.path.join(chrome_dir, ".stealth-manifest.json")] if chrome_dir else []
    candidates.append("/opt/chromium/.stealth-manifest.json")
    for path in candidates:
        try:
            with open(path) as f:
                manifest = json.load(f)
            if isinstance(manifest, dict):
                _CUSTOM_CHROMIUM_MANIFEST = manifest
                break
        except (OSError, json.JSONDecodeError):
            continue
    return _CUSTOM_CHROMIUM_MANIFEST


def _custom_chromium_has_patch(patch_id: str) -> bool:
    """True when the custom binary's build manifest lists the given patch."""
    if not _is_custom_chromium():
        return False
    patches = _get_custom_chromium_manifest().get("patches")
    return isinstance(patches, list) and patch_id in patches


def get_config_log_html() -> bool:
    return os.environ.get("LOG_HTML", "false").lower() == "true"


def get_config_headless() -> bool:
    return os.environ.get("HEADLESS", "true").lower() == "true"


def get_config_disable_media() -> bool:
    return os.environ.get("DISABLE_MEDIA", "false").lower() == "true"


def get_config_browser_wait_timeout() -> int:
    return int(os.environ.get("BROWSER_WAIT_TIMEOUT", "1"))


def get_config_challenge_probe_grace() -> float:
    """Seconds before the Cloudflare resolver starts probing/clicking.

    The probe forces layout and walks the challenge DOM, which measurably
    stalls Turnstile auto-verification. Auto-verifying challenges pass in
    ~4s undisturbed, so probing starts only after this grace window.
    """
    return float(os.environ.get("CHALLENGE_PROBE_GRACE", "12"))


def get_config_stealth_omit_flags() -> set[str]:
    """Parse STEALTH_OMIT_FLAGS: comma-separated --stealth-* switch names to omit.

    Runtime ablation hook for the switch-gated native patches (e.g.
    "stealth-viewport-size,stealth-no-media-devices"). Names are compared
    without leading dashes.
    """
    raw = os.environ.get("STEALTH_OMIT_FLAGS", "")
    return {token.strip().lstrip("-") for token in raw.split(",") if token.strip()}


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

    For custom Chromium builds *without* the native-ua patch we intentionally
    do not set userAgentMetadata: the --user-agent command-line switch already
    gives all contexts (main, workers, shared workers) a coherent UA, and CDP
    metadata would be suppressed by it anyway. With the native-ua patch
    (--stealth-native-ua instead of --user-agent) we DO set metadata, since
    nothing else overrides it and userAgentData must match the requested UA.

    Known limitation: SharedWorkers do not receive the CDP override on any
    path, so a session-level UA override is not fully coherent there.
    """
    accept_lang = accept_language if accept_language is not None else get_config_accept_language()
    params: dict[str, Any] = {
        "userAgent": user_agent,
        "acceptLanguage": accept_lang,
    }

    if not _is_custom_chromium() or _custom_chromium_has_patch("native-ua"):
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

        params["userAgentMetadata"] = {
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
        }

    driver.execute_cdp_cmd("Emulation.setUserAgentOverride", params)


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
    except (PackageNotFoundError, ValueError) as e:
        logger.debug("Could not read installed version: %s", e)

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


def _limit_cpu_affinity() -> None:
    """Restrict the Chrome process to a plausible consumer CPU count.

    navigator.hardwareConcurrency reflects the number of online CPUs visible
    to the renderer process. By setting the child process affinity to the
    first 16 logical CPUs we keep the reported value <= 16 on servers with
    many cores (32, 64, ...) without patching the browser binary. This is a
    process-level, native configuration that propagates to Web Workers and
    SharedWorkers because they inherit the renderer's affinity mask.
    """
    try:
        total = os.cpu_count()
        if total and total > 16:
            os.sched_setaffinity(0, set(range(16)))
    except (OSError, AttributeError):
        pass


def _build_chrome_options(effective_stealth_mode: str, load_extension: bool = False) -> ChromeOptions:
    """Build and configure ChromeOptions based on settings.

    `load_extension` controls whether the DisableLoadExtensionCommandLineSwitch
    feature is disabled (required for --load-extension to work on newer Chrome).
    """
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
    custom = _is_custom_chromium()

    # Chrome treats repeated --disable-features switches as replace-not-merge:
    # only the last occurrence takes effect. Collect every intended feature in
    # one list and emit a single switch at the end.
    disabled_features: list[str] = []

    if not get_config_chrome_disable_optimizations():
        options.add_argument("--renderer-process-limit=1")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-background-networking")
        options.add_argument("--enable-features=NetworkServiceInProcess")
        options.add_argument("--disable-component-update")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-pings")
        disabled_features += [
            "MediaRouter",
            "GlobalMediaControls",
            "AutofillServerCommunication",
            "OptimizationHints",
            "Translate",
        ]

    for extra_flag in get_config_chrome_extra_flags():
        options.add_argument(extra_flag)

    minimal_fingerprint = get_config_minimal_fingerprint()

    if get_config_disable_quic():
        options.add_argument("--disable-quic")
        options.add_argument("--disable-http3")

    if not minimal_fingerprint:
        disabled_features += ["StrictOriginIsolation", "IsolateOrigins"]
        options.add_argument("--disable-site-isolation-trials")

    if os.environ.get("DISABLE_WEB_SECURITY", "false").lower() == "true":
        options.add_argument("--disable-web-security")
        disabled_features.append("BlockInsecurePrivateNetworkRequests")

    if platform.machine().startswith(("arm", "aarch")):
        options.add_argument("--disable-gpu-sandbox")

    # In --headless=new / ozone-platform=headless the GPU process is disabled
    # regardless of --use-gl, so no GL context is opened. The old
    # --use-gl=swiftshader flag is stale; omit it to keep the command line
    # honest and avoid the false impression that SwiftShader is the backend.

    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    disabled_features.append("LocalNetworkAccessChecks")

    if load_extension:
        # DisableLoadExtensionCommandLineSwitch is enabled by default on newer
        # Chrome; disabling it keeps --load-extension working.
        disabled_features.append("DisableLoadExtensionCommandLineSwitch")

    # Disable the AutomationControlled blink feature so navigator.webdriver is
    # absent (undefined) rather than true. Needed for stock Chromium and for
    # custom binaries built with the webdriver-idl ablation variant — the
    # default webdriver-false build keeps the property present, so the flag
    # must NOT be passed there.
    if (custom or not minimal_fingerprint) and not _custom_chromium_has_patch("webdriver-false"):
        options.add_argument("--disable-blink-features=AutomationControlled")

    omit_flags = get_config_stealth_omit_flags()

    # --stealth-native-ua is only useful when the binary carries Patch 6b
    # (advertised via the build manifest) and stealth is active. When it is
    # NOT active, fall back to the legacy --user-agent switch so headless mode
    # never exposes a HeadlessChrome UA.
    native_ua_active = (
        custom and effective_stealth_mode != STEALTH_MODE_OFF and "stealth-native-ua" not in omit_flags and _custom_chromium_has_patch("native-ua")
    )

    if custom:
        if not native_ua_active:
            # Legacy fallback for binaries without Patch 6b: --user-agent sets a
            # normalized UA for *all* browsing contexts (main, workers, shared
            # workers) so UA stays coherent — at the cost of suppressing
            # high-entropy UA client hints (GetUserAgentMetadata early-return).
            full_version = get_chrome_full_version()
            if not full_version:
                full_version = f"{get_chrome_major_version()}.0.0.0"
            machine = platform.machine()
            user_agent = f"Mozilla/5.0 (X11; Linux {machine}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{full_version} Safari/537.36"
            options.add_argument(f"--user-agent={user_agent}")
        # Native accept-language for HTTP headers; navigator.languages is still
        # handled by --stealth-navigator-languages at the binary level.
        options.add_argument(f"--accept-lang={get_config_accept_language()}")
        # The --lang switch sets the ICU default locale in renderer processes
        # (Patch 10 in apply.py), keeping Intl.* defaults aligned with
        # navigator.language across all execution contexts.
        options.add_argument(f"--lang={get_config_accept_language().split(',')[0]}")

    if effective_stealth_mode != STEALTH_MODE_OFF and custom:
        # C++ flags; no JavaScript replacement needed.
        # --enable-trusted-synthetic-events was removed: synthetic events must
        # not be reported as trusted globally.
        # The WebGL vendor/renderer spoof (Patch 3) has been removed as an
        # ablation; the natural ANGLE/GPU identity is exposed instead.
        # The value of this switch is the underlying navigator.languages state
        # consumed by all execution contexts. The C++ patch in apply.py parses
        # the comma-separated list so Window/Worker/SharedWorker stay coherent.
        stealth_switches = [
            f"--stealth-navigator-languages={get_config_accept_language()}",
            "--stealth-viewport-size",
            "--stealth-no-media-devices",
        ]
        if native_ua_active:
            stealth_switches.append("--stealth-native-ua")
        for switch in stealth_switches:
            name = switch.lstrip("-").split("=", 1)[0]
            if name not in omit_flags:
                options.add_argument(switch)
            else:
                logger.debug("STEALTH_OMIT_FLAGS: omitting %s", switch)
        logger.debug("Applied custom Chromium stealth flags.")

    if disabled_features:
        options.add_argument("--disable-features=" + ",".join(disabled_features))

    return options


def _redact_url_credentials(url: str) -> str:
    """Replace URL userinfo (scheme://user:pass@host) with a redacted marker."""
    return re.sub(r"(://)[^/@]+@", r"\1***:***@", url)


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
        raise RuntimeError(f"Invalid proxy URL (cannot parse host/port): {_redact_url_credentials(proxy_url)!r}")
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
        logger.debug("Clearing proxy on session via extension")
    elif not _is_proxy_valid(proxy):
        safe_proxy = {k: ("***" if k == "password" else _redact_url_credentials(v) if k == "url" and isinstance(v, str) else v) for k, v in proxy.items()}
        raise RuntimeError(f"Invalid proxy config (schema required, e.g. http:// or socks5://): {safe_proxy!r}")
    else:
        proxy_url = proxy["url"]
        _check_proxy_reachable(proxy_url)
        parsed = urllib.parse.urlparse(proxy_url)
        scheme = parsed.scheme
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            raise RuntimeError(f"Invalid proxy URL (cannot parse host/port): {_redact_url_credentials(proxy_url)!r}")
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
        # Credentials embedded in the URL (scheme://user:pass@host:port) apply
        # when no explicit username/password fields are set. urlparse returns
        # them percent-encoded, so decode before sending to the extension.
        if not username and parsed.username:
            username = urllib.parse.unquote(parsed.username)
            password = urllib.parse.unquote(parsed.password or "")
        if username:
            payload["auth"] = {"username": username, "password": password or ""}
        logger.debug("Applying proxy to session via extension: %s:%d", host, port)

    # Navigate to the extension's proxy.html page so we have a stable
    # extension context where chrome.runtime.sendMessage is available.
    ext_id = getattr(driver, "_proxy_ext_id", None)
    if not ext_id:
        raise RuntimeError("Extension ID not available on driver; cannot apply proxy")
    driver.get(f"chrome-extension://{ext_id}/proxy.html")

    # Smoke check: verify we are on a live extension page by reading chrome.runtime.id
    actual_ext_id = driver.execute_script("return chrome.runtime.id")
    if actual_ext_id != ext_id:
        raise RuntimeError(
            f"Extension ID mismatch: expected {ext_id!r}, got {actual_ext_id!r}. The computed extension ID does not match Chrome's actual extension ID."
        )

    # Directly call chrome.runtime.sendMessage from the extension page
    script = f"""
        (function() {{
            window.__FS_PROXY_RESULT = null;
            chrome.runtime.sendMessage({json.dumps(payload)}, function(response) {{
                window.__FS_PROXY_RESULT = response || {{success: false, error: "no response"}};
            }});
        }})();
    """
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
    # Custom Chromium handles the UA natively: builds with Patch 6b use
    # --stealth-native-ua (no Headless token, full high-entropy client hints),
    # older builds fall back to --user-agent for cross-context coherence.
    # Either way no runtime override is needed for custom builds.
    if _is_custom_chromium():
        return

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
                logger.info("Normalized default user-agent by removing HeadlessChrome token.")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed normalizing default user-agent: %s", e)


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
            logger.info("Applied screen size override: 1920x1080 (was 800x600 headless default).")
    except Exception as e:  # noqa: BLE001
        logger.debug("Screen size override skipped: %s", e)


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
            # Native Chromium handles WebGL, languages, identity and timing signals.
            # No JavaScript injection is used for the custom build; the empty
            # stealth.js was removed from the CDP injection path.
            logger.info("Custom Chromium stealth flags active (mode=%s).", effective_stealth_mode)
        else:
            _apply_stealth_patches(driver, effective_stealth_mode)
            logger.info("Applied CDP stealth patches (fallback mode=%s).", effective_stealth_mode)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed applying stealth patches: %s", e)


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
                logger.debug("Chrome debug port %d ready after %.1fs", port, elapsed)
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
                    logger.debug("Cleaned up orphaned temp dir: %s", path)
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
        except Exception:  # nosec B110  # noqa: BLE001
            logger.debug(f"Skipping malformed performance log entry: {entry}")
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
            logger.warning(f"Performance logs not available for this backend: {e}")
            return []
        raise RuntimeError(f"Error getting network logs: {e}") from e
    return parse_performance_log_entries(logs)


def _header_lookup(headers: dict[str, Any], name: str) -> Any:
    """Case-insensitive lookup in a CDP header dict."""
    name_lower = name.lower()
    for key, value in headers.items():
        if str(key).lower() == name_lower:
            return value
    return None


def _get_main_frame_id(driver: WebDriver) -> str | None:
    """Return the top-level frame id via CDP, or None if unavailable."""
    try:
        tree = driver.execute_cdp_cmd("Page.getFrameTree", {})  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - mocks and non-CDP drivers
        return None
    return ((tree or {}).get("frameTree") or {}).get("frame", {}).get("id")


def _select_document_chain(doc_chains: list[dict[str, Any]], root_frame_ids: list[str], driver: WebDriver) -> tuple[dict[str, Any], bool]:
    """Pick the Document chain belonging to the top-level frame.

    Returns (chain, identified). identified=False means the last-resort
    fallback was used — the chain may be an iframe navigation and callers must
    not treat it as authoritative top-level evidence.
    """
    # Frame ids come from Page.getFrameTree (chromedriver) or
    # Page.frameNavigated perf-log events.
    main_frame_id = _get_main_frame_id(driver) or (root_frame_ids[-1] if root_frame_ids else None)
    chain = None
    if main_frame_id:
        chain = next((c for c in reversed(doc_chains) if c["frameId"] == main_frame_id), None)
    if chain is None:
        # Fallback: the main-frame document is the one matching the final URL.
        current_url = getattr(driver, "current_url", None)
        if current_url:
            chain = next((c for c in reversed(doc_chains) if c["url"] == current_url), None)
    if chain is None:
        return doc_chains[-1], False
    return chain, True


def get_document_response_evidence(driver: WebDriver, max_failed_resources: int = 10, entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Summarize the most recent top-level document exchange.

    Returns a dict with the final document url/status/mimeType/protocol, the
    redirect chain, filtered response headers, Cloudflare response markers
    (cf-mitigated, cf-ray), a navigation error (if the document load failed),
    and a bounded list of failed sub-resources. Returns an empty dict when no
    document request is found or performance logs are unavailable.

    `entries` may carry an already-drained performance log so callers can
    share one drain between evidence and HAR collection; when omitted the log
    is drained here. Note: draining empties the queue, so call it only when
    the exchange is complete (failure paths, postDataRaw completion).

    `mainFrameIdentified` reports whether the top-level frame was positively
    identified; when False the result fell back to the latest Document chain,
    which can be an iframe navigation — treat it as a hint, not authoritative.
    """
    if entries is None:
        entries = get_performance_log(driver)
    if not entries:
        return {}

    url_by_request_id: dict[str, str] = {}
    responses_by_request_id: dict[str, dict[str, Any]] = {}
    failed_by_request_id: dict[str, str] = {}
    # Every Document request chain, in order. Iframe navigations are also
    # type=Document, so the "latest Document" heuristic alone can silently
    # replace the top-level 403/Ray ID with a challenge iframe's 200.
    doc_chains: list[dict[str, Any]] = []
    doc_chain_by_id: dict[str, dict[str, Any]] = {}
    root_frame_ids: list[str] = []

    for entry in entries:
        method = entry.get("method")
        params = entry.get("params") or {}
        if method == "Page.frameNavigated":
            frame = params.get("frame") or {}
            if frame.get("id") and "parentId" not in frame:
                root_frame_ids.append(frame["id"])
            continue
        request_id = params.get("requestId")
        if not request_id:
            continue
        if method == "Network.requestWillBeSent":
            request_url = (params.get("request") or {}).get("url", "")
            url_by_request_id[request_id] = request_url
            if params.get("type") != "Document":
                continue
            redirect_response = params.get("redirectResponse")
            chain = doc_chain_by_id.get(request_id)
            if chain is not None and redirect_response:
                # Same requestId carrying a redirectResponse = next redirect hop.
                chain["redirects"].append(
                    {
                        "url": redirect_response.get("url"),
                        "status": redirect_response.get("status"),
                    }
                )
                chain["url"] = request_url or chain["url"]
            else:
                # A new requestId for a Document request = new navigation.
                chain = {
                    "requestId": request_id,
                    "frameId": params.get("frameId"),
                    "url": request_url,
                    "redirects": [],
                }
                doc_chain_by_id[request_id] = chain
                doc_chains.append(chain)
        elif method == "Network.responseReceived":
            responses_by_request_id[request_id] = params.get("response") or {}
        elif method == "Network.loadingFailed":
            error_text = params.get("errorText")
            if error_text:
                failed_by_request_id[request_id] = error_text

    if not doc_chains:
        return {}

    chain, identified = _select_document_chain(doc_chains, root_frame_ids, driver)

    doc_request_id = chain["requestId"]
    doc_url = chain["url"]
    redirects = chain["redirects"]

    response = responses_by_request_id.get(doc_request_id) or {}
    headers = response.get("headers") or {}
    nav_error = failed_by_request_id.pop(doc_request_id, None)
    failed_resources = [{"url": url_by_request_id.get(rid, ""), "error": err} for rid, err in list(failed_by_request_id.items())[:max_failed_resources]]

    return {
        "url": response.get("url") or doc_url,
        "status": response.get("status"),
        "statusText": response.get("statusText"),
        "mimeType": response.get("mimeType"),
        "protocol": response.get("protocol"),
        # Cookie values stay out of the evidence record; they are already
        # exposed via solution.cookies.
        "headers": {str(k): v for k, v in headers.items() if str(k).lower() != "set-cookie"},
        "cfMitigated": _header_lookup(headers, "cf-mitigated"),
        "cfRay": _header_lookup(headers, "cf-ray"),
        "redirects": redirects,
        "navError": nav_error,
        "failedResources": failed_resources,
        "mainFrameIdentified": identified,
    }


def collect_failure_evidence(driver: WebDriver, stealth_mode: str | None = None) -> dict[str, Any]:
    """Collect a bounded diagnostic snapshot of the browser after a failed request.

    Never raises; every field is best-effort. Sensitive values (cookie values,
    POST bodies) are deliberately excluded — only cookie names, domains and
    expiry are recorded.
    """
    evidence: dict[str, Any] = {}

    def _safe(fn, default=None):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return default

    evidence["currentUrl"] = _safe(lambda: driver.current_url)
    evidence["pageTitle"] = _safe(lambda: driver.title)
    evidence["response"] = _safe(lambda: get_document_response_evidence(driver), {})

    cookies = _safe(driver.get_cookies, []) or []
    evidence["cookies"] = [{"name": c.get("name"), "domain": c.get("domain"), "expiry": c.get("expiry")} for c in cookies if isinstance(c, dict)]
    evidence["cfClearancePresent"] = any(c.get("name") == "cf_clearance" for c in cookies if isinstance(c, dict))

    caps = _safe(lambda: driver.capabilities, {}) or {}
    chrome_caps = caps.get("chrome") or {}
    evidence["browser"] = {
        "name": caps.get("browserName"),
        "version": caps.get("browserVersion"),
        "chromedriverVersion": chrome_caps.get("chromedriverVersion"),
    }
    evidence["userAgent"] = _safe(lambda: get_user_agent(driver))
    evidence["launchArgs"] = getattr(driver, "_flaresolverr_launch_args", None)
    evidence["config"] = {
        # The effective per-request/session mode when the caller knows it;
        # env config can disagree with a request-level stealthMode override.
        "stealthMode": stealth_mode or get_config_stealth_mode(),
        "headless": get_config_headless(),
        "customChromium": _is_custom_chromium(),
    }
    evidence["screenshotBase64"] = _safe(driver.get_screenshot_as_base64)
    return evidence


def _cdp_headers_to_har(headers: dict[str, Any]) -> list[dict[str, str]]:
    """Convert CDP header dict to HAR header list."""
    har_headers = []
    for name, value in headers.items():
        har_headers.append({"name": str(name), "value": str(value)})
    return har_headers


def _is_internal_chrome_url(url: str) -> bool:
    """Return True for URLs that belong to Chrome internals or extensions."""
    return url.startswith(("chrome://", "chrome-extension://"))


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
        started_datetime = datetime.fromtimestamp(started_timestamp, UTC).isoformat().replace("+00:00", "Z")

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


def get_webdriver(
    proxy: dict[str, Any] | None = None, stealth_mode: str | bool | None = None, logging_prefs: dict[str, str] | None = None, for_session: bool = False
) -> WebDriver:
    logger.debug("Launching web browser...")

    effective_stealth_mode = get_config_stealth_mode() if stealth_mode is None else normalize_stealth_mode(stealth_mode)
    # Performance logging is enabled for every driver (not just sessions /
    # recordHar) so failure paths can inspect the actual HTTP exchange.
    if logging_prefs is None:
        logging_prefs = {"performance": "ALL"}
    user_data_dir: str | None = None
    proxy_ext_dir: str | None = None

    # The unpacked proxy-manager extension is only needed when a proxy is
    # configured now (proxy auth / settings) or might be assigned later
    # (sessions support dynamic proxy updates via apply_proxy_to_session).
    # One-off drivers without a proxy launch without any extension.
    use_extension = for_session or _is_proxy_valid(proxy)

    try:
        proxy_ext_id = None
        if use_extension:
            proxy_ext_dir, proxy_ext_id = _build_stealth_extension_dir()
        options = _build_chrome_options(effective_stealth_mode, load_extension=use_extension)
        if proxy_ext_dir:
            options.add_argument(f"--load-extension={os.path.abspath(proxy_ext_dir)}")
        windows_headless = _configure_headless()
        driver_exe_path, version_main = _resolve_driver_paths()
        browser_executable_path = get_chrome_exe_path()
        custom_chromium = _is_custom_chromium()

        if browser_executable_path:
            options.binary_location = browser_executable_path

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
            cpu_count = os.cpu_count()
            preexec = _limit_cpu_affinity if (os.name == "posix" and cpu_count is not None and cpu_count > 16) else None
            chrome_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_build_chrome_env(),
                start_new_session=True,
                preexec_fn=preexec,  # noqa: PLW1509
            )
            logger.debug("Started custom Chromium manually (PID %d, debug port %d)", chrome_proc.pid, debug_port)

            # Wait for Chrome to open the debug port
            try:
                _wait_for_debug_port(debug_port)
            except RuntimeError:
                alive = chrome_proc.poll() is None
                logger.debug("Chrome process alive=%s, returncode=%s", alive, chrome_proc.poll())
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
                logger.warning("Custom chromium chromedriver not found at expected path, using system chromedriver.")
            driver = webdriver.Chrome(options=opts, service=service)
            driver._flaresolverr_launch_args = list(cmd)  # type: ignore[attr-defined]

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
            driver._flaresolverr_launch_args = list(options.arguments)  # type: ignore[attr-defined]
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
        logger.error("Error starting Chrome: %s", e)
        # If Chrome failed to start, the proxy extension temp dir and the
        # user data dir were already created but will never be cleaned up by
        # driver.quit(). Remove them now.
        if proxy_ext_dir and os.path.isdir(proxy_ext_dir):
            shutil.rmtree(proxy_ext_dir, ignore_errors=True)
        if user_data_dir and os.path.isdir(user_data_dir):
            shutil.rmtree(user_data_dir, ignore_errors=True)
        raise

    _maybe_normalize_user_agent(driver, effective_stealth_mode)
    _maybe_apply_stealth(driver, effective_stealth_mode)

    # An explicit empty proxy ({url: ""}) asks for direct mode — a fresh
    # browser is already direct, so no extension round-trip is needed.
    if proxy is not None and not _is_proxy_empty(proxy):
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
            raise RuntimeError(f'Chrome binary "{chrome_path}" is not executable. Please, extract the archive with "tar xzf <file.tar.gz>".')
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
        except Exception:  # noqa: BLE001
            try:
                return extract_version_nt_registry()
            except Exception:  # noqa: BLE001
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
    logger.debug("wait_for_page_stable: timed out after %.0fs, proceeding anyway", timeout)


def retry_driver_read(read_fn, retries: int = 10, delay: float = 0.5):
    """Retry a driver property read that may transiently fail during navigation."""
    last_exc: WebDriverException | None = None
    for attempt in range(1, retries + 1):
        try:
            result = read_fn()
            if attempt > 1:
                logger.debug("Driver read succeeded after %d retries", attempt - 1)
            return result
        except WebDriverException as exc:
            msg = str(exc).lower()
            if "no such execution context" in msg or "aborted by navigation" in msg:
                logger.debug("Driver read failed transiently (%s), retry %d/%d", exc, attempt, retries)
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
        raise TypeError("Error getting browser User-Agent. The returned value is not a string.")
    return user_agent_value


def get_user_agent(driver=None) -> str:
    global USER_AGENT
    if driver is not None:
        try:
            return re.sub("HEADLESS", "", _fetch_user_agent(driver), flags=re.IGNORECASE)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("Error getting browser User-Agent. " + str(e))

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
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("Error getting browser User-Agent. " + str(e))
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

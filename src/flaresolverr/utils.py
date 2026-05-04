import json
import logging
import os
import platform
import re
import shutil
import tempfile
import urllib.parse
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from selenium.webdriver.chrome.webdriver import WebDriver
from flaresolverr import undetected_chromedriver as uc  # type: ignore[import-untyped]

FLARESOLVERR_VERSION: str | None = None
PLATFORM_VERSION: str | None = None
CHROME_EXE_PATH: str | None = None
CHROME_MAJOR_VERSION: str | None = None
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
    _CUSTOM_CHROMIUM = os.path.exists("/opt/chromium/.stealth-patched")
    return _CUSTOM_CHROMIUM


def get_config_log_html() -> bool:
    return os.environ.get("LOG_HTML", "false").lower() == "true"


def get_config_headless() -> bool:
    return os.environ.get("HEADLESS", "true").lower() == "true"


def get_config_disable_media() -> bool:
    return os.environ.get("DISABLE_MEDIA", "false").lower() == "true"


def get_config_disable_quic() -> bool:
    return os.environ.get("DISABLE_QUIC", "true").lower() == "true"


def get_config_minimal_fingerprint() -> bool:
    return os.environ.get("MINIMAL_FINGERPRINT", "true").lower() == "true"


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


def _apply_stealth_patches(driver: WebDriver, stealth_mode: str) -> None:
    # standard mode: enable WebGL spoofing — the worker wrapper also patches workers
    # so main/worker WebGL values stay consistent.
    # csp-safe mode: disable WebGL spoofing — blob: worker injection is skipped
    # (BLOB_BYPASS=true), so the worker would see real renderer values and a
    # main-thread spoof would create a detectable inconsistency.
    patch_webgl = stealth_mode == STEALTH_MODE_STANDARD
    patch_blob_bypass = stealth_mode == STEALTH_MODE_CSP_SAFE
    prelude = (
        f"window.__FS_STEALTH_PATCH_WEBGL = {'true' if patch_webgl else 'false'};\n"
        f"window.__FS_STEALTH_BLOB_BYPASS = {'true' if patch_blob_bypass else 'false'};\n"
    )
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": prelude + _load_stealth_script(fallback=True)})


def apply_user_agent_override(driver: WebDriver, user_agent: str) -> None:
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
    chrome_version = chrome_match.group(1) if chrome_match else "130"

    # Build brands array (Chrome's GREASEd brand format)
    brands = [
        {"brand": "Chromium", "version": chrome_version},
        {"brand": "Google Chrome", "version": chrome_version},
        {"brand": "Not.A/Brand", "version": "24"},
    ]

    driver.execute_cdp_cmd(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": user_agent,
            "userAgentMetadata": {
                "platform": platform,
                "platformVersion": platform_version,
                "architecture": architecture,
                "model": "",
                "mobile": False,
                "brands": brands,
                "fullVersionList": [
                    {"brand": "Chromium", "version": f"{chrome_version}.0.0.0"},
                    {"brand": "Google Chrome", "version": f"{chrome_version}.0.0.0"},
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
        from importlib.metadata import version

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


def create_proxy_extension(proxy: dict[str, Any]) -> str:
    parsed_url = urllib.parse.urlparse(proxy["url"])
    scheme = parsed_url.scheme
    host = parsed_url.hostname
    port = parsed_url.port
    username = proxy["username"]
    password = proxy["password"]
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 3,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy",
            "tabs",
            "storage",
            "webRequest",
            "webRequestAuthProvider"
        ],
        "host_permissions": [
          "<all_urls>"
        ],
        "background": {
          "service_worker": "background.js"
        },
        "minimum_chrome_version": "76.0.0"
    }
    """

    background_js = """
    var config = {
        mode: "fixed_servers",
        rules: {
            singleProxy: {
                scheme: "%s",
                host: "%s",
                port: %d
            },
            bypassList: ["localhost"]
        }
    };

    chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

    function callbackFn(details) {
        return {
            authCredentials: {
                username: "%s",
                password: "%s"
            }
        };
    }

    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        { urls: ["<all_urls>"] },
        ['blocking']
    );
    """ % (scheme, host, port, username, password)

    proxy_extension_dir = tempfile.mkdtemp()

    with open(os.path.join(proxy_extension_dir, "manifest.json"), "w") as f:
        f.write(manifest_json)

    with open(os.path.join(proxy_extension_dir, "background.js"), "w") as f:
        f.write(background_js)

    return proxy_extension_dir


def _build_chrome_options(effective_stealth_mode: str) -> uc.ChromeOptions:
    """Build and configure ChromeOptions based on settings."""
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-search-engine-choice-screen")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-zygote")

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

    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")

    if not minimal_fingerprint:
        options.add_argument("--disable-blink-features=AutomationControlled")

    language = os.environ.get("LANG", None)
    if language is not None:
        options.add_argument("--accept-lang=%s" % language)

    if effective_stealth_mode != STEALTH_MODE_OFF and _is_custom_chromium():
        options.add_argument("--enable-trusted-synthetic-events")
        # --preload-script causes renderer CPU spin (GetWebFrame()->ExecuteScript from
        # DidCreateDocumentElement appears unsafe); use CDP injection instead.
        options.add_argument("--webgl-unmasked-vendor=Intel Inc.")
        options.add_argument("--webgl-unmasked-renderer=Intel(R) Iris(TM) Graphics 6100")
        options.add_argument("--stealth-navigator-languages")
        options.add_argument("--stealth-viewport-size")
        logging.debug("Applied custom Chromium stealth flags.")

    return options


def _handle_proxy_setup(options: uc.ChromeOptions, proxy: dict[str, Any] | None) -> str | None:
    """Configure proxy settings and return extension directory if created."""
    if proxy is None:
        return None

    if all(key in proxy for key in ["url", "username", "password"]):
        proxy_extension_dir = create_proxy_extension(proxy)
        options.add_argument("--disable-features=DisableLoadExtensionCommandLineSwitch")
        options.add_argument("--load-extension=%s" % os.path.abspath(proxy_extension_dir))
        return proxy_extension_dir

    if "url" in proxy:
        proxy_url = proxy["url"]
        logging.debug("Using webdriver proxy: %s", proxy_url)
        options.add_argument("--proxy-server=%s" % proxy_url)

    return None


def _resolve_driver_paths() -> tuple[str | None, str | None]:
    """Return (driver_exe_path, version_main) tuple."""
    global PATCHED_DRIVER_PATH

    if os.path.exists("/app/chromedriver"):
        return "/app/chromedriver", None

    version_main = get_chrome_major_version()
    driver_exe_path = PATCHED_DRIVER_PATH if PATCHED_DRIVER_PATH is not None else None
    return driver_exe_path, version_main


def _configure_headless() -> bool:
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

        if ua_changed or effective_stealth_mode != STEALTH_MODE_OFF:
            apply_user_agent_override(driver, normalized_ua)
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
    if effective_stealth_mode == STEALTH_MODE_OFF:
        return

    _apply_screen_size_override(driver)

    try:
        if _is_custom_chromium():
            # C++ flags handle WebGL, webdriver, languages, isTrusted at binary level.
            # Inject stealth.js (not stealth_fallback.js) via CDP — stealth.js does NOT
            # patch Navigator.prototype.webdriver or languages so getter-tampering
            # detections (webdriverGetterPatched, languagesProtoGetterPatched) are avoided.
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


def get_webdriver(proxy: dict[str, Any] | None = None, stealth_mode: str | bool | None = None) -> WebDriver:
    global PATCHED_DRIVER_PATH

    logging.debug("Launching web browser...")

    effective_stealth_mode = get_config_stealth_mode() if stealth_mode is None else normalize_stealth_mode(stealth_mode)

    options = _build_chrome_options(effective_stealth_mode)
    proxy_extension_dir = _handle_proxy_setup(options, proxy)
    windows_headless = _configure_headless()
    driver_exe_path, version_main = _resolve_driver_paths()
    browser_executable_path = get_chrome_exe_path()

    try:
        driver = uc.Chrome(
            options=options,
            browser_executable_path=browser_executable_path,
            driver_executable_path=driver_exe_path,
            version_main=version_main,
            windows_headless=windows_headless,
            headless=get_config_headless(),
        )
    except Exception as e:
        logging.error("Error starting Chrome: %s", e)
        raise e

    _maybe_normalize_user_agent(driver, effective_stealth_mode)
    _maybe_apply_stealth(driver, effective_stealth_mode)
    _save_patched_driver(driver, driver_exe_path)

    if proxy_extension_dir is not None:
        shutil.rmtree(proxy_extension_dir)

    # selenium vanilla
    # options = webdriver.ChromeOptions()
    # options.add_argument('--no-sandbox')
    # options.add_argument('--window-size=1920,1080')
    # options.add_argument('--disable-setuid-sandbox')
    # options.add_argument('--disable-dev-shm-usage')
    # driver = webdriver.Chrome(options=options)

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


def get_chrome_major_version() -> str:
    global CHROME_MAJOR_VERSION
    if CHROME_MAJOR_VERSION is not None:
        return CHROME_MAJOR_VERSION

    if os.name == "nt":
        # Example: '104.0.5112.79'
        try:
            complete_version = extract_version_nt_executable(get_chrome_exe_path())
        except Exception:
            try:
                complete_version = extract_version_nt_registry()
            except Exception:
                # Example: '104.0.5112.79'
                complete_version = extract_version_nt_folder()
    else:
        chrome_path = get_chrome_exe_path()
        if chrome_path is None:
            return ""
        process = os.popen(f'"{chrome_path}" --version')
        # Example 1: 'Chromium 104.0.5112.79 Arch Linux\n'
        # Example 2: 'Google Chrome 104.0.5112.79 Arch Linux\n'
        complete_version = process.read()
        process.close()

    CHROME_MAJOR_VERSION = complete_version.split(".")[0].split(" ")[-1]
    return CHROME_MAJOR_VERSION


def extract_version_nt_executable(exe_path: str) -> str:
    import pefile  # pyright: ignore[reportMissingImports]

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


def get_user_agent(driver=None) -> str:
    global USER_AGENT
    if driver is not None:
        try:
            user_agent_value = driver.execute_script("return navigator.userAgent")
            if not isinstance(user_agent_value, str):
                raise Exception("Error getting browser User-Agent. The returned value is not a string.")
            # Keep parity with previous behavior and remove HEADLESS token if present.
            return re.sub("HEADLESS", "", user_agent_value, flags=re.IGNORECASE)
        except Exception as e:
            raise Exception("Error getting browser User-Agent. " + str(e))

    if USER_AGENT is not None:
        return USER_AGENT

    try:
        if driver is None:
            driver = get_webdriver()
        user_agent_value = driver.execute_script("return navigator.userAgent")
        if not isinstance(user_agent_value, str):
            raise Exception("Error getting browser User-Agent. The returned value is not a string.")
        USER_AGENT = user_agent_value
        # Fix for Chrome 117 | https://github.com/FlareSolverr/FlareSolverr/issues/910
        USER_AGENT = re.sub("HEADLESS", "", USER_AGENT, flags=re.IGNORECASE)
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
        from xvfbwrapper import Xvfb

        width = int(os.environ.get("XVFB_WIDTH", "1920"))
        height = int(os.environ.get("XVFB_HEIGHT", "1080"))
        colordepth = int(os.environ.get("XVFB_COLORDEPTH", "24"))
        XVFB_DISPLAY = Xvfb(width=width, height=height, colordepth=colordepth)
        XVFB_DISPLAY.start()


def object_to_dict(_object: Any) -> dict[str, Any]:
    json_dict = json.loads(json.dumps(_object, default=lambda o: o.__dict__))
    # remove hidden fields
    return {k: v for k, v in json_dict.items() if not k.startswith("__")}

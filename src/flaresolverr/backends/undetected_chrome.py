import logging
import os
import platform
import shutil
from typing import Any

from selenium.webdriver.chrome.webdriver import WebDriver
from flaresolverr import undetected_chromedriver as uc
from flaresolverr import utils

_PATCHED_DRIVER_PATH: str | None = None
_STEALTH_SCRIPT: str | None = None
_STEALTH_FALLBACK_SCRIPT: str | None = None
_CUSTOM_CHROMIUM: bool | None = None


def _load_stealth_script(fallback: bool = False) -> str:
    global _STEALTH_SCRIPT, _STEALTH_FALLBACK_SCRIPT
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if fallback:
        if _STEALTH_FALLBACK_SCRIPT is None:
            path = os.path.join(base, "stealth_fallback.js")
            with open(path) as f:
                _STEALTH_FALLBACK_SCRIPT = f.read()
        return _STEALTH_FALLBACK_SCRIPT
    if _STEALTH_SCRIPT is None:
        path = os.path.join(base, "stealth.js")
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

    _CUSTOM_CHROMIUM = os.path.exists("/opt/chromium/.stealth-patched")
    return _CUSTOM_CHROMIUM


def _apply_stealth_patches(driver: WebDriver, stealth_mode: str) -> None:
    patch_webgl = stealth_mode == utils.STEALTH_MODE_STANDARD
    patch_blob_bypass = stealth_mode == utils.STEALTH_MODE_CSP_SAFE
    prelude = (
        f"window.__FS_STEALTH_PATCH_WEBGL = {'true' if patch_webgl else 'false'};\n"
        f"window.__FS_STEALTH_BLOB_BYPASS = {'true' if patch_blob_bypass else 'false'};\n"
    )
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": prelude + _load_stealth_script(fallback=True)})


def _apply_screen_size_override(driver: WebDriver) -> None:
    try:
        sw = driver.execute_script("return screen.width")
        sh = driver.execute_script("return screen.height")
        if sw == 800 and sh == 600:
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
    if effective_stealth_mode == utils.STEALTH_MODE_OFF:
        return

    _apply_screen_size_override(driver)

    try:
        if _is_custom_chromium():
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": _load_stealth_script(fallback=False)})
            logging.info("Applied custom Chromium stealth (C++ flags + CDP stealth.js, mode=%s).", effective_stealth_mode)
        else:
            _apply_stealth_patches(driver, effective_stealth_mode)
            logging.info("Applied CDP stealth patches (fallback mode=%s).", effective_stealth_mode)
    except Exception as e:
        logging.warning("Failed applying stealth patches: %s", e)


def _maybe_normalize_user_agent(driver: WebDriver, effective_stealth_mode: str) -> None:
    try:
        default_ua = driver.execute_script("return navigator.userAgent")
        if not isinstance(default_ua, str):
            return

        normalized_ua = utils.sanitize_user_agent(default_ua)
        ua_changed = normalized_ua != default_ua

        if ua_changed or effective_stealth_mode != utils.STEALTH_MODE_OFF:
            utils.apply_user_agent_override(driver, normalized_ua)
            if ua_changed:
                logging.info("Normalized default user-agent by removing HeadlessChrome token.")
    except Exception as e:
        logging.warning("Failed normalizing default user-agent: %s", e)


def _save_patched_driver(driver: WebDriver, driver_exe_path: str | None) -> None:
    global _PATCHED_DRIVER_PATH

    if driver_exe_path is not None:
        return

    patcher = getattr(driver, "patcher", None)
    if patcher is None:
        return

    _PATCHED_DRIVER_PATH = os.path.join(patcher.data_path, patcher.exe_name)
    assert _PATCHED_DRIVER_PATH is not None

    if _PATCHED_DRIVER_PATH != patcher.executable_path:
        shutil.copy(patcher.executable_path, _PATCHED_DRIVER_PATH)


def _build_chrome_options(effective_stealth_mode: str) -> uc.ChromeOptions:
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-search-engine-choice-screen")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-zygote")

    minimal_fingerprint = utils.get_config_minimal_fingerprint()

    if utils.get_config_disable_quic():
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

    if effective_stealth_mode != utils.STEALTH_MODE_OFF and _is_custom_chromium():
        options.add_argument("--enable-trusted-synthetic-events")
        options.add_argument("--webgl-unmasked-vendor=Intel Inc.")
        options.add_argument("--webgl-unmasked-renderer=Intel(R) Iris(TM) Graphics 6100")
        options.add_argument("--stealth-navigator-languages")
        options.add_argument("--stealth-viewport-size")
        logging.debug("Applied custom Chromium stealth flags.")

    return options


def _handle_proxy_setup(options: uc.ChromeOptions, proxy: dict[str, Any] | None) -> str | None:
    if proxy is None:
        return None

    if all(key in proxy for key in ["url", "username", "password"]):
        proxy_extension_dir = utils.create_proxy_extension(proxy)
        options.add_argument("--disable-features=DisableLoadExtensionCommandLineSwitch")
        options.add_argument("--load-extension=%s" % os.path.abspath(proxy_extension_dir))
        return proxy_extension_dir

    if "url" in proxy:
        proxy_url = proxy["url"]
        logging.debug("Using webdriver proxy: %s", proxy_url)
        options.add_argument("--proxy-server=%s" % proxy_url)

    return None


def _resolve_driver_paths() -> tuple[str | None, str | None]:
    global _PATCHED_DRIVER_PATH

    if os.path.exists("/app/chromedriver"):
        return "/app/chromedriver", None

    version_main = utils.get_chrome_major_version()
    driver_exe_path = _PATCHED_DRIVER_PATH if _PATCHED_DRIVER_PATH is not None else None
    return driver_exe_path, version_main


class UndetectedChromeBackend:
    def create_driver(self, proxy: dict[str, Any] | None, stealth_mode: str) -> WebDriver:
        logging.debug("Launching web browser (undetected-chromedriver)...")

        options = _build_chrome_options(stealth_mode)
        proxy_extension_dir = _handle_proxy_setup(options, proxy)
        windows_headless = utils._configure_headless()
        driver_exe_path, version_main = _resolve_driver_paths()
        browser_executable_path = utils.get_chrome_exe_path()

        try:
            driver = uc.Chrome(
                options=options,
                browser_executable_path=browser_executable_path,
                driver_executable_path=driver_exe_path,
                version_main=version_main,
                windows_headless=windows_headless,
                headless=utils.get_config_headless(),
            )
        except Exception as e:
            logging.error("Error starting Chrome: %s", e)
            raise e

        _maybe_normalize_user_agent(driver, stealth_mode)
        _maybe_apply_stealth(driver, stealth_mode)
        _save_patched_driver(driver, driver_exe_path)

        if proxy_extension_dir is not None:
            shutil.rmtree(proxy_extension_dir)

        return driver

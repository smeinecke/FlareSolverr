import json
import logging
import os
import platform
import re
import shutil
import tempfile
import urllib.parse
from typing import Any
import tomllib

from selenium.webdriver.chrome.webdriver import WebDriver
import undetected_chromedriver as uc

FLARESOLVERR_VERSION: str | None = None
PLATFORM_VERSION: str | None = None
CHROME_EXE_PATH: str | None = None
CHROME_MAJOR_VERSION: str | None = None
USER_AGENT: str | None = None
XVFB_DISPLAY = None
PATCHED_DRIVER_PATH: str | None = None


def get_config_log_html() -> bool:
    return os.environ.get("LOG_HTML", "false").lower() == "true"


def get_config_headless() -> bool:
    return os.environ.get("HEADLESS", "true").lower() == "true"


def get_config_disable_media() -> bool:
    return os.environ.get("DISABLE_MEDIA", "false").lower() == "true"


def get_config_stealth_mode() -> bool:
    return os.environ.get("STEALTH_MODE", "true").lower() == "true"


def _apply_stealth_patches(driver: WebDriver) -> None:
    # Experimental stealth patching to reduce modern JS/CDP fingerprint signals.
    # This is intentionally opt-in through STEALTH_MODE because it can change page behavior.
    script = """
(() => {
  const installCdpConsoleGuard = () => {
    try {
      // Avoid devtools-style formatting side effects when pages call console.log(new Error()).
      const origLog = console.log.bind(console);
      const safeLog = (...args) => {
        const mapped = args.map((arg) => {
          if (arg instanceof Error) {
            return `${arg.name}: ${arg.message}`;
          }
          return arg;
        });
        return origLog(...mapped);
      };
      try {
        Object.defineProperty(console, "log", {
          value: safeLog,
          writable: false,
          configurable: false,
        });
      } catch (_) {
        console.log = safeLog;
      }
    } catch (_) {}
  };

  installCdpConsoleGuard();

  try {
    // Hide webdriver where possible (both instance + prototype path).
    Object.defineProperty(Navigator.prototype, "webdriver", {
      get: () => undefined,
      configurable: true,
    });
  } catch (_) {}
  try {
    Object.defineProperty(navigator, "webdriver", {
      get: () => undefined,
      configurable: true,
    });
  } catch (_) {}

  try {
    // Chromium-based browsers expose a window.chrome object.
    if (!window.chrome) {
      window.chrome = {
        app: { isInstalled: false },
        runtime: {},
      };
    } else if (!window.chrome.runtime) {
      window.chrome.runtime = {};
    }
  } catch (_) {}

  try {
    // Keep language hints non-empty and internally consistent.
    const langs = Array.isArray(navigator.languages) && navigator.languages.length > 0
      ? navigator.languages
      : ["en-US", "en"];
    const mainLang = (navigator.language && typeof navigator.language === "string")
      ? navigator.language
      : langs[0];
    Object.defineProperty(Navigator.prototype, "languages", {
      get: () => langs,
      configurable: true,
    });
    Object.defineProperty(Navigator.prototype, "language", {
      get: () => mainLang,
      configurable: true,
    });
  } catch (_) {}

  try {
    // Some hardened/automated environments expose empty plugins/mimeTypes.
    const makePluginArray = () => {
      const pdfPlugin = {
        name: "Chrome PDF Viewer",
        filename: "internal-pdf-viewer",
        description: "Portable Document Format",
        version: "1",
      };
      const pluginArray = {
        0: pdfPlugin,
        length: 1,
        item: (i) => (i === 0 ? pdfPlugin : null),
        namedItem: (name) => (name === pdfPlugin.name ? pdfPlugin : null),
      };
      return pluginArray;
    };
    const makeMimeTypeArray = () => {
      const pdfMime = {
        type: "application/pdf",
        suffixes: "pdf",
        description: "Portable Document Format",
      };
      const mimeArray = {
        0: pdfMime,
        length: 1,
        item: (i) => (i === 0 ? pdfMime : null),
        namedItem: (name) => (name === pdfMime.type ? pdfMime : null),
      };
      return mimeArray;
    };
    const currentPlugins = navigator.plugins;
    if (!currentPlugins || currentPlugins.length === 0) {
      Object.defineProperty(Navigator.prototype, "plugins", {
        get: () => makePluginArray(),
        configurable: true,
      });
    }
    const currentMimeTypes = navigator.mimeTypes;
    if (!currentMimeTypes || currentMimeTypes.length === 0) {
      Object.defineProperty(Navigator.prototype, "mimeTypes", {
        get: () => makeMimeTypeArray(),
        configurable: true,
      });
    }
  } catch (_) {}

  try {
    // Some containerized Chrome builds expose no voices at all.
    if (window.speechSynthesis && typeof window.speechSynthesis.getVoices === "function") {
      const originalGetVoices = window.speechSynthesis.getVoices.bind(window.speechSynthesis);
      window.speechSynthesis.getVoices = () => {
        const voices = originalGetVoices();
        if (Array.isArray(voices) && voices.length > 0) {
          return voices;
        }
        return [
          {
            default: true,
            lang: "en-US",
            localService: true,
            name: "Google US English",
            voiceURI: "Google US English",
          },
        ];
      };
    }
  } catch (_) {}

  try {
    // Keep notifications query behavior closer to normal browsers.
    const originalQuery = navigator.permissions && navigator.permissions.query;
    if (originalQuery) {
      navigator.permissions.query = (parameters) => {
        if (parameters && parameters.name === "notifications") {
          return Promise.resolve({ state: Notification.permission, onchange: null });
        }
        return originalQuery(parameters);
      };
    }
  } catch (_) {}

  try {
    // Ensure worker context receives the same CDP guard as the main context.
    const NativeWorker = window.Worker;
    if (NativeWorker) {
      const workerPrelude = `
        (() => {
          try {
            const origLog = console.log.bind(console);
            console.log = (...args) => origLog(...args.map((arg) => arg instanceof Error ? \`\${arg.name}: \${arg.message}\` : arg));
          } catch (_) {}
          try {
            Object.defineProperty(Navigator.prototype, "webdriver", { get: () => undefined, configurable: true });
          } catch (_) {}
        })();
      `;
      const WrappedWorker = function(scriptURL, options) {
        try {
          const wrappedBody = `${workerPrelude}\\nimportScripts(${JSON.stringify(String(scriptURL))});`;
          const blob = new Blob([wrappedBody], { type: "application/javascript" });
          const wrappedUrl = URL.createObjectURL(blob);
          return new NativeWorker(wrappedUrl, options);
        } catch (_) {
          return new NativeWorker(scriptURL, options);
        }
      };
      WrappedWorker.prototype = NativeWorker.prototype;
      Object.defineProperty(window, "Worker", {
        value: WrappedWorker,
        configurable: true,
        writable: true,
      });
    }
  } catch (_) {}
})();
"""
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})


def get_flaresolverr_version() -> str:
    global FLARESOLVERR_VERSION
    if FLARESOLVERR_VERSION is not None:
        return FLARESOLVERR_VERSION

    pyproject_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "pyproject.toml")
    if not os.path.isfile(pyproject_path):
        pyproject_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyproject.toml")

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
        FLARESOLVERR_VERSION = data["project"]["version"]
        assert FLARESOLVERR_VERSION is not None
        return FLARESOLVERR_VERSION


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


def get_webdriver(proxy: dict[str, Any] | None = None) -> WebDriver:
    global PATCHED_DRIVER_PATH, USER_AGENT
    logging.debug("Launching web browser...")

    # undetected_chromedriver
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-search-engine-choice-screen")
    # todo: this param shows a warning in chrome head-full
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # this option removes the zygote sandbox (it seems that the resolution is a bit faster)
    options.add_argument("--no-zygote")
    # attempt to fix Docker ARM32 build
    IS_ARMARCH = platform.machine().startswith(("arm", "aarch"))
    if IS_ARMARCH:
        options.add_argument("--disable-gpu-sandbox")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--disable-blink-features=AutomationControlled")

    language = os.environ.get("LANG", None)
    if language is not None:
        options.add_argument("--accept-lang=%s" % language)

    # Fix for Chrome 117 | https://github.com/FlareSolverr/FlareSolverr/issues/910
    if USER_AGENT is not None:
        options.add_argument("--user-agent=%s" % USER_AGENT)

    proxy_extension_dir = None
    if proxy and all(key in proxy for key in ["url", "username", "password"]):
        proxy_extension_dir = create_proxy_extension(proxy)
        options.add_argument("--disable-features=DisableLoadExtensionCommandLineSwitch")
        options.add_argument("--load-extension=%s" % os.path.abspath(proxy_extension_dir))
    elif proxy and "url" in proxy:
        proxy_url = proxy["url"]
        logging.debug("Using webdriver proxy: %s", proxy_url)
        options.add_argument("--proxy-server=%s" % proxy_url)

    # note: headless mode is detected (headless = True)
    # we launch the browser in head-full mode with the window hidden
    windows_headless = False
    if get_config_headless():
        if os.name == "nt":
            windows_headless = True
        else:
            start_xvfb_display()
    # For normal headless mode:
    # options.add_argument('--headless')

    # if we are inside the Docker container, we avoid downloading the driver
    driver_exe_path = None
    version_main = None
    if os.path.exists("/app/chromedriver"):
        # running inside Docker
        driver_exe_path = "/app/chromedriver"
    else:
        version_main = get_chrome_major_version()
        if PATCHED_DRIVER_PATH is not None:
            driver_exe_path = PATCHED_DRIVER_PATH

    # detect chrome path
    browser_executable_path = get_chrome_exe_path()

    # downloads and patches the chromedriver
    # if we don't set driver_executable_path it downloads, patches, and deletes the driver each time
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
        logging.error("Error starting Chrome: %s" % e)
        # No point in continuing if we cannot retrieve the driver
        raise e

    if get_config_stealth_mode():
        try:
            _apply_stealth_patches(driver)
            logging.info("Applied experimental stealth patches (STEALTH_MODE=true).")
        except Exception as e:
            logging.warning("Failed applying stealth patches: %s", e)

    # save the patched driver to avoid re-downloads
    if driver_exe_path is None:
        patcher = getattr(driver, "patcher", None)
        if patcher is not None:
            PATCHED_DRIVER_PATH = os.path.join(patcher.data_path, patcher.exe_name)
            assert PATCHED_DRIVER_PATH is not None
            if PATCHED_DRIVER_PATH != patcher.executable_path:
                shutil.copy(patcher.executable_path, PATCHED_DRIVER_PATH)

    # clean up proxy extension directory
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

        width = int(os.environ.get("XVFB_WIDTH", "1280"))
        height = int(os.environ.get("XVFB_HEIGHT", "720"))
        colordepth = int(os.environ.get("XVFB_COLORDEPTH", "24"))
        XVFB_DISPLAY = Xvfb(width=width, height=height, colordepth=colordepth)
        XVFB_DISPLAY.start()


def object_to_dict(_object: Any) -> dict[str, Any]:
    json_dict = json.loads(json.dumps(_object, default=lambda o: o.__dict__))
    # remove hidden fields
    return {k: v for k, v in json_dict.items() if not k.startswith("__")}

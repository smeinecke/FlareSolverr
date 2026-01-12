from pathlib import Path
import sys
import types

# Keep legacy absolute imports (e.g. `import flaresolverr`) working from tests/.
SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def _install_bottle_shim() -> None:
    if "bottle" in sys.modules:
        return
    try:
        __import__("bottle")
        return
    except ModuleNotFoundError:
        pass

    bottle = types.ModuleType("bottle")
    bottle.response = types.SimpleNamespace(status=200, content_type="application/json")
    bottle.request = types.SimpleNamespace(json={}, url="", remote_addr="", method="")

    class Bottle:
        def route(self, _path, **_kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, _path, **_kwargs):
            def decorator(func):
                return func

            return decorator

    class ServerAdapter:
        pass

    def run(*_args, **_kwargs):
        return None

    bottle.Bottle = Bottle
    bottle.ServerAdapter = ServerAdapter
    bottle.run = run
    sys.modules["bottle"] = bottle


def _install_selenium_and_uc_shims() -> None:
    try:
        __import__("selenium")
    except ModuleNotFoundError:
        selenium = types.ModuleType("selenium")
        webdriver = types.ModuleType("selenium.webdriver")
        chrome = types.ModuleType("selenium.webdriver.chrome")
        chrome_webdriver = types.ModuleType("selenium.webdriver.chrome.webdriver")

        class WebDriver:
            pass

        chrome_webdriver.WebDriver = WebDriver

        sys.modules["selenium"] = selenium
        sys.modules["selenium.webdriver"] = webdriver
        sys.modules["selenium.webdriver.chrome"] = chrome
        sys.modules["selenium.webdriver.chrome.webdriver"] = chrome_webdriver

    if "undetected_chromedriver" in sys.modules:
        return
    try:
        __import__("undetected_chromedriver")
        return
    except Exception:
        # Use a minimal shim if the bundled package cannot be imported.
        pass

    uc = types.ModuleType("undetected_chromedriver")

    class ChromeOptions:
        def add_argument(self, _arg):
            return None

    class Chrome:
        def __init__(self, *args, **kwargs):
            self.patcher = types.SimpleNamespace(data_path="", exe_name="", executable_path="")

    def find_chrome_executable():
        return "/usr/bin/google-chrome"

    uc.ChromeOptions = ChromeOptions
    uc.Chrome = Chrome
    uc.find_chrome_executable = find_chrome_executable
    sys.modules["undetected_chromedriver"] = uc


_install_bottle_shim()
_install_selenium_and_uc_shims()

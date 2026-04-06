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
        from selenium.common import TimeoutException  # noqa: F401
        from selenium.webdriver.common.by import By  # noqa: F401
        from selenium.webdriver.common.action_chains import ActionChains  # noqa: F401
        from selenium.webdriver.support.wait import WebDriverWait  # noqa: F401
        from selenium.webdriver.support.expected_conditions import (  # noqa: F401
            presence_of_element_located,
            visibility_of_element_located,
        )
    except (ModuleNotFoundError, ImportError):
        # Build a minimal selenium shim covering everything flaresolverr_service imports.
        selenium = sys.modules.get("selenium") or types.ModuleType("selenium")

        # selenium.common
        common = types.ModuleType("selenium.common")
        class TimeoutException(Exception): pass
        common.TimeoutException = TimeoutException  # type: ignore[attr-defined]
        sys.modules.setdefault("selenium", selenium)
        sys.modules["selenium.common"] = common

        # selenium.webdriver
        webdriver_mod = types.ModuleType("selenium.webdriver")
        chrome_mod = types.ModuleType("selenium.webdriver.chrome")
        chrome_webdriver_mod = types.ModuleType("selenium.webdriver.chrome.webdriver")
        class WebDriver: pass
        chrome_webdriver_mod.WebDriver = WebDriver  # type: ignore[attr-defined]
        sys.modules["selenium.webdriver"] = webdriver_mod
        sys.modules["selenium.webdriver.chrome"] = chrome_mod
        sys.modules["selenium.webdriver.chrome.webdriver"] = chrome_webdriver_mod

        # selenium.webdriver.common.by
        by_mod = types.ModuleType("selenium.webdriver.common.by")
        class By:
            XPATH = "xpath"
            CSS_SELECTOR = "css selector"
            ID = "id"
        by_mod.By = By  # type: ignore[attr-defined]
        common_mod = types.ModuleType("selenium.webdriver.common")
        sys.modules["selenium.webdriver.common"] = common_mod
        sys.modules["selenium.webdriver.common.by"] = by_mod

        # selenium.webdriver.common.keys
        keys_mod = types.ModuleType("selenium.webdriver.common.keys")
        class Keys:
            RETURN = "\n"
            TAB = "\t"
        keys_mod.Keys = Keys  # type: ignore[attr-defined]
        sys.modules["selenium.webdriver.common.keys"] = keys_mod

        # selenium.webdriver.common.action_chains
        ac_mod = types.ModuleType("selenium.webdriver.common.action_chains")
        class ActionChains:
            def __init__(self, driver): pass
            def move_to_element(self, el): return self
            def move_by_offset(self, x, y): return self
            def pause(self, s): return self
            def click(self): return self
            def perform(self): pass
            def send_keys(self, *a): return self
        ac_mod.ActionChains = ActionChains  # type: ignore[attr-defined]
        sys.modules["selenium.webdriver.common.action_chains"] = ac_mod

        # selenium.webdriver.support.wait
        support_mod = types.ModuleType("selenium.webdriver.support")
        wait_mod = types.ModuleType("selenium.webdriver.support.wait")
        class WebDriverWait:
            def __init__(self, driver, timeout): pass
            def until(self, condition): return None
            def until_not(self, condition): return None
        wait_mod.WebDriverWait = WebDriverWait  # type: ignore[attr-defined]
        sys.modules["selenium.webdriver.support"] = support_mod
        sys.modules["selenium.webdriver.support.wait"] = wait_mod

        # selenium.webdriver.support.expected_conditions
        ec_mod = types.ModuleType("selenium.webdriver.support.expected_conditions")
        def presence_of_element_located(locator):
            def _cond(driver): return locator
            return _cond
        def visibility_of_element_located(locator):
            def _cond(driver): return locator
            return _cond
        def staleness_of(element): return element
        def title_is(title): return title
        ec_mod.presence_of_element_located = presence_of_element_located  # type: ignore[attr-defined]
        ec_mod.visibility_of_element_located = visibility_of_element_located  # type: ignore[attr-defined]
        ec_mod.staleness_of = staleness_of  # type: ignore[attr-defined]
        ec_mod.title_is = title_is  # type: ignore[attr-defined]
        sys.modules["selenium.webdriver.support.expected_conditions"] = ec_mod

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


def _install_func_timeout_shim() -> None:
    try:
        __import__("func_timeout")
        return
    except ModuleNotFoundError:
        pass

    ft = types.ModuleType("func_timeout")

    class FunctionTimedOut(Exception):
        pass

    def func_timeout(timeout, func, args=(), kwargs=None):
        return func(*args, **(kwargs or {}))

    ft.FunctionTimedOut = FunctionTimedOut
    ft.func_timeout = func_timeout
    sys.modules["func_timeout"] = ft


_install_bottle_shim()
_install_selenium_and_uc_shims()
_install_func_timeout_shim()

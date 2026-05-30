import json
import logging
import platform
import re
import sys
import threading
import time
from datetime import timedelta
from html import escape
from typing import Any, cast
from urllib.parse import quote, unquote

from func_timeout import FunctionTimedOut, func_timeout
from selenium.common import UnexpectedAlertPresentException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import presence_of_element_located, visibility_of_element_located
from selenium.webdriver.support.wait import WebDriverWait

from flaresolverr import utils
from flaresolverr.captcha_solvers import SOLVER_MANAGER, get_available_solvers, get_config_captcha_solver
from flaresolverr.dtos import (
    STATUS_ERROR,
    STATUS_OK,
    ChallengeResolutionResultT,
    ChallengeResolutionT,
    HealthResponse,
    IndexResponse,
    V1RequestBase,
    V1ResponseBase,
)
from flaresolverr.services import SERVICE_MANAGER
from flaresolverr.services.cloudflare import CloudflareService
from flaresolverr.sessions import SessionsStorage
from flaresolverr.utils import _human_like_click, _random_delay

ACCESS_DENIED_TITLES = [
    # Cloudflare
    "Access denied",
    # Cloudflare http://bitturk.net/ Firefox
    "Attention Required! | Cloudflare",
]
ACCESS_DENIED_SELECTORS = [
    # Cloudflare
    "div.cf-error-title span.cf-code-label span",
    # Cloudflare http://bitturk.net/ Firefox
    "#cf-error-details div.cf-error-overview h1",
]

TURNSTILE_SELECTORS = ["input[name='cf-turnstile-response']"]

BLOCK_MEDIA_URL_PATTERNS = [
    # Images
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.bmp",
    "*.svg",
    "*.ico",
    "*.PNG",
    "*.JPG",
    "*.JPEG",
    "*.GIF",
    "*.WEBP",
    "*.BMP",
    "*.SVG",
    "*.ICO",
    "*.tiff",
    "*.tif",
    "*.jpe",
    "*.apng",
    "*.avif",
    "*.heic",
    "*.heif",
    "*.TIFF",
    "*.TIF",
    "*.JPE",
    "*.APNG",
    "*.AVIF",
    "*.HEIC",
    "*.HEIF",
    # Stylesheets
    "*.css",
    "*.CSS",
    # Fonts
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.otf",
    "*.eot",
    "*.WOFF",
    "*.WOFF2",
    "*.TTF",
    "*.OTF",
    "*.EOT",
]

SHORT_TIMEOUT = 1
SESSIONS_STORAGE = SessionsStorage()
_NET_ERROR_CODE_RE = re.compile(r"\bERR_[A-Z0-9_]+\b")
_MAX_PARALLEL_REQUESTS = utils.get_config_max_parallel_requests()
_PARALLEL_REQUESTS_SEMAPHORE = threading.Semaphore(_MAX_PARALLEL_REQUESTS) if _MAX_PARALLEL_REQUESTS else None


def test_browser_installation() -> None:
    logging.info("Testing web browser installation...")
    logging.info("Platform: " + platform.platform())

    chrome_exe_path = utils.get_chrome_exe_path()
    if chrome_exe_path is None:
        logging.error("Chrome / Chromium web browser not installed!")
        sys.exit(1)
    else:
        logging.info("Chrome / Chromium path: " + chrome_exe_path)

    chrome_major_version = utils.get_chrome_major_version()
    if chrome_major_version == "":
        logging.error("Chrome / Chromium version not detected!")
        sys.exit(1)
    else:
        logging.info("Chrome / Chromium major version: " + chrome_major_version)

    logging.info("Launching web browser...")
    user_agent = utils.get_user_agent()
    logging.info("FlareSolverr User-Agent: " + user_agent)
    logging.info("Test successful!")


def index_endpoint() -> IndexResponse:
    res = IndexResponse({})
    res.msg = "FlareSolverr is ready!"  # noqa
    res.version = utils.get_flaresolverr_version()  # noqa
    res.userAgent = utils.get_user_agent()
    return res


def health_endpoint() -> HealthResponse:
    res = HealthResponse({})
    res.status = STATUS_OK
    return res


def controller_v1_endpoint(req: V1RequestBase) -> V1ResponseBase:
    start_ts = int(time.time() * 1000)
    logging.info(f"Incoming request => POST /v1 body: {utils.object_to_dict(req)}")

    if _PARALLEL_REQUESTS_SEMAPHORE is not None and not _PARALLEL_REQUESTS_SEMAPHORE.acquire(blocking=False):
        res = V1ResponseBase({})
        res.__error_429__ = True
        res.status = STATUS_ERROR
        res.message = "Error: Maximum parallel requests limit reached. Please retry later."
        res.startTimestamp = start_ts
        res.endTimestamp = int(time.time() * 1000)
        res.version = utils.get_flaresolverr_version()  # noqa
        logging.warning("Request rejected: maximum parallel requests limit reached")
        return res

    try:
        res: V1ResponseBase
        try:
            res = _controller_v1_handler(req)
        except Exception as e:
            res = V1ResponseBase({})
            res.__error_500__ = True
            res.status = STATUS_ERROR
            res.message = "Error: " + str(e)
            logging.error(res.message)

        res.startTimestamp = start_ts
        res.endTimestamp = int(time.time() * 1000)
        res.version = utils.get_flaresolverr_version()  # noqa
        debug_res = utils.object_to_dict(res)
        if debug_res.get("solution", {}).get("response"):
            html = debug_res["solution"]["response"]
            debug_res["solution"]["response"] = html[:500] + ("..." if len(html) > 500 else "")
        logging.debug(f"Response => POST /v1 body: {debug_res}")
        logging.info(f"Response in {(res.endTimestamp - res.startTimestamp) / 1000} s")
        return res
    finally:
        if _PARALLEL_REQUESTS_SEMAPHORE is not None:
            _PARALLEL_REQUESTS_SEMAPHORE.release()


def _controller_v1_handler(req: V1RequestBase) -> V1ResponseBase:
    # do some validations
    if req.cmd is None:
        raise Exception("Request parameter 'cmd' is mandatory.")

    # set default values
    if req.maxTimeout is None or int(req.maxTimeout) < 1:
        req.maxTimeout = 60000

    # execute the command
    res: V1ResponseBase
    if req.cmd == "sessions.create":
        res = _cmd_sessions_create(req)
    elif req.cmd == "sessions.list":
        res = _cmd_sessions_list(req)
    elif req.cmd == "sessions.destroy":
        res = _cmd_sessions_destroy(req)
    elif req.cmd == "sessions.cleanup":
        res = _cmd_sessions_cleanup(req)
    elif req.cmd == "sessions.eval":
        res = _cmd_sessions_eval(req)
    elif req.cmd == "sessions.get":
        res = _cmd_sessions_get(req)
    elif req.cmd == "sessions.network":
        res = _cmd_sessions_network(req)
    elif req.cmd == "sessions.click":
        res = _cmd_sessions_click(req)
    elif req.cmd == "sessions.action":
        res = _cmd_sessions_action(req)
    elif req.cmd == "sessions.screenshot":
        res = _cmd_sessions_screenshot(req)
    elif req.cmd == "sessions.cdp":
        res = _cmd_sessions_cdp(req)
    elif req.cmd == "request.get":
        res = _cmd_request_get(req)
    elif req.cmd == "request.post":
        res = _cmd_request_post(req)
    else:
        raise Exception(f"Request parameter 'cmd' = '{req.cmd}' is invalid.")

    return res


def _cmd_request_get(req: V1RequestBase) -> V1ResponseBase:
    # do some validations
    if req.url is None:
        raise Exception("Request parameter 'url' is mandatory in 'request.get' command.")
    if req.postData is not None:
        raise Exception("Cannot use 'postBody' when sending a GET request.")
    if req.returnRawHtml is not None:
        logging.warning("Request parameter 'returnRawHtml' was removed in FlareSolverr v2.")
    if req.download is not None:
        logging.warning("Request parameter 'download' was removed in FlareSolverr v2.")
    if req.captchaSolver is not None:
        available = get_available_solvers()
        if req.captchaSolver not in available:
            raise Exception(f"Request parameter 'captchaSolver' = '{req.captchaSolver}' is invalid. Available solvers: {available}")

    challenge_res = _resolve_challenge(req, "GET")
    res = V1ResponseBase({})
    res.status = challenge_res.status
    res.message = challenge_res.message
    res.solution = challenge_res.result
    return res


def _cmd_request_post(req: V1RequestBase) -> V1ResponseBase:
    # do some validations
    if req.postData is None:
        raise Exception("Request parameter 'postData' is mandatory in 'request.post' command.")
    if req.returnRawHtml is not None:
        logging.warning("Request parameter 'returnRawHtml' was removed in FlareSolverr v2.")
    if req.download is not None:
        logging.warning("Request parameter 'download' was removed in FlareSolverr v2.")
    if req.captchaSolver is not None:
        available = get_available_solvers()
        if req.captchaSolver not in available:
            raise Exception(f"Request parameter 'captchaSolver' = '{req.captchaSolver}' is invalid. Available solvers: {available}")

    challenge_res = _resolve_challenge(req, "POST")
    res = V1ResponseBase({})
    res.status = challenge_res.status
    res.message = challenge_res.message
    res.solution = challenge_res.result
    return res


def _cmd_sessions_create(req: V1RequestBase) -> V1ResponseBase:
    logging.debug("Creating new session...")
    req_stealth_mode = _resolve_request_stealth_mode(req)
    enabled_services = req.enabledServices if req.enabledServices is not None else ["cloudflare", "ddos_guard"]

    max_runtime = timedelta(seconds=req.sessionMaxRuntime) if req.sessionMaxRuntime is not None else None
    idle_timeout = timedelta(seconds=req.sessionIdleTimeout) if req.sessionIdleTimeout is not None else None
    session, fresh = SESSIONS_STORAGE.create(
        session_id=req.session,
        proxy=req.proxy,
        stealth_mode=req_stealth_mode,
        user_agent=req.userAgent,
        accept_language=req.acceptLanguage,
        enabled_services=enabled_services,
        max_runtime=max_runtime,
        idle_timeout=idle_timeout,
    )
    session_id = session.session_id

    if not fresh:
        return V1ResponseBase({"status": STATUS_OK, "message": "Session already exists.", "session": session_id})

    return V1ResponseBase({"status": STATUS_OK, "message": "Session created successfully.", "session": session_id})


def _cmd_sessions_list(req: V1RequestBase) -> V1ResponseBase:
    session_ids = SESSIONS_STORAGE.session_ids()

    return V1ResponseBase({"status": STATUS_OK, "message": "", "sessions": session_ids})


def _cmd_sessions_destroy(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.destroy' command.")
    existed = SESSIONS_STORAGE.destroy(session_id)

    if not existed:
        raise Exception("The session doesn't exist.")

    return V1ResponseBase({"status": STATUS_OK, "message": "The session has been removed."})


def _cmd_sessions_cleanup(req: V1RequestBase) -> V1ResponseBase:
    destroyed = SESSIONS_STORAGE.cleanup()
    return V1ResponseBase({"status": STATUS_OK, "message": f"Cleaned up {len(destroyed)} session(s).", "sessions": destroyed})


def _cmd_sessions_get(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.get' command.")
    if not SESSIONS_STORAGE.exists(session_id):
        raise Exception("The session doesn't exist.")

    session = SESSIONS_STORAGE.sessions[session_id]
    driver = session.driver
    logging.debug(f"sessions.get (session_id={session_id})")

    result = ChallengeResolutionResultT({})
    result.url = driver.current_url
    try:
        result.title = driver.title
    except Exception:
        result.title = None
    try:
        result.response = driver.page_source
    except Exception:
        result.response = None
    try:
        result.cookies = driver.get_cookies()
    except Exception:
        result.cookies = []
    try:
        result.userAgent = driver.execute_script("return navigator.userAgent")
    except Exception:
        result.userAgent = None

    res = V1ResponseBase({})
    res.status = STATUS_OK
    res.message = "Session info retrieved successfully."
    res.solution = result
    return res


def _cmd_sessions_eval(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.eval' command.")
    if not SESSIONS_STORAGE.exists(session_id):
        raise Exception("The session doesn't exist.")

    script = req.script
    if script is None:
        raise Exception("Request parameter 'script' is mandatory in 'sessions.eval' command.")

    session = SESSIONS_STORAGE.sessions[session_id]
    driver = session.driver
    logging.debug(f"sessions.eval (session_id={session_id})")

    try:
        result = driver.execute_script(script)
    except Exception as e:
        raise Exception(f"Error executing script: {e}")

    result_obj = ChallengeResolutionResultT({})
    result_obj.evalResult = result
    result_obj.url = driver.current_url
    try:
        result_obj.cookies = driver.get_cookies()
    except Exception:
        result_obj.cookies = []

    res = V1ResponseBase({})
    res.status = STATUS_OK
    res.message = "Script executed successfully."
    res.solution = result_obj
    return res


def _cmd_sessions_network(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.network' command.")
    if not SESSIONS_STORAGE.exists(session_id):
        raise Exception("The session doesn't exist.")

    session = SESSIONS_STORAGE.sessions[session_id]
    driver = session.driver
    logging.debug(f"sessions.network (session_id={session_id})")

    try:
        logs = driver.get_log("performance")
    except Exception as e:
        raise Exception(f"Error getting network logs: {e}")

    parsed_logs = []
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            parsed_logs.append(
                {
                    "method": msg.get("method"),
                    "params": msg.get("params"),
                }
            )
        except Exception:  # nosec B110
            pass

    result = ChallengeResolutionResultT({})
    result.networkLogs = parsed_logs
    result.url = driver.current_url

    res = V1ResponseBase({})
    res.status = STATUS_OK
    res.message = f"Retrieved {len(parsed_logs)} network log entries."
    res.solution = result
    return res


def _cmd_sessions_click(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.click' command.")
    if not SESSIONS_STORAGE.exists(session_id):
        raise Exception("The session doesn't exist.")

    selector = req.selector
    if selector is None:
        raise Exception("Request parameter 'selector' is mandatory in 'sessions.click' command.")

    session = SESSIONS_STORAGE.sessions[session_id]
    driver = session.driver
    logging.debug(f"sessions.click (session_id={session_id}, selector={selector})")

    try:
        element = driver.find_element(By.XPATH, selector)
        if not element.is_displayed():
            raise Exception("Element is not displayed.")
        if element.get_attribute("disabled"):
            raise Exception("Element is disabled.")
        _human_like_click(driver, element)
    except Exception as e:
        raise Exception(f"Error clicking element: {e}")

    result = ChallengeResolutionResultT({})
    result.url = driver.current_url
    try:
        result.cookies = driver.get_cookies()
    except Exception:
        result.cookies = []

    res = V1ResponseBase({})
    res.status = STATUS_OK
    res.message = "Element clicked successfully."
    res.solution = result
    return res


def _cmd_sessions_action(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.action' command.")
    if not SESSIONS_STORAGE.exists(session_id):
        raise Exception("The session doesn't exist.")

    actions = req.actions
    if actions is None:
        raise Exception("Request parameter 'actions' is mandatory in 'sessions.action' command.")

    session = SESSIONS_STORAGE.sessions[session_id]
    driver = session.driver
    logging.debug(f"sessions.action (session_id={session_id}, actions={len(actions)})")

    try:
        action_results = _execute_actions(driver, actions)
    except Exception as e:
        raise Exception(f"Error executing actions: {e}")

    result = ChallengeResolutionResultT({})
    result.url = driver.current_url
    try:
        result.title = driver.title
    except Exception:
        result.title = None
    try:
        result.cookies = driver.get_cookies()
    except Exception:
        result.cookies = []
    eval_values = [r for r in action_results if r is not None]
    if eval_values:
        result.evalResult = eval_values if len(eval_values) > 1 else eval_values[0]

    res = V1ResponseBase({})
    res.status = STATUS_OK
    res.message = "Actions executed successfully."
    res.solution = result
    return res


def _cmd_sessions_screenshot(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.screenshot' command.")
    if not SESSIONS_STORAGE.exists(session_id):
        raise Exception("The session doesn't exist.")

    session = SESSIONS_STORAGE.sessions[session_id]
    driver = session.driver
    logging.debug(f"sessions.screenshot (session_id={session_id})")

    try:
        screenshot_b64 = driver.get_screenshot_as_base64()
    except Exception as e:
        raise Exception(f"Error capturing screenshot: {e}")

    result = ChallengeResolutionResultT({})
    result.screenshot = screenshot_b64
    result.url = driver.current_url
    try:
        result.title = driver.title
    except Exception:
        result.title = None

    res = V1ResponseBase({})
    res.status = STATUS_OK
    res.message = "Screenshot captured successfully."
    res.solution = result
    return res


def _cmd_sessions_cdp(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.cdp' command.")
    if not SESSIONS_STORAGE.exists(session_id):
        raise Exception("The session doesn't exist.")

    session = SESSIONS_STORAGE.sessions[session_id]
    driver = session.driver
    cdp_cmd = req.cdp_cmd
    cdp_params = req.cdp_params or {}
    logging.debug(f"sessions.cdp (session_id={session_id}, cmd={cdp_cmd})")

    try:
        cdp_result = driver.execute_cdp_cmd(cdp_cmd, cdp_params)
    except Exception as e:
        raise Exception(f"Error executing CDP command: {e}")

    result = ChallengeResolutionResultT({})
    result.url = driver.current_url
    result.evalResult = cdp_result

    res = V1ResponseBase({})
    res.status = STATUS_OK
    res.message = "CDP command executed successfully."
    res.solution = result
    return res


def _resolve_challenge(req: V1RequestBase, method: str) -> ChallengeResolutionT:
    max_timeout = req.maxTimeout if req.maxTimeout is not None else 60000
    timeout = int(max_timeout) / 1000
    driver = None
    session = None
    req_stealth_mode = _resolve_request_stealth_mode(req)
    try:
        if req.session:
            session_id = req.session
            ttl = timedelta(minutes=req.session_ttl_minutes) if req.session_ttl_minutes is not None else None
            max_runtime = timedelta(seconds=req.sessionMaxRuntime) if req.sessionMaxRuntime is not None else None
            idle_timeout = timedelta(seconds=req.sessionIdleTimeout) if req.sessionIdleTimeout is not None else None
            session, fresh = SESSIONS_STORAGE.get(
                session_id,
                ttl,
                stealth_mode=req_stealth_mode,
                user_agent=req.userAgent,
                accept_language=req.acceptLanguage,
                max_runtime=max_runtime,
                idle_timeout=idle_timeout,
            )

            if fresh:
                logging.debug(f"new session created to perform the request (session_id={session_id})")
            else:
                logging.debug(f"existing session is used to perform the request (session_id={session_id}, lifetime={str(session.lifetime())}, ttl={str(ttl)})")

            driver = session.driver
            # Acquire lock to prevent concurrent access to the same session
            logging.debug(f"acquiring session lock (session_id={session_id})")
            session.lock.acquire()
            logging.debug(f"session lock acquired (session_id={session_id})")
        else:
            driver = utils.get_webdriver(req.proxy, stealth_mode=req_stealth_mode)
            if req.userAgent is not None:
                utils.apply_user_agent_override(driver, req.userAgent, req.acceptLanguage or utils.get_config_accept_language())
            logging.debug("New instance of webdriver has been created to perform the request")
        enabled_services = req.enabledServices
        if enabled_services is None and session is not None:
            enabled_services = session.enabled_services
        if enabled_services is None:
            enabled_services = ["cloudflare", "ddos_guard"]
        challenge_result = func_timeout(timeout, _evil_logic, (req, driver, method, enabled_services))
        if session is not None:
            session.request_count += 1
            session.touch()
        return cast(ChallengeResolutionT, challenge_result)
    except FunctionTimedOut:
        raise Exception(f"Error solving the challenge. Timeout after {timeout} seconds.")
    except Exception as e:
        raise Exception("Error solving the challenge. " + str(e).replace("\n", "\\n"))
    finally:
        # Release session lock if it was acquired
        if session is not None and session.lock.locked():
            session.lock.release()
            logging.debug(f"session lock released (session_id={session.session_id})")
        # Quit one-off webdriver instances created for non-session requests
        if session is None and driver is not None:
            try:
                if utils.PLATFORM_VERSION == "nt":
                    driver.close()
                driver.quit()
                logging.debug("A used instance of webdriver has been destroyed")
            except Exception as e:
                logging.debug(f"Failed to quit webdriver: {e}")


def _resolve_request_stealth_mode(req: V1RequestBase) -> str | None:
    if req.stealthMode is not None:
        return utils.normalize_stealth_mode(req.stealthMode)
    if req.stealth is not None:
        return utils.normalize_stealth_mode(req.stealth)
    return None


def _get_turnstile_token(driver: WebDriver, tabs: int) -> str | None:
    token_input = driver.find_element(By.CSS_SELECTOR, "input[name='cf-turnstile-response']")
    current_value = token_input.get_attribute("value")
    while True:
        cloudflare_svc = SERVICE_MANAGER.get_service("cloudflare")
        if isinstance(cloudflare_svc, CloudflareService):
            cloudflare_svc._click_verify(driver, num_tabs=tabs)
        turnstile_token = token_input.get_attribute("value")
        if turnstile_token:
            if turnstile_token != current_value:
                logging.info(f"Turnstile token: {turnstile_token}")
                return turnstile_token
        logging.debug("Failed to extract token possibly click failed")

        # reset focus
        driver.execute_script("""
            let old = document.getElementById('__focus_helper');
            if (old) old.remove();

            let el = document.createElement('button');
            el.id = '__focus_helper';
            el.style.position = 'fixed';
            el.style.top = '0';
            el.style.left = '0';
            el.style.opacity = '0.01';
            el.style.pointerEvents = 'none';
            document.body.prepend(el);
            el.focus();
        """)
        time.sleep(1)


def _resolve_turnstile_captcha(req: V1RequestBase, driver: WebDriver) -> str | None:
    turnstile_token = None
    if req.tabs_till_verify is not None:
        if req.url is None:
            raise Exception("Request parameter 'url' is mandatory in request commands.")
        logging.debug(f"Navigating to... {req.url} in order to pass the turnstile challenge")
        driver.get(req.url)

        turnstile_challenge_found = False
        for selector in TURNSTILE_SELECTORS:
            found_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(found_elements) > 0:
                turnstile_challenge_found = True
                logging.info("Turnstile challenge detected. Selector found: " + selector)
                break
        if turnstile_challenge_found:
            turnstile_token = _get_turnstile_token(driver=driver, tabs=req.tabs_till_verify)
        else:
            logging.debug("Turnstile challenge not found")
    return turnstile_token


def _configure_blocked_media(req: V1RequestBase, driver: WebDriver) -> None:
    disable_media = utils.get_config_disable_media()
    if req.disableMedia is not None:
        disable_media = req.disableMedia
    if not disable_media:
        return
    try:
        logging.debug("Network.setBlockedURLs: %s", BLOCK_MEDIA_URL_PATTERNS)
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": BLOCK_MEDIA_URL_PATTERNS})
    except Exception:
        # if CDP commands are not available or fail, ignore and continue
        logging.debug("Network.setBlockedURLs failed or unsupported on this webdriver")


def _set_custom_headers(req: V1RequestBase, driver: WebDriver) -> None:
    if req.headers is None or len(req.headers) == 0:
        return
    try:
        logging.debug(f"Setting custom headers: {req.headers}")
        # Convert headers list to dict for CDP
        headers_dict = {}
        for header in req.headers:
            if isinstance(header, dict) and "name" in header and "value" in header:
                headers_dict[header["name"]] = header["value"]
            elif isinstance(header, str) and ":" in header:
                # Support "Name: Value" format
                name, value = header.split(":", 1)
                headers_dict[name.strip()] = value.strip()
        if headers_dict:
            driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {"headers": headers_dict})
            logging.debug(f"Custom headers set: {headers_dict}")
    except Exception as e:
        logging.warning(f"Failed to set custom headers: {e}")


def _navigate_request(req: V1RequestBase, driver: WebDriver, method: str, target_url: str) -> str | None:
    logging.debug(f"Navigating to... {req.url}")
    if method == "POST":
        _post_request(req, driver)
        return None
    if req.tabs_till_verify is None:
        driver.get(target_url)
        return None
    return _resolve_turnstile_captcha(req, driver)


def _set_request_cookies(req: V1RequestBase, driver: WebDriver, method: str, target_url: str) -> None:
    if req.cookies is None or len(req.cookies) == 0:
        return
    logging.debug("Setting cookies...")
    for cookie in req.cookies:
        driver.delete_cookie(cookie["name"])
        driver.add_cookie(cookie)
    if method == "POST":
        _post_request(req, driver)
    else:
        driver.get(target_url)


def _raise_if_access_denied(driver: WebDriver, page_title: str) -> None:
    for title in ACCESS_DENIED_TITLES:
        if page_title.startswith(title):
            raise Exception("Cloudflare has blocked this request. Probably your IP is banned for this site, check in your web browser.")
    for selector in ACCESS_DENIED_SELECTORS:
        found_elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if len(found_elements) > 0:
            raise Exception("Cloudflare has blocked this request. Probably your IP is banned for this site, check in your web browser.")


def _raise_if_navigation_error(driver: WebDriver) -> None:
    """Raise a Selenium-like network error for Chromium net error pages.

    Chrome 147 can render `chrome-error://chromewebdata/` pages instead of
    raising WebDriver exceptions on navigation failures. Integration tests and
    API compatibility expect the legacy net::ERR_* error path.
    """
    current_url = (driver.current_url or "").lower()
    page_title = (driver.title or "").strip()
    page_source = driver.page_source or ""

    has_browser_error_markers = (
        current_url.startswith("chrome-error://")
        or 'id="main-frame-error"' in page_source
        or 'class="neterror"' in page_source
        or page_title in {"This site can’t be reached", "This page can’t be reached"}
    )
    if not has_browser_error_markers:
        return

    match = _NET_ERROR_CODE_RE.search(page_source)
    if match is not None:
        raise Exception(f"Message: unknown error: net::{match.group(0)}")
    raise Exception("Message: unknown error: net::ERR_FAILED")


def _execute_actions(driver: WebDriver, actions: list) -> list[Any | None]:
    """Execute a list of browser actions after page load (fill forms, click, wait, eval).

    Returns a list of results, one per action. Non-eval actions return None.
    """
    default_action_timeout = 15
    eval_results: list[Any | None] = []
    for action in actions:
        action_type = action.get("type")
        selector = action.get("selector")
        if action_type == "fill":
            import random

            el = WebDriverWait(driver, default_action_timeout).until(presence_of_element_located((By.XPATH, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(_random_delay(0.3, 0.6))
            # Click with a random non-zero offset from center so that
            # hasClickedEmailFieldExactCenter / hasClickedFieldSmallMargin
            # bot-detection checks don't flag the exact-center pattern.
            size = el.size
            max_dx = max(4, size.get("width", 30) // 4)
            max_dy = max(4, size.get("height", 16) // 4)
            # Ensure the offset is at least 2px in at least one direction.
            dx = random.uniform(2, max_dx) * random.choice([-1, 1])  # nosec B311
            dy = random.uniform(-max_dy, max_dy)  # nosec B311
            ActionChains(driver).move_to_element_with_offset(el, int(dx), int(dy)).pause(_random_delay(0.05, 0.1)).click().perform()
            time.sleep(_random_delay(0.1, 0.2))
            el.clear()
            # Type character-by-character with realistic inter-key delays
            for ch in action.get("value", ""):
                el.send_keys(ch)
                time.sleep(random.uniform(0.06, 0.18))  # nosec B311
            logging.debug(f"Action fill: selector={selector}")
        elif action_type == "click":
            logging.debug(f"Action click: waiting for selector={selector}")
            el = WebDriverWait(driver, default_action_timeout).until(presence_of_element_located((By.XPATH, selector)))
            logging.debug("Action click: element found, scrolling")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(_random_delay(0.2, 0.4))
            if action.get("humanLike"):
                _human_like_click(driver, el)
            else:
                logging.debug("Action click: calling ActionChains.perform()")
                try:
                    # Use a small non-zero offset to avoid exact-center click detection
                    _s = el.size
                    _max_dx = max(4, _s.get("width", 30) // 4)
                    _max_dy = max(4, _s.get("height", 16) // 4)
                    import random as _r

                    _dx = _r.uniform(2, _max_dx) * _r.choice([-1, 1])  # nosec B311
                    _dy = _r.uniform(-_max_dy, _max_dy)  # nosec B311
                    ActionChains(driver).move_to_element_with_offset(el, int(_dx), int(_dy)).pause(_random_delay(0.05, 0.15)).click().perform()
                except UnexpectedAlertPresentException:
                    try:
                        alert_text = driver.switch_to.alert.text
                        logging.debug(f"Action click: dismissing alert: {alert_text!r}")
                        driver.switch_to.alert.dismiss()
                    except Exception as alert_err:  # noqa: BLE001
                        logging.debug(f"Action click: alert already gone: {alert_err}")
            logging.debug(f"Action click: done selector={selector}")
        elif action_type == "wait_for":
            timeout_ms = action.get("timeout")
            wait_timeout = timeout_ms / 1000.0 if timeout_ms is not None else default_action_timeout
            logging.debug(f"Action wait_for: selector={selector}, timeout={wait_timeout}s")
            WebDriverWait(driver, wait_timeout).until(visibility_of_element_located((By.XPATH, selector)))
            # Brief grace period: the element is visible but sibling JS signals may
            # still be writing their final values into the DOM.
            time.sleep(0.5)
            logging.debug(f"Action wait_for done: selector={selector}")
        elif action_type == "wait":
            seconds = float(action.get("seconds", 1))
            logging.debug(f"Action wait: {seconds}s")
            time.sleep(seconds)
        elif action_type == "eval":
            script = action.get("script", "")
            logging.debug(f"Action eval: script={script[:80]!r}")
            try:
                result = driver.execute_script(script)
            except Exception as e:
                raise Exception(f"Error executing eval action: {e}")
            eval_results.append(result)
            continue
        else:
            logging.warning(f"Unknown action type: {action_type!r}")
        eval_results.append(None)
    return eval_results


def _build_challenge_result(req: V1RequestBase, driver: WebDriver, turnstile_token: str | None) -> ChallengeResolutionResultT:
    challenge_res = ChallengeResolutionResultT({})
    challenge_res.url = driver.current_url
    challenge_res.status = 200  # todo: fix, selenium not provides this info
    challenge_res.userAgent = utils.get_user_agent(driver)
    challenge_res.turnstile_token = turnstile_token

    if not req.returnOnlyCookies:
        challenge_res.headers = {}  # todo: fix, selenium not provides this info

        if req.actions:
            action_results = _execute_actions(driver, req.actions)
            eval_values = [r for r in action_results if r is not None]
            if eval_values:
                challenge_res.evalResult = eval_values if len(eval_values) > 1 else eval_values[0]

        if req.waitInSeconds and req.waitInSeconds > 0:
            logging.info("Waiting " + str(req.waitInSeconds) + " seconds before returning the response...")
            time.sleep(req.waitInSeconds)

        challenge_res.response = driver.page_source

    # Get cookies after waiting to ensure all challenge cookies are captured
    challenge_res.cookies = driver.get_cookies()

    if req.returnScreenshot:
        challenge_res.screenshot = driver.get_screenshot_as_base64()  # noqa

    return challenge_res


def _evil_logic(req: V1RequestBase, driver: WebDriver, method: str, enabled_services: list[str]) -> ChallengeResolutionT:
    if req.url is None:
        raise Exception("Request parameter 'url' is mandatory in request commands.")
    target_url = req.url

    res = ChallengeResolutionT({})
    res.status = STATUS_OK
    res.message = ""

    _configure_blocked_media(req, driver)
    _set_custom_headers(req, driver)
    turnstile_token = _navigate_request(req, driver, method, target_url)
    _set_request_cookies(req, driver, method, target_url)

    # wait for the page
    if utils.get_config_log_html():
        logging.debug(f"Response HTML:\n{driver.page_source}")
    page_title = driver.title

    _raise_if_navigation_error(driver)
    _raise_if_access_denied(driver, page_title)
    detected_service = SERVICE_MANAGER.detect(driver, enabled_services)
    if detected_service is not None:
        # Try external captcha solver first if configured
        solver_used = False
        effective_solver = req.captchaSolver if req.captchaSolver is not None else get_config_captcha_solver()
        if effective_solver != "default":
            solver_type = _detect_captcha_type(driver)
            if solver_type:
                logging.info(f"Attempting to solve {solver_type} captcha with {effective_solver} solver")
                solver_used = SOLVER_MANAGER.solve(driver, solver_type, effective_solver)
                if solver_used:
                    logging.info(f"Captcha solved successfully with {effective_solver}")

        if not solver_used:
            # Fall back to default challenge resolution
            SERVICE_MANAGER.resolve(driver, detected_service)

        logging.info("Challenge solved!")
        res.message = "Challenge solved!"
    else:
        logging.info("Challenge not detected!")
        res.message = "Challenge not detected!"

    res.result = _build_challenge_result(req, driver, turnstile_token)
    return res


def _detect_captcha_type(driver: WebDriver) -> str | None:
    """Detect the type of captcha present on the page.

    Returns:
        String identifying the captcha type, or None if not detected.
    """
    # Check for hCaptcha
    hcaptcha_elements = driver.find_elements(By.CSS_SELECTOR, ".h-captcha, iframe[src*='hcaptcha.com']")
    if hcaptcha_elements:
        logging.debug("hCaptcha detected on page")
        return "hcaptcha"

    # Check for reCAPTCHA
    recaptcha_elements = driver.find_elements(By.CSS_SELECTOR, ".g-recaptcha, iframe[src*='google.com/recaptcha']")
    if recaptcha_elements:
        logging.debug("reCAPTCHA detected on page")
        return "recaptcha"

    # Check for Turnstile (already handled separately, but for completeness)
    turnstile_elements = driver.find_elements(By.CSS_SELECTOR, "input[name='cf-turnstile-response'], #turnstile-wrapper")
    if turnstile_elements:
        logging.debug("Turnstile detected on page")
        return "turnstile"

    logging.debug("No specific captcha type detected")
    return None


def _post_request(req: V1RequestBase, driver: WebDriver) -> None:
    if req.url is None:
        raise Exception("Request parameter 'url' is mandatory in request commands.")
    post_form = f'<form id="hackForm" action="{req.url}" method="POST">'
    query_string = req.postData if req.postData and req.postData[0] != "?" else req.postData[1:] if req.postData else ""
    pairs = query_string.split("&")
    for pair in pairs:
        parts = pair.split("=", 1)
        # noinspection PyBroadException
        try:
            name = unquote(parts[0])
        except Exception:
            name = parts[0]
        if name == "submit":
            continue
        # noinspection PyBroadException
        try:
            value = unquote(parts[1]) if len(parts) > 1 else ""
        except Exception:
            value = parts[1] if len(parts) > 1 else ""
        # Protection of " character, for syntax
        value = value.replace('"', "&quot;")
        post_form += f'<input type="text" name="{escape(quote(name))}" value="{escape(quote(value))}"><br>'
    post_form += "</form>"
    html_content = f"""
        <!DOCTYPE html>
        <html>
        <body>
            {post_form}
            <script>document.getElementById('hackForm').submit();</script>
        </body>
        </html>"""
    driver.get("data:text/html;charset=utf-8,{html_content}".format(html_content=html_content))

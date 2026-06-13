import json
import logging
import os
import platform
import random
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

from flaresolverr import sessions
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
from flaresolverr.sessions import SessionsStorage, SessionLimitExceededError
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

_active_requests: list[dict[str, Any]] = []
_active_requests_lock = threading.Lock()


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


def _get_public_config() -> dict[str, Any]:
    """Return a dictionary of non-credential configuration settings."""
    session_max_runtime = utils.get_config_session_max_runtime()
    session_idle_timeout = utils.get_config_session_idle_timeout()
    return {
        "logLevel": os.environ.get("LOG_LEVEL", "info"),
        "logHtml": utils.get_config_log_html(),
        "headless": utils.get_config_headless(),
        "disableMedia": utils.get_config_disable_media(),
        "jsInjectionEnabled": utils.get_config_js_injection_enabled(),
        "disableQuic": utils.get_config_disable_quic(),
        "minimalFingerprint": utils.get_config_minimal_fingerprint(),
        "stealthMode": utils.get_config_stealth_mode(),
        "acceptLanguage": utils.get_config_accept_language(),
        "port": int(os.environ.get("PORT", 8191)),
        "host": os.environ.get("HOST", "0.0.0.0"),  # nosec: B104
        "prometheusEnabled": os.environ.get("PROMETHEUS_ENABLED", "false").lower() == "true",
        "prometheusPort": int(os.environ.get("PROMETHEUS_PORT", 8192)),
        "sessionMaxRuntimeSeconds": int(session_max_runtime.total_seconds()) if session_max_runtime is not None else None,
        "sessionIdleTimeoutSeconds": int(session_idle_timeout.total_seconds()),
        "sessionMaxCount": utils.get_config_session_max_count(),
        "maxParallelRequests": _MAX_PARALLEL_REQUESTS,
        "chromeDisableOptimizations": utils.get_config_chrome_disable_optimizations(),
        "chromeExtraFlags": utils.get_config_chrome_extra_flags(),
    }


def health_endpoint(details: bool = False) -> HealthResponse:
    res = HealthResponse({})
    res.status = STATUS_OK
    res.sessionsCount = len(SESSIONS_STORAGE.sessions)
    with _active_requests_lock:
        res.activeParallelRequests = len(_active_requests)
    res.maxParallelRequests = _MAX_PARALLEL_REQUESTS
    res.maxSessionCount = utils.get_config_session_max_count()
    session_max_runtime = utils.get_config_session_max_runtime()
    res.sessionMaxRuntime = int(session_max_runtime.total_seconds()) if session_max_runtime is not None else None
    res.sessionIdleTimeout = int(utils.get_config_session_idle_timeout().total_seconds())
    res.version = utils.get_flaresolverr_version()
    res.config = _get_public_config()

    if details:
        now_ms = int(time.time() * 1000)
        with _active_requests_lock:
            res.activeRequests = [
                {
                    "cmd": r.get("cmd"),
                    "url": r.get("url"),
                    "sessionId": r.get("session_id"),
                    "runtimeMs": now_ms - r.get("start_ts", now_ms),
                }
                for r in _active_requests
            ]
        with SESSIONS_STORAGE._lock:
            res.sessions = [
                {
                    "sessionId": s.session_id,
                    "lifetimeSeconds": int(s.lifetime().total_seconds()),
                    "idleTimeSeconds": int(s.idle_time().total_seconds()),
                    "requestCount": s.request_count,
                    "locked": s.lock.locked(),
                    "stealthMode": s.stealth_mode,
                    "enabledServices": s.enabled_services,
                    "hasProxy": s.proxy is not None,
                    "userAgent": s.user_agent_override,
                    "maxRuntimeSeconds": int(s.max_runtime.total_seconds()) if s.max_runtime is not None else None,
                    "idleTimeoutSeconds": int(s.idle_timeout.total_seconds()),
                }
                for s in SESSIONS_STORAGE.sessions.values()
            ]
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
        with _active_requests_lock:
            _active_requests.append(
                {
                    "cmd": req.cmd,
                    "url": req.url,
                    "session_id": req.session,
                    "start_ts": start_ts,
                }
            )
        res: V1ResponseBase
        try:
            res = _controller_v1_handler(req)
        except SessionLimitExceededError as e:
            res = V1ResponseBase({})
            res.__error_429__ = True
            res.status = STATUS_ERROR
            res.message = "Error: " + str(e)
            res.startTimestamp = start_ts
            res.endTimestamp = int(time.time() * 1000)
            res.version = utils.get_flaresolverr_version()  # noqa
            logging.warning("Request rejected: " + str(e))
            return res
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
        with _active_requests_lock:
            try:
                _active_requests.remove(
                    {
                        "cmd": req.cmd,
                        "url": req.url,
                        "session_id": req.session,
                        "start_ts": start_ts,
                    }
                )
            except ValueError:
                pass
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
    elif req.cmd == "sessions.clear":
        res = _cmd_sessions_clear(req)
    elif req.cmd == "sessions.cdp":
        res = _cmd_sessions_cdp(req)
    elif req.cmd == "request.get":
        res = _cmd_request_get(req)
    elif req.cmd == "request.post":
        res = _cmd_request_post(req)
    else:
        raise Exception(f"Request parameter 'cmd' = '{req.cmd}' is invalid.")

    return res


def _validate_common_request_params(req: V1RequestBase) -> None:
    """Validate request parameters shared between GET and POST commands."""
    if req.returnRawHtml is not None:
        logging.warning("Request parameter 'returnRawHtml' was removed in FlareSolverr v2.")
    if req.captchaSolver is not None:
        available = get_available_solvers()
        if req.captchaSolver not in available:
            raise Exception(f"Request parameter 'captchaSolver' = '{req.captchaSolver}' is invalid. Available solvers: {available}")


def _safe_driver_call(callable_, default):
    """Safely call a driver method/property, returning default on failure."""
    try:
        return callable_()
    except Exception:
        return default


def _cmd_request_get(req: V1RequestBase) -> V1ResponseBase:
    # do some validations
    if req.url is None:
        raise Exception("Request parameter 'url' is mandatory in 'request.get' command.")
    if req.postData is not None:
        raise Exception("Cannot use 'postData' when sending a GET request.")
    if req.postDataRaw is not None:
        raise Exception("Cannot use 'postDataRaw' when sending a GET request.")
    _validate_common_request_params(req)

    challenge_res = _resolve_challenge(req, "GET")
    return _build_response_from_challenge(challenge_res)


def _cmd_request_post(req: V1RequestBase) -> V1ResponseBase:
    # do some validations
    if req.postData is None and req.postDataRaw is None:
        raise Exception("Request parameter 'postData' or 'postDataRaw' is mandatory in 'request.post' command.")
    if req.postData is not None and req.postDataRaw is not None:
        raise Exception("Cannot use both 'postData' and 'postDataRaw' in the same request.")
    _validate_common_request_params(req)

    challenge_res = _resolve_challenge(req, "POST")
    return _build_response_from_challenge(challenge_res)


def _build_response_from_challenge(challenge_res: ChallengeResolutionT) -> V1ResponseBase:
    """Build a V1ResponseBase from a challenge resolution result."""
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


def _get_session_locked(session_id: str) -> sessions.Session:
    """Look up a session under SESSIONS_STORAGE._lock and acquire its driver lock.

    Raises Exception if the session doesn't exist.  This avoids the TOCTOU race
    between SESSIONS_STORAGE.exists() and SESSIONS_STORAGE.sessions[session_id].
    """
    with SESSIONS_STORAGE._lock:
        session = SESSIONS_STORAGE.sessions.get(session_id)
    if session is None:
        raise Exception("The session doesn't exist.")
    session.lock.acquire()
    return session


def _cmd_sessions_cleanup(req: V1RequestBase) -> V1ResponseBase:
    destroyed = SESSIONS_STORAGE.cleanup()
    return V1ResponseBase({"status": STATUS_OK, "message": f"Cleaned up {len(destroyed)} session(s).", "sessions": destroyed})


def _cmd_sessions_get(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.get' command.")

    session = _get_session_locked(session_id)
    try:
        driver = session.driver
        logging.debug(f"sessions.get (session_id={session_id})")

        result = ChallengeResolutionResultT({})
        result.url = driver.current_url
        result.title = _safe_driver_call(lambda: driver.title, None)
        result.response = _safe_driver_call(lambda: driver.page_source, None)
        result.cookies = _safe_driver_call(driver.get_cookies, [])
        result.userAgent = _safe_driver_call(lambda: driver.execute_script("return navigator.userAgent"), None)

        res = V1ResponseBase({})
        res.status = STATUS_OK
        res.message = "Session info retrieved successfully."
        res.solution = result
        return res
    finally:
        session.lock.release()


def _cmd_sessions_eval(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.eval' command.")
    script = req.script
    if script is None:
        raise Exception("Request parameter 'script' is mandatory in 'sessions.eval' command.")

    session = _get_session_locked(session_id)
    try:
        driver = session.driver
        logging.debug(f"sessions.eval (session_id={session_id})")

        try:
            result = driver.execute_script(script)
        except Exception as e:
            raise Exception(f"Error executing script: {e}")

        result_obj = ChallengeResolutionResultT({})
        result_obj.evalResult = result
        result_obj.url = driver.current_url
        result_obj.cookies = _safe_driver_call(driver.get_cookies, [])

        res = V1ResponseBase({})
        res.status = STATUS_OK
        res.message = "Script executed successfully."
        res.solution = result_obj
        return res
    finally:
        session.lock.release()


def _cmd_sessions_network(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.network' command.")

    session = _get_session_locked(session_id)
    try:
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
    finally:
        session.lock.release()


def _cmd_sessions_click(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.click' command.")
    selector = req.selector
    if selector is None:
        raise Exception("Request parameter 'selector' is mandatory in 'sessions.click' command.")

    session = _get_session_locked(session_id)
    try:
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
        result.cookies = _safe_driver_call(driver.get_cookies, [])

        res = V1ResponseBase({})
        res.status = STATUS_OK
        res.message = "Element clicked successfully."
        res.solution = result
        return res
    finally:
        session.lock.release()


def _cmd_sessions_action(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.action' command.")
    actions = req.actions
    if actions is None:
        raise Exception("Request parameter 'actions' is mandatory in 'sessions.action' command.")

    session = _get_session_locked(session_id)
    try:
        driver = session.driver
        logging.debug(f"sessions.action (session_id={session_id}, actions={len(actions)})")

        try:
            action_results = _execute_actions(driver, actions)
        except Exception as e:
            raise Exception(f"Error executing actions: {e}")

        result = ChallengeResolutionResultT({})
        result.url = driver.current_url
        result.title = _safe_driver_call(lambda: driver.title, None)
        result.cookies = _safe_driver_call(driver.get_cookies, [])
        eval_values = [r for r in action_results if r is not None]
        if eval_values:
            result.evalResult = eval_values if len(eval_values) > 1 else eval_values[0]

        res = V1ResponseBase({})
        res.status = STATUS_OK
        res.message = "Actions executed successfully."
        res.solution = result
        return res
    finally:
        session.lock.release()


def _clear_session_context(driver: WebDriver) -> None:
    """Clear cookies, storage, cache, IndexedDB and service workers, then navigate to about:blank."""
    logging.debug("Clearing session context...")

    # 1. Cookies
    try:
        driver.delete_all_cookies()
        logging.debug("Cookies cleared")
    except Exception as e:
        logging.debug(f"Cookie clear failed: {e}")

    # 2. localStorage / sessionStorage
    try:
        driver.execute_script("try { localStorage.clear(); } catch(e) {} try { sessionStorage.clear(); } catch(e) {}")
        logging.debug("Storage cleared")
    except Exception as e:
        logging.debug(f"Storage clear failed: {e}")

    # 3. Browser cache via CDP
    try:
        driver.execute_cdp_cmd("Network.clearBrowserCache", {})
        logging.debug("Browser cache cleared")
    except Exception as e:
        logging.debug(f"Browser cache clear failed: {e}")

    # 4. IndexedDB
    try:
        driver.execute_script("""
            var dbs = indexedDB.databases ? indexedDB.databases() : Promise.resolve([]);
            dbs.then(function(list) {
                list.forEach(function(db) {
                    if (db.name) indexedDB.deleteDatabase(db.name);
                });
            });
        """)
        logging.debug("IndexedDB cleared")
    except Exception as e:
        logging.debug(f"IndexedDB clear failed: {e}")

    # 5. Service workers
    try:
        driver.execute_script("""
            if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
                navigator.serviceWorker.getRegistrations().then(function(regs) {
                    regs.forEach(function(reg) { reg.unregister(); });
                });
            }
        """)
        logging.debug("Service workers unregistered")
    except Exception as e:
        logging.debug(f"Service worker unregister failed: {e}")

    # 6. Navigate to about:blank
    try:
        driver.get("about:blank")
        logging.debug("Navigated to about:blank")
    except Exception as e:
        logging.debug(f"Navigate to about:blank failed: {e}")


def _cmd_sessions_clear(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.clear' command.")

    session = _get_session_locked(session_id)
    try:
        driver = session.driver
        logging.debug(f"sessions.clear (session_id={session_id})")

        try:
            _clear_session_context(driver)
        except Exception as e:
            raise Exception(f"Error clearing session context: {e}")

        result = ChallengeResolutionResultT({})
        result.url = driver.current_url
        result.title = _safe_driver_call(lambda: driver.title, None)
        result.cookies = _safe_driver_call(driver.get_cookies, [])

        res = V1ResponseBase({})
        res.status = STATUS_OK
        res.message = "Session context cleared successfully."
        res.solution = result
        return res
    finally:
        session.lock.release()


def _cmd_sessions_screenshot(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.screenshot' command.")

    session = _get_session_locked(session_id)
    try:
        driver = session.driver
        logging.debug(f"sessions.screenshot (session_id={session_id})")

        try:
            screenshot_b64 = driver.get_screenshot_as_base64()
        except Exception as e:
            raise Exception(f"Error capturing screenshot: {e}")

        result = ChallengeResolutionResultT({})
        result.screenshot = screenshot_b64
        result.url = driver.current_url
        result.title = _safe_driver_call(lambda: driver.title, None)

        res = V1ResponseBase({})
        res.status = STATUS_OK
        res.message = "Screenshot captured successfully."
        res.solution = result
        return res
    finally:
        session.lock.release()


def _cmd_sessions_cdp(req: V1RequestBase) -> V1ResponseBase:
    session_id = req.session
    if session_id is None:
        raise Exception("Request parameter 'session' is mandatory in 'sessions.cdp' command.")

    session = _get_session_locked(session_id)
    try:
        driver = session.driver
        cdp_cmd = req.cdp.get("cmd") if req.cdp else None
        cdp_params = req.cdp.get("params", {}) if req.cdp else {}
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
    finally:
        session.lock.release()


def _resolve_challenge(req: V1RequestBase, method: str) -> ChallengeResolutionT:
    max_timeout = req.maxTimeout if req.maxTimeout is not None else 60000
    timeout = int(max_timeout) / 1000
    driver = None
    session = None
    lock_acquired = False
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
                proxy=req.proxy,
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
            lock_acquired = True
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
        # Release session lock only if this thread acquired it
        if lock_acquired:
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
            # Clean up any leaked temp dirs (e.g. if get_webdriver failed
            # after creating the proxy extension temp dir)
            utils._cleanup_orphaned_temp_dirs()


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
            driver.execute_cdp_cmd("Network.enable", {})
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


def _find_and_scroll_element(driver, selector, timeout, delay_min, delay_max):
    """Wait for element by XPath, scroll it into view, and pause."""
    el = WebDriverWait(driver, timeout).until(presence_of_element_located((By.XPATH, selector)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(_random_delay(delay_min, delay_max))
    return el


def _execute_actions(driver: WebDriver, actions: list) -> list[Any | None]:
    """Execute a list of browser actions after page load (fill forms, click, wait, eval).

    Returns a list of results, one per action. Non-eval actions return None.
    """
    default_action_timeout = 15
    eval_results: list[Any | None] = []
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            raise Exception(f"Action at index {i} is not an object (got {type(action).__name__}), expected dict with 'type' key.")
        action_type = action.get("type")
        selector = action.get("selector")
        if action_type == "fill":
            el = _find_and_scroll_element(driver, selector, default_action_timeout, 0.3, 0.6)
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
            el = _find_and_scroll_element(driver, selector, default_action_timeout, 0.2, 0.4)
            logging.debug("Action click: element found, scrolling")
            if action.get("humanLike"):
                _human_like_click(driver, el)
            else:
                logging.debug("Action click: calling ActionChains.perform()")
                try:
                    # Use a small non-zero offset to avoid exact-center click detection
                    _s = el.size
                    _max_dx = max(4, _s.get("width", 30) // 4)
                    _max_dy = max(4, _s.get("height", 16) // 4)
                    _dx = random.uniform(2, _max_dx) * random.choice([-1, 1])  # nosec B311
                    _dy = random.uniform(-_max_dy, _max_dy)  # nosec B311
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
            # issue #38 - eval supports an optional returnResult flag.
            # Defaults to True for backward compatibility.
            script = action.get("script", "")
            should_return = action.get("returnResult", True)
            logging.debug(f"Action eval: script={script[:80]!r}")
            try:
                result = driver.execute_script(script)
            except Exception as e:
                raise Exception(f"Error executing eval action: {e}")
            if should_return:
                eval_results.append(result)
            else:
                eval_results.append(None)
            continue
        elif action_type == "clear_context":
            logging.debug("Action clear_context")
            try:
                _clear_session_context(driver)
            except Exception as e:
                raise Exception(f"Error executing clear_context action: {e}")
        else:
            logging.warning(f"Unknown action type: {action_type!r}")
        eval_results.append(None)
    return eval_results


def _get_download_content(driver: WebDriver, url: str) -> tuple[str, bool, dict[str, str] | None]:
    """Get raw page content for download mode.

    Tries CDP Page.getResourceContent first, then falls back to a JS fetch.
    Returns (content, is_binary, headers_dict_or_none).
    """
    # Try CDP Page.getResourceContent first
    try:
        driver.execute_cdp_cmd("Page.enable", {})
        resource = driver.execute_cdp_cmd("Page.getResourceContent", {"url": url})
        content = resource.get("content", "")
        is_base64 = resource.get("base64Encoded", False)
        if is_base64:
            return content, True, None
        return content, False, None
    except Exception as e:
        logging.debug(f"Page.getResourceContent failed: {e}")

    # Fallback: JS fetch with FileReader data URL
    script = """
        return fetch(arguments[0], {credentials: 'include'})
            .then(r => r.blob())
            .then(blob => new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onloadend = () => resolve({
                    dataUrl: reader.result,
                    type: blob.type,
                    size: blob.size
                });
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            }));
    """
    try:
        result = driver.execute_script(script, url)
        data_url = result.get("dataUrl", "")
        content_type = result.get("type", "")
        size = result.get("size", 0)
        if data_url.startswith("data:"):
            comma_idx = data_url.index(",")
            content = data_url[comma_idx + 1 :]
            is_binary = utils.is_binary_content_type(content_type)
            headers: dict[str, str] | None = {}
            if content_type:
                headers["Content-Type"] = content_type
            if size:
                headers["Content-Length"] = str(size)
            return content, is_binary, headers
    except Exception as e:
        logging.debug(f"JS fetch fallback failed: {e}")

    # Ultimate fallback: page_source
    page_source = _safe_driver_call(lambda: driver.page_source, "")
    return page_source or "", False, None


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

        if req.download:
            content, is_binary, download_headers = _get_download_content(driver, driver.current_url)
            challenge_res.response = content
            challenge_res.isBinary = is_binary
            if download_headers:
                challenge_res.headers = download_headers
        else:
            challenge_res.response = driver.page_source

    # Get cookies after waiting to ensure all challenge cookies are captured
    challenge_res.cookies = driver.get_cookies()

    if req.returnScreenshot:
        challenge_res.screenshot = driver.get_screenshot_as_base64()  # noqa

    return challenge_res


def _apply_js_injection(req: V1RequestBase, driver: WebDriver, point: str) -> None:
    """Apply declarative JS injections for the given lifecycle point.

    Collects all scripts from req.scriptInject whose point matches the
    current lifecycle stage and injects them.

    Args:
        req: The incoming request.
        driver: The active WebDriver instance.
        point: The lifecycle point being processed (document_start, document_end,
               document_idle).
    """
    if not utils.get_config_js_injection_enabled():
        if req.scriptInject is not None:
            logging.warning("JS injection fields ignored because JS_INJECTION_ENABLED is not set to true.")
        return

    if req.scriptInject is None or len(req.scriptInject) == 0:
        return

    point_lc = point.lower()
    matched = []
    for item in req.scriptInject:
        if not isinstance(item, dict):
            continue
        script = item.get("script", "")
        if not script:
            continue
        item_point = (item.get("point") or "document_idle").lower()
        if item_point == point_lc:
            matched.append(script)

    if not matched:
        return

    for script in matched:
        logging.info(f"Applying JS injection at '{point}'")
        if point == "document_start":
            try:
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
            except Exception as e:
                logging.warning(f"Failed to inject script at document_start: {e}")
        else:
            try:
                driver.execute_script(script)
            except Exception as e:
                logging.warning(f"Failed to inject script at {point}: {e}")


def _evil_logic(req: V1RequestBase, driver: WebDriver, method: str, enabled_services: list[str]) -> ChallengeResolutionT:
    if req.url is None:
        raise Exception("Request parameter 'url' is mandatory in request commands.")
    target_url = req.url

    res = ChallengeResolutionT({})
    res.status = STATUS_OK
    res.message = ""

    _configure_blocked_media(req, driver)
    _set_custom_headers(req, driver)
    _apply_js_injection(req, driver, "document_start")
    turnstile_token = _navigate_request(req, driver, method, target_url)
    _set_request_cookies(req, driver, method, target_url)

    # wait for the page
    if utils.get_config_log_html():
        logging.debug(f"Response HTML:\n{driver.page_source}")
    page_title = driver.title

    _apply_js_injection(req, driver, "document_end")
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

    _apply_js_injection(req, driver, "document_idle")
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


def _post_request_raw(req: V1RequestBase, driver: WebDriver) -> None:
    if req.url is None:
        raise Exception("Request parameter 'url' is mandatory in request commands.")
    if req.postDataRaw is None:
        raise Exception("Request parameter 'postDataRaw' is mandatory for raw POST requests.")

    target_url = req.url
    post_data = req.postDataRaw
    content_type = req.postDataContentType or "application/x-www-form-urlencoded"

    # Build headers dict for JavaScript
    headers_dict = {"Content-Type": content_type}
    if req.headers:
        for header in req.headers:
            if isinstance(header, dict) and "name" in header and "value" in header:
                headers_dict[header["name"]] = header["value"]
            elif isinstance(header, str) and ":" in header:
                name, value = header.split(":", 1)
                headers_dict[name.strip()] = value.strip()

    headers_json = json.dumps(headers_dict)

    # Navigate to the target URL first to establish the correct origin,
    # then perform the raw POST via synchronous XHR and replace the document
    # content so driver.current_url stays correct.
    driver.get(target_url)

    script = f"""
    (function() {{
        try {{
            var xhr = new XMLHttpRequest();
            xhr.open('POST', {json.dumps(target_url)}, false);
            var headers = {headers_json};
            for (var name in headers) {{
                if (headers.hasOwnProperty(name)) {{
                    xhr.setRequestHeader(name, headers[name]);
                }}
            }}
            xhr.send({json.dumps(post_data)});
            document.open();
            document.write(xhr.responseText);
            document.close();
            window.__flaresolverr_raw_post_status = xhr.status;
            window.__flaresolverr_raw_post_done = true;
        }} catch (e) {{
            window.__flaresolverr_raw_post_error = e.toString();
            window.__flaresolverr_raw_post_done = true;
        }}
    }})();
    """

    driver.execute_script(script)

    # Wait for the script to complete
    wait_timeout = 60
    wait_start = time.time()
    while time.time() - wait_start < wait_timeout:
        try:
            done = driver.execute_script("return window.__flaresolverr_raw_post_done")
        except Exception:
            done = None
        if done:
            break
        time.sleep(0.1)

    error = driver.execute_script("return window.__flaresolverr_raw_post_error")
    if error:
        raise Exception(f"Raw POST request failed: {error}")


def _post_request(req: V1RequestBase, driver: WebDriver) -> None:
    if req.url is None:
        raise Exception("Request parameter 'url' is mandatory in request commands.")
    if req.postDataRaw is not None:
        _post_request_raw(req, driver)
        return
    post_form = f'<form id="hackForm" action="{escape(req.url)}" method="POST">'
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

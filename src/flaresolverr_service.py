import logging
import platform
import sys
import time
from datetime import timedelta
from html import escape
from typing import cast
from urllib.parse import unquote, quote

from func_timeout import FunctionTimedOut, func_timeout
from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.expected_conditions import presence_of_element_located, staleness_of, title_is, visibility_of_element_located
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait

import utils
from captcha_solvers import SOLVER_MANAGER, get_config_captcha_solver
from dtos import STATUS_ERROR, STATUS_OK, ChallengeResolutionResultT, ChallengeResolutionT, HealthResponse, IndexResponse, V1RequestBase, V1ResponseBase
from sessions import SessionsStorage

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
CHALLENGE_TITLES = [
    # Cloudflare
    "Just a moment...",
    # DDoS-GUARD
    "DDoS-Guard",
]
CHALLENGE_SELECTORS = [
    # Cloudflare
    "#cf-challenge-running",
    ".ray_id",
    ".attack-box",
    "#cf-please-wait",
    "#challenge-spinner",
    "#trk_jschal_js",
    "#turnstile-wrapper",
    ".lds-ring",
    # Custom CloudFlare for EbookParadijs, Film-Paleis, MuziekFabriek and Puur-Hollands
    "td.info #js_info",
    # Fairlane / pararius.com
    "div.vc div.text-box h2",
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
    res.msg = "FlareSolverr is ready!"
    res.version = utils.get_flaresolverr_version()
    res.userAgent = utils.get_user_agent()
    return res


def health_endpoint() -> HealthResponse:
    res = HealthResponse({})
    res.status = STATUS_OK
    return res


def controller_v1_endpoint(req: V1RequestBase) -> V1ResponseBase:
    start_ts = int(time.time() * 1000)
    logging.info(f"Incoming request => POST /v1 body: {utils.object_to_dict(req)}")
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
    res.version = utils.get_flaresolverr_version()
    logging.debug(f"Response => POST /v1 body: {utils.object_to_dict(res)}")
    logging.info(f"Response in {(res.endTimestamp - res.startTimestamp) / 1000} s")
    return res


def _controller_v1_handler(req: V1RequestBase) -> V1ResponseBase:
    # do some validations
    if req.cmd is None:
        raise Exception("Request parameter 'cmd' is mandatory.")
    if req.userAgent is not None:
        logging.warning("Request parameter 'userAgent' was removed in FlareSolverr v2.")

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

    challenge_res = _resolve_challenge(req, "POST")
    res = V1ResponseBase({})
    res.status = challenge_res.status
    res.message = challenge_res.message
    res.solution = challenge_res.result
    return res


def _cmd_sessions_create(req: V1RequestBase) -> V1ResponseBase:
    logging.debug("Creating new session...")

    session, fresh = SESSIONS_STORAGE.create(session_id=req.session, proxy=req.proxy)
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


def _resolve_challenge(req: V1RequestBase, method: str) -> ChallengeResolutionT:
    max_timeout = req.maxTimeout if req.maxTimeout is not None else 60000
    timeout = int(max_timeout) / 1000
    driver = None
    session = None
    try:
        if req.session:
            session_id = req.session
            ttl = timedelta(minutes=req.session_ttl_minutes) if req.session_ttl_minutes else None
            session, fresh = SESSIONS_STORAGE.get(session_id, ttl)

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
            driver = utils.get_webdriver(req.proxy)
            logging.debug("New instance of webdriver has been created to perform the request")
        challenge_result = func_timeout(timeout, _evil_logic, (req, driver, method))
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
        if not req.session and driver is not None:
            if utils.PLATFORM_VERSION == "nt":
                driver.close()
            driver.quit()
            logging.debug("A used instance of webdriver has been destroyed")


def click_verify(driver: WebDriver, num_tabs: int = 1) -> None:
    try:
        logging.debug("Try to find the Cloudflare verify checkbox...")
        actions = ActionChains(driver)
        actions.pause(_random_delay(4.0, 6.0))
        for _ in range(num_tabs):
            actions.send_keys(Keys.TAB).pause(_random_delay(0.08, 0.15))
        actions.pause(_random_delay(0.8, 1.2))
        actions.send_keys(Keys.SPACE).perform()

        logging.debug(f"Cloudflare verify checkbox clicked after {num_tabs} tabs!")
    except Exception:
        logging.debug("Cloudflare verify checkbox not found on the page.")
    finally:
        driver.switch_to.default_content()

    try:
        logging.debug("Try to find the Cloudflare 'Verify you are human' button...")
        button = driver.find_element(
            by=By.XPATH,
            value="//input[@type='button' and @value='Verify you are human']",
        )
        if button:
            _human_like_click(driver, button)
            logging.debug("The Cloudflare 'Verify you are human' button found and clicked!")
    except Exception:
        logging.debug("The Cloudflare 'Verify you are human' button not found on the page.")

    time.sleep(_random_delay(1.5, 2.5))


def _random_delay(min_sec: float, max_sec: float) -> float:
    """Generate a random delay with slight gaussian distribution for natural feel."""
    import random

    mean = (min_sec + max_sec) / 2
    std_dev = (max_sec - min_sec) / 6
    delay = random.gauss(mean, std_dev)
    return max(min_sec, min(max_sec, delay))


def _human_like_click(driver: WebDriver, element) -> None:
    """Perform a human-like mouse movement and click with bezier curves and randomness."""
    import random
    from selenium.webdriver.common.action_chains import ActionChains

    # Get element location and size
    location = element.location
    size = element.size
    element_center_x = location["x"] + size["width"] / 2
    element_center_y = location["y"] + size["height"] / 2

    # Random offset within the element (avoid edges, focus on center area)
    offset_x = random.gauss(0, size["width"] / 8)
    offset_y = random.gauss(0, size["height"] / 8)
    target_x = element_center_x + offset_x
    target_y = element_center_y + offset_y

    # Get current mouse position or start from random screen edge
    # Start from a random position near the viewport edges (common human pattern)
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

    # Generate bezier curve points for natural movement
    points = _generate_bezier_curve((start_x, start_y), (target_x, target_y), control_points=random.randint(1, 2))  # nosec B311

    # Execute movement through points with variable speed
    actions = ActionChains(driver)
    for i, (x, y) in enumerate(points):
        if i == 0:
            actions.move_by_offset(x - viewport_width / 2, y - viewport_height / 2)
        else:
            actions.move_by_offset(x - points[i - 1][0], y - points[i - 1][1])
        # Variable delay between movements (faster in middle, slower at start/end)
        progress = i / len(points)
        delay = 0.01 + 0.03 * (1 - abs(progress - 0.5) * 2)  # 0.01 to 0.04
        actions.pause(delay)

    # Slight hesitation before clicking
    actions.pause(_random_delay(0.05, 0.15))

    # Click with slight movement during press (human hand tremor)
    actions.click_and_hold()
    actions.move_by_offset(random.gauss(0, 1), random.gauss(0, 1))
    actions.pause(_random_delay(0.03, 0.08))
    actions.release()

    actions.perform()


def _generate_bezier_curve(start: tuple[float, float], end: tuple[float, float], control_points: int = 1) -> list[tuple[float, float]]:
    """Generate points along a bezier curve for natural mouse movement."""
    import random

    points = [start]

    # Generate control points with randomness
    for i in range(control_points):
        # Control points deviate from the direct line
        t = (i + 1) / (control_points + 1)
        base_x = start[0] + (end[0] - start[0]) * t
        base_y = start[1] + (end[1] - start[1]) * t

        # Add perpendicular deviation
        deviation = max(abs(end[0] - start[0]), abs(end[1] - start[1])) * random.uniform(0.1, 0.3)  # nosec B311
        ctrl_x = base_x + deviation * random.gauss(0, 0.5)
        ctrl_y = base_y + deviation * random.gauss(0, 0.5)
        points.append((ctrl_x, ctrl_y))

    points.append(end)

    # Generate interpolated points along the curve
    num_steps = random.randint(15, 25)  # nosec B311
    curve_points = []

    for t in [i / num_steps for i in range(num_steps + 1)]:
        # De Casteljau's algorithm for bezier curves
        temp_points = points.copy()
        while len(temp_points) > 1:
            new_points = []
            for i in range(len(temp_points) - 1):
                x = temp_points[i][0] + (temp_points[i + 1][0] - temp_points[i][0]) * t
                y = temp_points[i][1] + (temp_points[i + 1][1] - temp_points[i][1]) * t
                new_points.append((x, y))
            temp_points = new_points
        curve_points.append(temp_points[0])

    return curve_points


def _get_turnstile_token(driver: WebDriver, tabs: int) -> str | None:
    token_input = driver.find_element(By.CSS_SELECTOR, "input[name='cf-turnstile-response']")
    current_value = token_input.get_attribute("value")
    while True:
        click_verify(driver, num_tabs=tabs)
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


def _challenge_found(driver: WebDriver, page_title: str) -> bool:
    for title in CHALLENGE_TITLES:
        if title.lower() == page_title.lower():
            logging.info("Challenge detected. Title found: " + page_title)
            return True
    for selector in CHALLENGE_SELECTORS:
        found_elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if len(found_elements) > 0:
            logging.info("Challenge detected. Selector found: " + selector)
            return True
    return False


def _wait_for_challenge(driver: WebDriver, html_element) -> None:
    attempt = 0
    while True:
        try:
            attempt += 1
            for title in CHALLENGE_TITLES:
                logging.debug("Waiting for title (attempt " + str(attempt) + "): " + title)
                WebDriverWait(driver, SHORT_TIMEOUT).until_not(title_is(title))
            for selector in CHALLENGE_SELECTORS:
                logging.debug("Waiting for selector (attempt " + str(attempt) + "): " + selector)
                WebDriverWait(driver, SHORT_TIMEOUT).until_not(presence_of_element_located((By.CSS_SELECTOR, selector)))
            break
        except TimeoutException:
            logging.debug("Timeout waiting for selector")
            click_verify(driver)
            # update the html (cloudflare reloads the page every 5 s)
            html_element = driver.find_element(By.TAG_NAME, "html")

    logging.debug("Waiting for redirect")
    # noinspection PyBroadException
    try:
        WebDriverWait(driver, SHORT_TIMEOUT).until(staleness_of(html_element))
    except Exception:
        logging.debug("Timeout waiting for redirect")


def _execute_actions(driver: WebDriver, actions: list) -> None:
    """Execute a list of browser actions after page load (fill forms, click, wait)."""
    action_timeout = 15
    for action in actions:
        action_type = action.get("type")
        selector = action.get("selector")
        if action_type == "fill":
            import random

            el = WebDriverWait(driver, action_timeout).until(presence_of_element_located((By.XPATH, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(_random_delay(0.3, 0.6))
            ActionChains(driver).move_to_element(el).pause(_random_delay(0.05, 0.1)).click().perform()
            time.sleep(_random_delay(0.1, 0.2))
            el.clear()
            # Type character-by-character with realistic inter-key delays
            for ch in action.get("value", ""):
                el.send_keys(ch)
                time.sleep(random.uniform(0.06, 0.18))  # nosec B311
            logging.debug(f"Action fill: selector={selector}")
        elif action_type == "click":
            el = WebDriverWait(driver, action_timeout).until(presence_of_element_located((By.XPATH, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(_random_delay(0.2, 0.4))
            if action.get("humanLike"):
                _human_like_click(driver, el)
            else:
                ActionChains(driver).move_to_element(el).pause(_random_delay(0.05, 0.15)).click().perform()
            logging.debug(f"Action click: selector={selector}")
        elif action_type == "wait_for":
            WebDriverWait(driver, action_timeout).until(visibility_of_element_located((By.XPATH, selector)))
            logging.debug(f"Action wait_for: selector={selector}")
        elif action_type == "wait":
            seconds = float(action.get("seconds", 1))
            logging.debug(f"Action wait: {seconds}s")
            time.sleep(seconds)
        else:
            logging.warning(f"Unknown action type: {action_type!r}")


def _build_challenge_result(req: V1RequestBase, driver: WebDriver, turnstile_token: str | None) -> ChallengeResolutionResultT:
    challenge_res = ChallengeResolutionResultT({})
    challenge_res.url = driver.current_url
    challenge_res.status = 200  # todo: fix, selenium not provides this info
    challenge_res.userAgent = utils.get_user_agent(driver)
    challenge_res.turnstile_token = turnstile_token

    if not req.returnOnlyCookies:
        challenge_res.headers = {}  # todo: fix, selenium not provides this info

        if req.actions:
            _execute_actions(driver, req.actions)

        if req.waitInSeconds and req.waitInSeconds > 0:
            logging.info("Waiting " + str(req.waitInSeconds) + " seconds before returning the response...")
            time.sleep(req.waitInSeconds)

        challenge_res.response = driver.page_source

    # Get cookies after waiting to ensure all challenge cookies are captured
    challenge_res.cookies = driver.get_cookies()

    if req.returnScreenshot:
        challenge_res.screenshot = driver.get_screenshot_as_base64()

    return challenge_res


def _evil_logic(req: V1RequestBase, driver: WebDriver, method: str) -> ChallengeResolutionT:
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
    html_element = driver.find_element(By.TAG_NAME, "html")
    page_title = driver.title

    _raise_if_access_denied(driver, page_title)
    challenge_found = _challenge_found(driver, page_title)
    if challenge_found:
        # Try external captcha solver first if configured
        solver_used = False
        configured_solver = get_config_captcha_solver()
        if configured_solver != "default":
            solver_type = _detect_captcha_type(driver)
            if solver_type:
                logging.info(f"Attempting to solve {solver_type} captcha with {configured_solver} solver")
                solver_used = SOLVER_MANAGER.solve(driver, solver_type)
                if solver_used:
                    logging.info(f"Captcha solved successfully with {configured_solver}")

        if not solver_used:
            # Fall back to default challenge resolution
            _wait_for_challenge(driver, html_element)

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

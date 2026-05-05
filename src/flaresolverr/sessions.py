import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
from uuid import uuid1

from selenium.webdriver.chrome.webdriver import WebDriver

from flaresolverr import utils
from flaresolverr.backends import BrowserContext


@dataclass
class Session:
    session_id: str
    driver: WebDriver | BrowserContext
    created_at: datetime
    stealth_mode: str
    user_agent_override: str | None
    request_count: int
    lock: threading.Lock  # noqa

    def __init__(self, session_id: str, driver: WebDriver | BrowserContext, created_at: datetime, stealth_mode: str, user_agent_override: str | None = None):
        self.session_id = session_id
        self.driver = driver
        self.created_at = created_at
        self.stealth_mode = stealth_mode
        self.user_agent_override = user_agent_override
        self.request_count = 0
        self.lock = threading.Lock()  # noqa

    def lifetime(self) -> timedelta:
        return datetime.now() - self.created_at


class SessionsStorage:
    """SessionsStorage creates, stores and process all the sessions"""

    def __init__(self):
        self.sessions = {}

    def create(
        self,
        session_id: Optional[str] = None,
        proxy: Optional[dict[str, Any]] = None,
        force_new: Optional[bool] = False,
        stealth_mode: Optional[str | bool] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[Session, bool]:
        """create creates new instance of WebDriver if necessary,
        assign defined (or newly generated) session_id to the instance
        and returns the session object. If a new session has been created
        second argument is set to True.

        Note: The function is idempotent, so in case if session_id
        already exists in the storage a new instance of WebDriver won't be created
        and existing session will be returned. Second argument defines if
        new session has been created (True) or an existing one was used (False).
        """
        session_id = session_id or str(uuid1())

        if force_new:
            self.destroy(session_id)

        if self.exists(session_id):
            existing_session = self.sessions[session_id]
            if stealth_mode is not None:
                normalized_mode = utils.normalize_stealth_mode(stealth_mode)
                if existing_session.stealth_mode != normalized_mode:
                    raise ValueError(
                        f"Session '{session_id}' already exists with stealthMode={existing_session.stealth_mode!r}. "
                        f"Requested stealthMode={normalized_mode!r}. Destroy/recreate the session to change this setting."
                    )
            if user_agent is not None:
                if existing_session.user_agent_override is None and existing_session.request_count == 0:
                    utils.apply_user_agent_override(existing_session.driver, user_agent)
                    existing_session.user_agent_override = user_agent
                elif existing_session.user_agent_override != user_agent:
                    raise ValueError(
                        f"Session '{session_id}' already initialized with userAgent={existing_session.user_agent_override!r}. "
                        f"Requested userAgent={user_agent!r}. Destroy/recreate the session to change this setting."
                    )
            return self.sessions[session_id], False

        effective_stealth_mode = utils.get_config_stealth_mode() if stealth_mode is None else utils.normalize_stealth_mode(stealth_mode)
        driver = utils.get_webdriver(proxy, stealth_mode=effective_stealth_mode)
        if user_agent is not None:
            utils.apply_user_agent_override(driver, user_agent)
        created_at = datetime.now()
        session = Session(session_id, driver, created_at, effective_stealth_mode, user_agent_override=user_agent)

        self.sessions[session_id] = session

        return session, True

    def exists(self, session_id: str) -> bool:
        return session_id in self.sessions

    def destroy(self, session_id: str) -> bool:
        """destroy closes the driver instance and removes session from the storage.
        The function is noop if session_id doesn't exist.
        The function returns True if session was found and destroyed,
        and False if session_id wasn't found.
        """
        if not self.exists(session_id):
            return False

        session = self.sessions.pop(session_id)
        if utils.PLATFORM_VERSION == "nt":
            session.driver.close()
        session.driver.quit()
        return True

    def get(
        self,
        session_id: str,
        ttl: Optional[timedelta] = None,
        stealth_mode: Optional[str | bool] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[Session, bool]:
        session, fresh = self.create(session_id, stealth_mode=stealth_mode, user_agent=user_agent)

        if ttl is not None and not fresh and session.lifetime() > ttl:
            logging.debug(f"session's lifetime has expired, so the session is recreated (session_id={session_id})")
            session, fresh = self.create(session_id, force_new=True, stealth_mode=stealth_mode, user_agent=user_agent)

        return session, fresh

    def session_ids(self) -> list[str]:
        return list(self.sessions.keys())

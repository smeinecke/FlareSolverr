import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
from uuid import uuid1

from selenium.webdriver.chrome.webdriver import WebDriver

from flaresolverr import utils


def _process_alive(pid: int) -> bool:
    """Best-effort check whether a process with the given PID is still alive."""
    try:
        # Works on POSIX systems (Linux, macOS)
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _ensure_process_dead(pid: int | None, grace_seconds: float = 2.0) -> None:
    """Wait for the process to exit gracefully, then force-kill it if necessary."""
    if pid is None:
        return

    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if not _process_alive(pid):
            return
        time.sleep(0.1)

    # Escalate to force kill
    try:
        if utils.PLATFORM_VERSION == "nt":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                check=False,
                capture_output=True,
            )
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


@dataclass
class Session:
    session_id: str
    driver: WebDriver
    created_at: datetime
    stealth_mode: str
    user_agent_override: str | None
    accept_language_override: str | None
    enabled_services: list[str]
    request_count: int
    lock: threading.Lock  # noqa
    last_used_at: datetime
    max_runtime: timedelta | None
    idle_timeout: timedelta

    def __init__(
        self,
        session_id: str,
        driver: WebDriver,
        created_at: datetime,
        stealth_mode: str,
        user_agent_override: str | None = None,
        accept_language_override: str | None = None,
        enabled_services: list[str] | None = None,
        max_runtime: timedelta | None = None,
        idle_timeout: timedelta | None = None,
    ):
        self.session_id = session_id
        self.driver = driver
        self.created_at = created_at
        self.stealth_mode = stealth_mode
        self.user_agent_override = user_agent_override
        self.accept_language_override = accept_language_override
        self.enabled_services = enabled_services if enabled_services is not None else ["cloudflare", "ddos_guard"]
        self.request_count = 0
        self.lock = threading.Lock()  # noqa
        self.last_used_at = created_at
        self.max_runtime = max_runtime
        self.idle_timeout = idle_timeout if idle_timeout is not None else utils.get_config_session_idle_timeout()

    def lifetime(self) -> timedelta:
        return datetime.now() - self.created_at

    def idle_time(self) -> timedelta:
        return datetime.now() - self.last_used_at

    def touch(self) -> None:
        self.last_used_at = datetime.now()

    def is_expired(self) -> bool:
        if self.max_runtime is not None and self.lifetime() > self.max_runtime:
            return True
        return self.idle_time() > self.idle_timeout


class SessionsStorage:
    """SessionsStorage creates, stores and process all the sessions"""

    def __init__(self):
        self.sessions = {}
        self._lock = threading.RLock()
        self._cleanup_thread: threading.Thread | None = None
        self._stop_cleanup = threading.Event()

    def create(
        self,
        session_id: Optional[str] = None,
        proxy: Optional[dict[str, Any]] = None,
        force_new: Optional[bool] = False,
        stealth_mode: Optional[str | bool] = None,
        user_agent: Optional[str] = None,
        accept_language: Optional[str] = None,
        enabled_services: Optional[list[str]] = None,
        max_runtime: Optional[timedelta] = None,
        idle_timeout: Optional[timedelta] = None,
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

        with self._lock:
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
                        utils.apply_user_agent_override(existing_session.driver, user_agent, accept_language or utils.get_config_accept_language())
                        existing_session.user_agent_override = user_agent
                    elif existing_session.user_agent_override != user_agent:
                        raise ValueError(
                            f"Session '{session_id}' already initialized with userAgent={existing_session.user_agent_override!r}. "
                            f"Requested userAgent={user_agent!r}. Destroy/recreate the session to change this setting."
                        )
                if accept_language is not None:
                    if existing_session.accept_language_override is None and existing_session.request_count == 0:
                        if existing_session.user_agent_override is not None:
                            utils.apply_user_agent_override(existing_session.driver, existing_session.user_agent_override, accept_language)
                        existing_session.accept_language_override = accept_language
                    elif existing_session.accept_language_override != accept_language:
                        raise ValueError(
                            f"Session '{session_id}' already initialized with acceptLanguage={existing_session.accept_language_override!r}. "
                            f"Requested acceptLanguage={accept_language!r}. Destroy/recreate the session to change this setting."
                        )
                if enabled_services is not None:
                    if existing_session.enabled_services != enabled_services:
                        raise ValueError(
                            f"Session '{session_id}' already initialized with enabledServices={existing_session.enabled_services!r}. "
                            f"Requested enabledServices={enabled_services!r}. Destroy/recreate the session to change this setting."
                        )
                return self.sessions[session_id], False

            effective_stealth_mode = utils.get_config_stealth_mode() if stealth_mode is None else utils.normalize_stealth_mode(stealth_mode)
            driver = utils.get_webdriver(
                proxy,
                stealth_mode=effective_stealth_mode,
                logging_prefs={"performance": "ALL"},
            )
            effective_accept_language = accept_language if accept_language is not None else utils.get_config_accept_language()
            if user_agent is not None:
                utils.apply_user_agent_override(driver, user_agent, effective_accept_language)
            created_at = datetime.now()
            effective_enabled_services = enabled_services if enabled_services is not None else ["cloudflare"]
            effective_max_runtime = max_runtime if max_runtime is not None else utils.get_config_session_max_runtime()
            effective_idle_timeout = idle_timeout if idle_timeout is not None else utils.get_config_session_idle_timeout()
            session = Session(
                session_id,
                driver,
                created_at,
                effective_stealth_mode,
                user_agent_override=user_agent,
                accept_language_override=accept_language,
                enabled_services=effective_enabled_services,
                max_runtime=effective_max_runtime,
                idle_timeout=effective_idle_timeout,
            )

            self.sessions[session_id] = session

            return session, True

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self.sessions

    def destroy(self, session_id: str) -> bool:
        """destroy closes the driver instance and removes session from the storage.
        The function is noop if session_id doesn't exist.
        The function returns True if session was found and destroyed,
        and False if session_id wasn't found.
        """
        with self._lock:
            if session_id not in self.sessions:
                return False
            session = self.sessions.pop(session_id)

        if utils.PLATFORM_VERSION == "nt":
            session.driver.close()
        session.driver.quit()

        # Verify the browser process is really gone; escalate to SIGKILL if needed
        browser_pid = getattr(session.driver, "browser_pid", None)
        _ensure_process_dead(browser_pid)
        return True

    def get(
        self,
        session_id: str,
        ttl: Optional[timedelta] = None,
        stealth_mode: Optional[str | bool] = None,
        user_agent: Optional[str] = None,
        accept_language: Optional[str] = None,
        enabled_services: Optional[list[str]] = None,
        max_runtime: Optional[timedelta] = None,
        idle_timeout: Optional[timedelta] = None,
    ) -> Tuple[Session, bool]:
        session, fresh = self.create(
            session_id, stealth_mode=stealth_mode, user_agent=user_agent, accept_language=accept_language,
            enabled_services=enabled_services, max_runtime=max_runtime, idle_timeout=idle_timeout,
        )

        if ttl is not None and not fresh and session.lifetime() > ttl:
            logging.debug(f"session's lifetime has expired, so the session is recreated (session_id={session_id})")
            session, fresh = self.create(
                session_id, force_new=True, stealth_mode=stealth_mode, user_agent=user_agent,
                accept_language=accept_language, enabled_services=enabled_services,
                max_runtime=max_runtime, idle_timeout=idle_timeout,
            )

        return session, fresh

    def session_ids(self) -> list[str]:
        with self._lock:
            return list(self.sessions.keys())

    def cleanup(self) -> list[str]:
        """Destroy expired sessions and enforce max session count.
        Returns a list of destroyed session IDs.
        """
        destroyed: list[str] = []
        max_count = utils.get_config_session_max_count()

        with self._lock:
            snapshot = list(self.sessions.values())

        for session in snapshot:
            if session.lock.locked():
                continue
            if session.is_expired():
                if self.destroy(session.session_id):
                    logging.info(f"Session '{session.session_id}' destroyed by cleanup (expired)")
                    destroyed.append(session.session_id)

        if max_count is not None:
            with self._lock:
                while len(self.sessions) > max_count:
                    candidates = [s for s in self.sessions.values() if not s.lock.locked()]
                    if not candidates:
                        break
                    oldest = min(candidates, key=lambda s: s.last_used_at)
                    if self.destroy(oldest.session_id):
                        logging.info(f"Session '{oldest.session_id}' destroyed by cleanup (max session count exceeded)")
                        destroyed.append(oldest.session_id)

        return destroyed

    def start_cleanup(self, interval_seconds: int = 30) -> None:
        """Start the background cleanup thread."""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return

        self._stop_cleanup.clear()

        def _run() -> None:
            while not self._stop_cleanup.wait(interval_seconds):
                try:
                    self.cleanup()
                except Exception:
                    logging.exception("Session cleanup failed")

        self._cleanup_thread = threading.Thread(target=_run, daemon=True, name="session-cleanup")
        self._cleanup_thread.start()
        logging.debug("Session cleanup thread started")

    def stop_cleanup(self) -> None:
        """Signal the background cleanup thread to stop and wait for it."""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            self._stop_cleanup.set()
            self._cleanup_thread.join(timeout=5)
            self._cleanup_thread = None

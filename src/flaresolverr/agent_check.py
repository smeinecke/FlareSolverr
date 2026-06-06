import logging
import socketserver
import threading

from flaresolverr import flaresolverr_service
from flaresolverr import utils


def _compute_state() -> str:
    """Return the HAProxy agent-check state based on current load.

    CRITICAL: This function must NEVER raise an exception.
    If anything fails, return 'drain' as a safe default.
    """
    try:
        # Request load
        max_parallel = flaresolverr_service._MAX_PARALLEL_REQUESTS  # noqa
        with flaresolverr_service._active_requests_lock:
            active = len(flaresolverr_service._active_requests)

        if max_parallel is None:
            req_state = "ready"
        elif active >= max_parallel:
            req_state = "drain"
        elif active >= max_parallel * 0.75:
            req_state = "50%"
        else:
            req_state = "ready"

        # Session load — use a copy to avoid thread-safety issues
        max_sessions = utils.get_config_session_max_count()
        try:
            # Make a shallow copy to avoid mutation-during-read race
            sessions_copy = dict(flaresolverr_service.SESSIONS_STORAGE.sessions)
            session_count = len(sessions_copy)
        except Exception:
            # If we can't read sessions, assume overloaded to be safe
            logging.warning("Agent-check: could not read session count, assuming drain")
            return "drain"

        if max_sessions is None:
            sess_state = "ready"
        elif session_count >= max_sessions:
            sess_state = "drain"
        elif session_count >= max_sessions * 0.75:
            sess_state = "50%"
        else:
            sess_state = "ready"

        # Return the most restrictive state
        if "drain" in (req_state, sess_state):
            return "drain"
        if "50%" in (req_state, sess_state):
            return "50%"
        return "ready"

    except Exception:
        logging.exception("Agent-check _compute_state crashed — returning drain")
        return "drain"


class AgentCheckHandler(socketserver.BaseRequestHandler):
    """Handle a single HAProxy agent-check TCP connection.

    CRITICAL: We must ALWAYS send a response, even on error.
    """

    def handle(self) -> None:
        state = "drain"  # safe default
        try:
            state = _compute_state()
        except Exception:
            logging.exception("Agent-check _compute_state failed")
        try:
            self.request.sendall(f"{state}\n".encode())
        except Exception:
            logging.exception("Agent-check sendall failed")
        finally:
            try:
                self.request.close()
            except Exception:
                logging.warning("Agent-check request.close failed", exc_info=True)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_agent_check_server(host: str, port: int) -> None:
    """Start the HAProxy agent-check TCP server in a background thread."""
    server = ThreadedTCPServer((host, port), AgentCheckHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True, name="agent-check")
    server_thread.start()
    logging.info(f"HAProxy agent-check TCP server listening on {host}:{port}")

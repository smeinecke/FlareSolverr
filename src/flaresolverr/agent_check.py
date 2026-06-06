import logging
import socketserver
import threading

from flaresolverr import flaresolverr_service
from flaresolverr import utils


def _compute_state() -> str:
    """Return the HAProxy agent-check state based on current load."""
    max_parallel = flaresolverr_service._MAX_PARALLEL_REQUESTS  # noqa
    with flaresolverr_service._active_requests_lock:
        active = len(flaresolverr_service._active_requests)

    # Request load state
    if max_parallel is None:
        req_state = "ready"
    elif active >= max_parallel:
        req_state = "drain"
    elif active >= max_parallel * 0.75:
        req_state = "50%"
    else:
        req_state = "ready"

    # Session load state
    max_sessions = utils.get_config_session_max_count()
    session_count = len(flaresolverr_service.SESSIONS_STORAGE.sessions)
    if max_sessions is None:
        sess_state = "ready"
    elif session_count >= max_sessions:
        sess_state = "drain"
    elif session_count >= max_sessions * 0.75:
        sess_state = "50%"
    else:
        sess_state = "ready"

    # Return the more restrictive state
    if "drain" in (req_state, sess_state):
        return "drain"
    if "50%" in (req_state, sess_state):
        return "50%"
    return "ready"


class AgentCheckHandler(socketserver.BaseRequestHandler):
    """Handle a single HAProxy agent-check TCP connection."""

    def handle(self) -> None:
        try:
            state = _compute_state()
            self.request.sendall(f"{state}\n".encode())
        except Exception:
            logging.exception("Agent-check handler failed")
        finally:
            self.request.close()


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_agent_check_server(host: str, port: int) -> None:
    """Start the HAProxy agent-check TCP server in a background thread."""
    server = ThreadedTCPServer((host, port), AgentCheckHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True, name="agent-check")
    server_thread.start()
    logging.info(f"HAProxy agent-check TCP server listening on {host}:{port}")

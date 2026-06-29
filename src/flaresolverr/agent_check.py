import logging
import socketserver
import threading

from flaresolverr import flaresolverr_service
from flaresolverr import utils


def _compute_state() -> str:
    """Return the HAProxy agent-check state based on session saturation.

    CRITICAL: This function must NEVER raise an exception.
    If anything fails, return 'drain' as a safe default.
    """
    try:
        max_sessions = utils.get_config_session_max_count()
        try:
            with flaresolverr_service.SESSIONS_STORAGE._lock:
                session_count = len(flaresolverr_service.SESSIONS_STORAGE.sessions)
        except Exception:
            # If we can't read sessions, assume overloaded to be safe
            logging.warning("Agent-check: could not read session count, assuming drain")
            return "drain"

        if max_sessions is None:
            return "ready"
        if session_count >= max_sessions:
            return "drain"
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
        except (ConnectionResetError, BrokenPipeError):
            logging.debug("Agent-check client closed connection before response could be sent")
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

"""Integration tests for HAProxy session-aware load balancing.

Requires:
- haproxy binary in PATH
- A running FlareSolverr instance at FLARESOLVERR_URL (for end-to-end tests)
"""

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from flaresolverr.dtos import V1ResponseBase, STATUS_OK

pytestmark = pytest.mark.integration


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _haproxy_available() -> bool:
    try:
        subprocess.run(["haproxy", "-v"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


class _EchoHandler(BaseHTTPRequestHandler):
    """HTTP handler that echoes back the backend name and request headers."""

    backend_id: str = "unknown"

    def log_message(self, format, *args):  # noqa
        pass

    def do_GET(self):  # noqa
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        headers = {k: v for k, v in self.headers.items()}
        body = json.dumps({"backend": self.backend_id, "headers": headers})
        self.wfile.write(body.encode())

    def do_POST(self):  # noqa
        self.do_GET()


class _EchoServer:
    """Lightweight HTTP server used as a HAProxy backend."""

    def __init__(self, backend_id: str, port: int):
        self.backend_id = backend_id
        self.port = port
        self.server = HTTPServer(("127.0.0.1", port), _create_handler(backend_id))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def _create_handler(backend_id: str):
    class Handler(_EchoHandler):
        pass

    Handler.backend_id = backend_id
    return Handler


class TestHAProxyStickyRouting(unittest.TestCase):
    """Verify that HAProxy routes consistently based on X-FlareSolverr-Session."""

    @classmethod
    def setUpClass(cls):
        if not _haproxy_available():
            raise unittest.SkipTest("haproxy binary not available")

        cls.backend1 = _EchoServer("backend-1", _find_free_port())
        cls.backend2 = _EchoServer("backend-2", _find_free_port())
        cls.backend1.start()
        cls.backend2.start()
        cls.haproxy_port = _find_free_port()

        cls.haproxy_cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False)
        cls.haproxy_cfg.write(
            f"""global
    maxconn 4096

defaults
    mode http
    timeout connect 5s
    timeout client 30s
    timeout server 30s

frontend flaresolverr_frontend
    bind 127.0.0.1:{cls.haproxy_port}
    default_backend flaresolverr_backend

backend flaresolverr_backend
    balance hdr(X-FlareSolverr-Session)
    hash-type consistent
    option httpchk GET /health
    server fs1 127.0.0.1:{cls.backend1.port} check
    server fs2 127.0.0.1:{cls.backend2.port} check
"""
        )
        cls.haproxy_cfg.close()

        cls.haproxy_proc = subprocess.Popen(
            ["haproxy", "-f", cls.haproxy_cfg.name, "-db"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # wait for HAProxy to be ready
        for _ in range(30):
            try:
                requests.get(f"http://127.0.0.1:{cls.haproxy_port}/", timeout=1)
                break
            except requests.exceptions.ConnectionError:
                time.sleep(0.2)
        else:
            cls.tearDownClass()
            raise RuntimeError("HAProxy did not start in time")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "haproxy_proc") and cls.haproxy_proc is not None:
            cls.haproxy_proc.terminate()
            try:
                cls.haproxy_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.haproxy_proc.kill()
        if hasattr(cls, "backend1"):
            cls.backend1.stop()
        if hasattr(cls, "backend2"):
            cls.backend2.stop()
        if hasattr(cls, "haproxy_cfg"):
            os.unlink(cls.haproxy_cfg.name)

    def _get_backend(self, session_header: str | None = None) -> str:
        url = f"http://127.0.0.1:{self.haproxy_port}/"
        headers = {}
        if session_header is not None:
            headers["X-FlareSolverr-Session"] = session_header
        res = requests.get(url, headers=headers, timeout=5)
        self.assertEqual(res.status_code, 200)
        return res.json()["backend"]

    def test_same_session_header_hits_same_backend(self):
        """Requests with identical X-FlareSolverr-Session must be routed consistently."""
        session_id = "sticky-session-abc"
        backends = [self._get_backend(session_id) for _ in range(10)]
        self.assertEqual(len(set(backends)), 1, f"Backends rotated: {backends}")

    def test_different_session_headers_can_hit_different_backends(self):
        """Different session IDs should be distributed (not all forced to one backend)."""
        backends = [self._get_backend(f"session-{i}") for i in range(20)]
        unique = set(backends)
        self.assertGreaterEqual(
            len(unique), 2,
            f"All requests hit a single backend: {backends}"
        )

    def test_request_without_session_header_is_routed(self):
        """Requests without the session header should still reach a backend."""
        backend = self._get_backend(None)
        self.assertIn(backend, {"backend-1", "backend-2"})


class TestHAProxyFlareSolverrEndToEnd(unittest.TestCase):
    """Verify X-FlareSolverr-Session header works end-to-end through HAProxy."""

    base_url: str | None = None
    haproxy_port: int = 0
    haproxy_cfg_path: str = ""
    haproxy_proc: subprocess.Popen | None = None
    haproxy_url: str = ""
    _external_haproxy: bool = False

    @classmethod
    def setUpClass(cls):
        external_haproxy_url = os.environ.get("HAPROXY_URL")
        if external_haproxy_url:
            # Docker-based HAProxy mode (e.g., CI)
            cls._external_haproxy = True
            cls.haproxy_url = external_haproxy_url.rstrip("/")
            try:
                requests.get(f"{cls.haproxy_url}/health", timeout=10)
            except requests.exceptions.ConnectionError:
                raise unittest.SkipTest(
                    f"HAProxy not reachable at {cls.haproxy_url} for end-to-end test"
                )
            return

        # Local HAProxy mode
        if not _haproxy_available():
            raise unittest.SkipTest("haproxy binary not available")

        cls.base_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191")
        # verify FlareSolverr is reachable
        try:
            requests.get(f"{cls.base_url}/health", timeout=5)
        except requests.exceptions.ConnectionError:
            raise unittest.SkipTest("FlareSolverr not reachable for HAProxy end-to-end test")

        parsed = requests.utils.urlparse(cls.base_url)
        fs_host = parsed.hostname or "127.0.0.1"
        fs_port = parsed.port or 8191

        cls.haproxy_port = _find_free_port()
        cls.haproxy_cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False)
        cls.haproxy_cfg.write(
            f"""global
    maxconn 4096

defaults
    mode http
    timeout connect 5s
    timeout client 60s
    timeout server 120s

frontend flaresolverr_frontend
    bind 127.0.0.1:{cls.haproxy_port}
    default_backend flaresolverr_backend

backend flaresolverr_backend
    balance hdr(X-FlareSolverr-Session)
    hash-type consistent
    option httpchk GET /health
    http-check expect status 200
    server fs1 {fs_host}:{fs_port} check
"""
        )
        cls.haproxy_cfg.close()
        cls.haproxy_cfg_path = cls.haproxy_cfg.name
        cls.haproxy_url = f"http://127.0.0.1:{cls.haproxy_port}"

        cls.haproxy_proc = subprocess.Popen(
            ["haproxy", "-f", cls.haproxy_cfg_path, "-db"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # wait for HAProxy to be ready
        for _ in range(30):
            try:
                requests.get(f"{cls.haproxy_url}/health", timeout=1)
                break
            except requests.exceptions.ConnectionError:
                time.sleep(0.2)
        else:
            cls.tearDownClass()
            raise RuntimeError("HAProxy did not start in time")

    @classmethod
    def tearDownClass(cls):
        if not getattr(cls, "_external_haproxy", False):
            if cls.haproxy_proc is not None:
                cls.haproxy_proc.terminate()
                try:
                    cls.haproxy_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    cls.haproxy_proc.kill()
            if cls.haproxy_cfg_path and os.path.exists(cls.haproxy_cfg_path):
                os.unlink(cls.haproxy_cfg_path)

        # clean up any session we created
        try:
            if cls.haproxy_url:
                requests.post(
                    f"{cls.haproxy_url}/v1",
                    json={"cmd": "sessions.destroy", "session": "haproxy-test-session"},
                    timeout=10,
                )
        except Exception:
            pass

    def _post_v1(self, payload: dict, headers: dict | None = None) -> dict:
        url = f"{self.haproxy_url}/v1"
        res = requests.post(url, json=payload, headers=headers or {}, timeout=120)
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_sessions_create_with_header(self):
        """sessions.create should accept session ID via X-FlareSolverr-Session header."""
        res = self._post_v1(
            {"cmd": "sessions.create"},
            headers={"X-FlareSolverr-Session": "haproxy-test-session"},
        )
        body = V1ResponseBase(res)
        self.assertEqual(body.status, STATUS_OK)
        self.assertEqual(body.session, "haproxy-test-session")

    def test_request_get_reuses_session_from_header(self):
        """request.get should reuse the session passed via X-FlareSolverr-Session header."""
        # ensure session exists
        create_res = self._post_v1(
            {"cmd": "sessions.create"},
            headers={"X-FlareSolverr-Session": "haproxy-test-session"},
        )
        self.assertEqual(create_res["status"], STATUS_OK)

        # now make a request using only the header (no body session)
        get_res = self._post_v1(
            {"cmd": "request.get", "url": "https://www.google.com", "maxTimeout": 30000},
            headers={"X-FlareSolverr-Session": "haproxy-test-session"},
        )
        body = V1ResponseBase(get_res)
        self.assertEqual(body.status, STATUS_OK)
        self.assertIn("Google", body.solution.response or "")

    def test_body_session_takes_precedence_over_header(self):
        """If both body session and header are present, body value wins."""
        # create both sessions
        self._post_v1(
            {"cmd": "sessions.create", "session": "body-session"},
            headers={"X-FlareSolverr-Session": "header-session"},
        )
        self._post_v1(
            {"cmd": "sessions.create", "session": "header-session"},
        )

        get_res = self._post_v1(
            {
                "cmd": "request.get",
                "url": "https://www.google.com",
                "maxTimeout": 30000,
                "session": "body-session",
            },
            headers={"X-FlareSolverr-Session": "header-session"},
        )
        body = V1ResponseBase(get_res)
        self.assertEqual(body.status, STATUS_OK)
        self.assertIn("Google", body.solution.response or "")

        # cleanup the extra session
        requests.post(
            f"{self.haproxy_url}/v1",
            json={"cmd": "sessions.destroy", "session": "body-session"},
            timeout=10,
        )

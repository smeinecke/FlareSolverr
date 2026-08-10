"""GPU/graphics identity diagnostic.

Collects the actual native backend, WebGL, WebGPU and cross-realm state for
FlareSolverr without adding any stealth.  Output is saved to a JSON file.

Run for the custom build (default):
    PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest \
        tests/integration/test_gpu_architecture.py -m integration -s

Run for a stock Chrome binary for comparison:
    PYTHONDONTWRITEBYTECODE=1 GPU_DIAG_VARIANT=stock CHROME_EXE_PATH=/usr/bin/google-chrome \
        uv run python -m pytest tests/integration/test_gpu_architecture.py -m integration -s
"""

import http.server
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import traceback

import pytest
import requests
import websocket

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from flaresolverr import utils  # noqa: E402

pytestmark = pytest.mark.integration

HTML = b"""<!doctype html>
<html><head><title>GPU diagnostic</title></head>
<body>
<p>FlareSolverr GPU architecture diagnostic</p>
<canvas id="c" width="1" height="1"></canvas>
</body></html>"""

GPU_PROBE_JS = """
(() => {
  const done = arguments[arguments.length - 1];

  const probeWebGL = (gl, label) => {
    if (!gl) return { present: false, label };
    const ext = gl.getExtension("WEBGL_debug_renderer_info") || {};
    return {
      present: true,
      label,
      VENDOR: gl.getParameter(gl.VENDOR),
      RENDERER: gl.getParameter(gl.RENDERER),
      VERSION: gl.getParameter(gl.VERSION),
      SHADING_LANGUAGE_VERSION: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
      UNMASKED_VENDOR: gl.getParameter(ext.UNMASKED_VENDOR_WEBGL),
      UNMASKED_RENDERER: gl.getParameter(ext.UNMASKED_RENDERER_WEBGL),
      MAX_TEXTURE_SIZE: gl.getParameter(gl.MAX_TEXTURE_SIZE),
      MAX_CUBE_MAP_TEXTURE_SIZE: gl.getParameter(gl.MAX_CUBE_MAP_TEXTURE_SIZE),
      MAX_RENDERBUFFER_SIZE: gl.getParameter(gl.MAX_RENDERBUFFER_SIZE),
      MAX_VIEWPORT_DIMS: gl.getParameter(gl.MAX_VIEWPORT_DIMS),
      MAX_VERTEX_ATTRIBS: gl.getParameter(gl.MAX_VERTEX_ATTRIBS),
      MAX_VERTEX_TEXTURE_IMAGE_UNITS: gl.getParameter(gl.MAX_VERTEX_TEXTURE_IMAGE_UNITS),
      MAX_TEXTURE_IMAGE_UNITS: gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS),
      MAX_COMBINED_TEXTURE_IMAGE_UNITS: gl.getParameter(gl.MAX_COMBINED_TEXTURE_IMAGE_UNITS),
      ALIASED_LINE_WIDTH_RANGE: gl.getParameter(gl.ALIASED_LINE_WIDTH_RANGE),
      ALIASED_POINT_SIZE_RANGE: gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE),
      MAX_VARYING_VECTORS: gl.getParameter(gl.MAX_VARYING_VECTORS),
      MAX_VERTEX_UNIFORM_VECTORS: gl.getParameter(gl.MAX_VERTEX_UNIFORM_VECTORS),
      MAX_FRAGMENT_UNIFORM_VECTORS: gl.getParameter(gl.MAX_FRAGMENT_UNIFORM_VECTORS),
      supportedExtensions: gl.getSupportedExtensions(),
    };
  };

  const probeWebGLContexts = (w) => {
    if (!w.document) return { webgl1: { present: false }, webgl2: { present: false } };
    const c1 = w.document.createElement("canvas");
    const c2 = w.document.createElement("canvas");
    const gl1 = c1.getContext("webgl") || c1.getContext("experimental-webgl");
    const gl2 = c2.getContext("webgl2");
    return { webgl1: probeWebGL(gl1, "webgl1"), webgl2: probeWebGL(gl2, "webgl2") };
  };

  const probeWebGPU = async (w) => {
    if (!w.navigator.gpu) return { present: false };
    try {
      const adapter = await w.navigator.gpu.requestAdapter();
      if (!adapter) return { present: true, adapter: false };
      const info = await adapter.requestAdapterInfo();
      const features = [...(adapter.features || [])];
      const limits = { ...Object.fromEntries(Object.entries(adapter.limits || {})) };
      return { present: true, adapter: true, info, features, limits };
    } catch (e) {
      return { present: true, adapter: false, error: e.message };
    }
  };

  const probeMedia = async (nav) => {
    if (!nav.mediaDevices || !nav.mediaDevices.enumerateDevices) return { present: false };
    try {
      const devices = await nav.mediaDevices.enumerateDevices();
      return {
        present: true,
        count: devices.length,
        devices: devices.map((d) => ({ kind: d.kind, label: d.label })),
      };
    } catch (e) {
      return { present: true, error: e.message };
    }
  };

  const collectWindow = (w) => ({
    innerWidth: w.innerWidth,
    innerHeight: w.innerHeight,
    outerWidth: w.outerWidth,
    outerHeight: w.outerHeight,
    devicePixelRatio: w.devicePixelRatio,
    visualViewport: w.visualViewport
      ? {
          width: w.visualViewport.width,
          height: w.visualViewport.height,
          scale: w.visualViewport.scale,
          offsetLeft: w.visualViewport.offsetLeft,
          offsetTop: w.visualViewport.offsetTop,
        }
      : null,
    screen: {
      width: w.screen.width,
      height: w.screen.height,
      availWidth: w.screen.availWidth,
      availHeight: w.screen.availHeight,
    },
  });

  const collectNavigator = (nav) => ({
    webdriver: nav.webdriver,
    typeof_webdriver: typeof nav.webdriver,
    userAgent: nav.userAgent,
    platform: nav.platform,
    language: nav.language,
    languages: Array.isArray(nav.languages) ? [...nav.languages] : nav.languages,
    hardwareConcurrency: nav.hardwareConcurrency,
    maxTouchPoints: nav.maxTouchPoints,
    userAgentData: nav.userAgentData
      ? { brands: nav.userAgentData.brands, mobile: nav.userAgentData.mobile, platform: nav.userAgentData.platform }
      : null,
  });

  const collectIntl = () => ({
    DateTimeFormat: (() => {
      try {
        const o = new Intl.DateTimeFormat().resolvedOptions();
        return { locale: o.locale, calendar: o.calendar, numberingSystem: o.numberingSystem, timeZone: o.timeZone };
      } catch (e) {
        return { error: e.message };
      }
    })(),
    NumberFormat: (() => {
      try {
        const o = new Intl.NumberFormat().resolvedOptions();
        return { locale: o.locale };
      } catch (e) {
        return { error: e.message };
      }
    })(),
  });

  const collectRealm = async (w) => ({
    navigator: collectNavigator(w.navigator),
    window: collectWindow(w),
    webgl: probeWebGLContexts(w),
    webgpu: await probeWebGPU(w),
    media: await probeMedia(w.navigator),
    intl: collectIntl(),
    performance_now: w.performance && w.performance.now ? w.performance.now.toString().slice(0, 80) : null,
  });

  const workerScript = `
    self.onmessage = async (e) => {
      const collectNavigator = (nav) => ({
        webdriver: nav.webdriver,
        typeof_webdriver: typeof nav.webdriver,
        userAgent: nav.userAgent,
        platform: nav.platform,
        language: nav.language,
        languages: Array.isArray(nav.languages) ? [...nav.languages] : nav.languages,
        hardwareConcurrency: nav.hardwareConcurrency,
        maxTouchPoints: nav.maxTouchPoints,
      });
      const probeWebGL = (gl) => {
        if (!gl) return { present: false };
        const ext = gl.getExtension("WEBGL_debug_renderer_info") || {};
        return {
          present: true,
          VENDOR: gl.getParameter(gl.VENDOR),
          RENDERER: gl.getParameter(gl.RENDERER),
          UNMASKED_VENDOR: gl.getParameter(ext.UNMASKED_VENDOR_WEBGL),
          UNMASKED_RENDERER: gl.getParameter(ext.UNMASKED_RENDERER_WEBGL),
          VERSION: gl.getParameter(gl.VERSION),
          SHADING_LANGUAGE_VERSION: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
          MAX_TEXTURE_SIZE: gl.getParameter(gl.MAX_TEXTURE_SIZE),
        };
      };
      const probeWebGPU = async () => {
        if (!navigator.gpu) return { present: false };
        const adapter = await navigator.gpu.requestAdapter();
        return { present: true, adapter: !!adapter, info: adapter ? await adapter.requestAdapterInfo() : null };
      };
      const probeMedia = async () => {
        if (!navigator.mediaDevices) return { present: false };
        const devices = await navigator.mediaDevices.enumerateDevices();
        return { present: true, count: devices.length };
      };
      const c1 = new OffscreenCanvas(1, 1);
      const c2 = new OffscreenCanvas(1, 1);
      self.postMessage({
        navigator: collectNavigator(navigator),
        webgl: {
          webgl1: probeWebGL(c1.getContext("webgl")),
          webgl2: probeWebGL(c2.getContext("webgl2")),
        },
        webgpu: await probeWebGPU(),
        media: await probeMedia(),
        performance_now: performance.now.toString().slice(0, 80),
      });
    };
  `;

  (async () => {
    const main = await collectRealm(window);

    let iframe = null;
    try {
      const el = document.createElement("iframe");
      el.src = "about:blank";
      await new Promise((resolve) => {
        el.onload = resolve;
        document.body.appendChild(el);
      });
      iframe = await collectRealm(el.contentWindow);
      document.body.removeChild(el);
    } catch (e) {
      iframe = { error: e.message };
    }

    let dedicated = { error: "not run" };
    try {
      const blob = new Blob([workerScript], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      const w = new Worker(url);
      dedicated = await new Promise((resolve) => {
        w.onmessage = (event) => resolve(event.data);
        w.onerror = (event) => resolve({ error: event.message });
        w.postMessage("go");
        setTimeout(() => resolve({ error: "timeout" }), 5000);
      });
    } catch (e) {
      dedicated = { error: e.message };
    }

    let shared = { error: "not run" };
    try {
      if (typeof SharedWorker !== "undefined") {
        const blob = new Blob([workerScript], { type: "application/javascript" });
        const url = URL.createObjectURL(blob);
        const sw = new SharedWorker(url);
        shared = await new Promise((resolve) => {
          sw.port.onmessage = (event) => resolve(event.data);
          sw.port.onerror = (event) => resolve({ error: event.message });
          sw.port.postMessage("go");
          sw.port.start();
          setTimeout(() => resolve({ error: "timeout" }), 5000);
        });
      } else {
        shared = { error: "SharedWorker not supported" };
      }
    } catch (e) {
      shared = { error: e.message };
    }

    done({ main, iframe, dedicated_worker: dedicated, shared_worker: shared });
  })();
})();
"""


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *args):
        pass


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server():
    port = _free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), _QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port, server


def _debug_port_and_browser_pid(driver):
    proc = getattr(driver, "_chrome_proc", None)
    if not proc:
        return None, None
    try:
        with open(f"/proc/{proc.pid}/cmdline", "rb") as f:
            cmdline = f.read().replace(b"\x00", b" ").decode()
        port = int(re.search(r"--remote-debugging-port=(\d+)", cmdline).group(1))
        return port, proc.pid
    except Exception:
        return None, None


def _find_gpu_process(user_data_dir):
    if not user_data_dir:
        return None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\x00", b" ").decode()
            if "--type=gpu-process" in cmd and user_data_dir in cmd:
                return cmd
        except OSError:
            pass
    return None


def _system_info(debug_port):
    try:
        ws_url = requests.get(f"http://127.0.0.1:{debug_port}/json/version", timeout=5).json()["webSocketDebuggerUrl"]
        ws = websocket.create_connection(ws_url)
        ws.send(json.dumps({"id": 1, "method": "SystemInfo.getInfo", "params": {}}))
        resp = json.loads(ws.recv())
        ws.close()
        return resp.get("result", {})
    except Exception as e:
        return {"error": str(e), "_trace": traceback.format_exc()}


def _reset_utils_state(variant_name, browser_executable_path):
    utils.CHROME_EXE_PATH = browser_executable_path
    utils.CHROME_MAJOR_VERSION = None
    utils.CHROME_FULL_VERSION = None
    if variant_name == "stock":
        utils._is_custom_chromium = lambda: False
        utils._CUSTOM_CHROMIUM = False
        os.environ["STEALTH_MODE"] = "off"
    else:
        os.environ["STEALTH_MODE"] = "standard"


class TestGpuArchitecture:
    @pytest.mark.integration
    def test_collect_gpu_identity(self):
        variant = os.environ.get("GPU_DIAG_VARIANT", "custom")
        browser_path = os.environ.get("CHROME_EXE_PATH") if variant == "stock" else None

        # Ensure remote debugging can connect from any origin for SystemInfo.
        extra = os.environ.get("CHROME_EXTRA_FLAGS", "")
        if "--remote-allow-origins" not in extra:
            os.environ["CHROME_EXTRA_FLAGS"] = f"{extra},--remote-allow-origins=*" if extra else "--remote-allow-origins=*"

        _reset_utils_state(variant, browser_path)

        driver = utils.get_webdriver()

        port, server = _start_server()
        page_url = f"http://127.0.0.1:{port}/"
        try:
            driver.get(page_url)
            page_data = driver.execute_async_script(GPU_PROBE_JS)

            debug_port, browser_pid = _debug_port_and_browser_pid(driver)
            system_info = _system_info(debug_port) if debug_port else {"error": "no debug port"}

            browser_cmdline = None
            if browser_pid:
                try:
                    with open(f"/proc/{browser_pid}/cmdline", "rb") as f:
                        browser_cmdline = f.read().replace(b"\x00", b" ").decode()
                except OSError:
                    pass

            user_data_dir = None
            if browser_cmdline:
                m = re.search(r"--user-data-dir=([^ ]+)", browser_cmdline)
                user_data_dir = m.group(1) if m else None

            out = {
                "variant": variant,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "chrome_version": driver.capabilities.get("browserVersion"),
                "user_agent": driver.execute_script("return navigator.userAgent"),
                "page_data": page_data,
                "system_info": system_info,
                "browser_command_line": browser_cmdline,
                "gpu_process_command_line": _find_gpu_process(user_data_dir),
            }

            out_path = os.environ.get("FLARESOLVERR_GPU_DIAG", f"/tmp/gpu_architecture_{variant}.json")
            os.makedirs(os.path.dirname(out_path) or "/tmp", exist_ok=True)
            with open(out_path, "w") as f:
                json.dump(out, f, indent=2, default=str)

            print(f"\nGPU diagnostic saved: {out_path}")
            print(json.dumps({k: v for k, v in out.items() if k in ("chrome_version", "user_agent", "system_info")}, indent=2, default=str))

            # No assertions: this is a data-collection test.
        finally:
            driver.quit()
            server.shutdown()

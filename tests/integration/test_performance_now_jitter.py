"""Integration test for Performance::now() bounded jitter semantics.

Verifies that Patch 13 does not inflate reported time with call frequency
while remaining monotonic and cross-realm consistent.
"""

import http.server
import os
import socket
import sys
import threading
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from flaresolverr import utils

pytestmark = pytest.mark.integration


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>FlareSolverr timing diagnostic</body></html>")

    def log_message(self, *args):
        pass


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


PERFORMANCE_NOW_SEMANTICS_SCRIPT = """
(() => {
  const done = arguments[arguments.length - 1];

  const MAX_JITTER = 2.5;  // ms, must match Patch 13 kMaxPerformanceNowJitterMs
  const TIGHT_LOOP_COUNT = 1000;
  const REAL_DELAY_MS = 200;

  const measureTightLoop = (count) => {
    const samples = new Array(count);
    const dateStart = Date.now();
    const first = performance.now();
    for (let i = 0; i < count; i++) {
      samples[i] = performance.now();
    }
    const last = samples[count - 1];
    const dateEnd = Date.now();

    let monotonic = true;
    let zeroDeltas = 0;
    let maxAdvance = 0;
    for (let i = 1; i < count; i++) {
      const diff = samples[i] - samples[i - 1];
      if (diff < 0) monotonic = false;
      if (diff === 0) zeroDeltas++;
      if (diff > maxAdvance) maxAdvance = diff;
    }

    return {
      first,
      last,
      reportedElapsed: last - first,
      dateElapsed: dateEnd - dateStart,
      monotonic,
      zeroDeltas,
      maxAdvance,
      count,
    };
  };

  const measureRealDelay = (delayMs) => {
    const perfStart = performance.now();
    const dateStart = Date.now();
    while (Date.now() - dateStart < delayMs) {}
    const perfEnd = performance.now();
    const dateEnd = Date.now();

    const perfElapsed = perfEnd - perfStart;
    const dateElapsed = dateEnd - dateStart;
    const timeOrigin = performance.timeOrigin;
    const lead = (timeOrigin + perfEnd) - dateEnd;

    return {
      perfElapsed,
      dateElapsed,
      diff: perfElapsed - dateElapsed,
      lead,
      timeOrigin,
    };
  };

  const runInContext = (ctx) => {
    const tight = measureTightLoop(TIGHT_LOOP_COUNT);
    const delay = measureRealDelay(REAL_DELAY_MS);
    return { tight, delay };
  };

  const runIframe = () => new Promise((resolve) => {
    try {
      const iframe = document.createElement("iframe");
      iframe.src = location.href;
      iframe.onload = () => {
        const win = iframe.contentWindow;
        resolve({ ...runInContext(win), source: "iframe" });
        document.body.removeChild(iframe);
      };
      document.body.appendChild(iframe);
    } catch (e) {
      resolve({ error: e.message });
    }
  });

  const blobUrl = (script) => URL.createObjectURL(new Blob([script], { type: "application/javascript" }));

  const dedicatedScript = `
    const MAX_JITTER = 2.5;
    const TIGHT_LOOP_COUNT = 1000;
    const REAL_DELAY_MS = 200;

    const measureTightLoop = (count) => {
      const samples = new Array(count);
      const dateStart = Date.now();
      const first = performance.now();
      for (let i = 0; i < count; i++) samples[i] = performance.now();
      const last = samples[count - 1];
      const dateEnd = Date.now();

      let monotonic = true;
      let zeroDeltas = 0;
      let maxAdvance = 0;
      for (let i = 1; i < count; i++) {
        const diff = samples[i] - samples[i - 1];
        if (diff < 0) monotonic = false;
        if (diff === 0) zeroDeltas++;
        if (diff > maxAdvance) maxAdvance = diff;
      }
      return { first, last, reportedElapsed: last - first, dateElapsed: dateEnd - dateStart, monotonic, zeroDeltas, maxAdvance, count };
    };

    const measureRealDelay = (delayMs) => {
      const perfStart = performance.now();
      const dateStart = Date.now();
      while (Date.now() - dateStart < delayMs) {}
      const perfEnd = performance.now();
      const dateEnd = Date.now();
      return {
        perfElapsed: perfEnd - perfStart,
        dateElapsed: dateEnd - dateStart,
        diff: (perfEnd - perfStart) - (dateEnd - dateStart),
        lead: (performance.timeOrigin + perfEnd) - dateEnd,
        timeOrigin: performance.timeOrigin,
      };
    };

    const result = { tight: measureTightLoop(TIGHT_LOOP_COUNT), delay: measureRealDelay(REAL_DELAY_MS), source: "dedicated_worker" };
    self.postMessage(result);
  `;

  const sharedScript = `
    self.onconnect = (e) => {
      const port = e.ports[0];
      const MAX_JITTER = 2.5;
      const TIGHT_LOOP_COUNT = 1000;
      const REAL_DELAY_MS = 200;

      const measureTightLoop = (count) => {
        const samples = new Array(count);
        const dateStart = Date.now();
        const first = performance.now();
        for (let i = 0; i < count; i++) samples[i] = performance.now();
        const last = samples[count - 1];
        const dateEnd = Date.now();

        let monotonic = true;
        let zeroDeltas = 0;
        let maxAdvance = 0;
        for (let i = 1; i < count; i++) {
          const diff = samples[i] - samples[i - 1];
          if (diff < 0) monotonic = false;
          if (diff === 0) zeroDeltas++;
          if (diff > maxAdvance) maxAdvance = diff;
        }
        return { first, last, reportedElapsed: last - first, dateElapsed: dateEnd - dateStart, monotonic, zeroDeltas, maxAdvance, count };
      };

      const measureRealDelay = (delayMs) => {
        const perfStart = performance.now();
        const dateStart = Date.now();
        while (Date.now() - dateStart < delayMs) {}
        const perfEnd = performance.now();
        const dateEnd = Date.now();
        return {
          perfElapsed: perfEnd - perfStart,
          dateElapsed: dateEnd - dateStart,
          diff: (perfEnd - perfStart) - (dateEnd - dateStart),
          lead: (performance.timeOrigin + perfEnd) - dateEnd,
          timeOrigin: performance.timeOrigin,
        };
      };

      const result = { tight: measureTightLoop(TIGHT_LOOP_COUNT), delay: measureRealDelay(REAL_DELAY_MS), source: "shared_worker" };
      port.postMessage(result);
    };
  `;

  const runWorker = (script) => new Promise((resolve) => {
    try {
      const w = new Worker(blobUrl(script));
      w.onmessage = (e) => resolve(e.data);
      w.onerror = (e) => resolve({ error: e.message });
    } catch (e) {
      resolve({ error: e.message });
    }
  });

  const runSharedWorker = (script) => new Promise((resolve) => {
    try {
      const sw = new SharedWorker(blobUrl(script));
      sw.port.onmessage = (e) => resolve(e.data);
      sw.port.onerror = (e) => resolve({ error: e.message });
      sw.port.start();
    } catch (e) {
      resolve({ error: e.message });
    }
  });

  Promise.all([
    Promise.resolve({ ...runInContext(self), source: "main" }),
    runIframe(),
    runWorker(dedicatedScript),
    runSharedWorker(sharedScript),
  ]).then(([main, iframe, dedicated, shared]) => {
    done({ main, iframe, dedicated, shared, maxJitterMs: MAX_JITTER });
  });
})();
"""


class TestPerformanceNowSemantics(unittest.TestCase):
    """Patch 13 must provide bounded timing jitter without call-frequency drift."""

    def test_performance_now_is_bounded_monotonic_and_coherent(self):
        port = _find_free_port()
        server = http.server.HTTPServer(("127.0.0.1", port), _QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        driver = utils.get_webdriver()
        try:
            driver.get(f"http://127.0.0.1:{port}/")
            result = driver.execute_async_script(PERFORMANCE_NOW_SEMANTICS_SCRIPT)

            for realm_name, data in [
                ("main", result["main"]),
                ("iframe", result["iframe"]),
                ("dedicated_worker", result["dedicated"]),
                ("shared_worker", result["shared"]),
            ]:
                with self.subTest(realm=realm_name):
                    self.assertNotIn("error", data, data.get("error"))
                    tight = data["tight"]
                    delay = data["delay"]
                    k = result["maxJitterMs"]

                    # Monotonicity.
                    self.assertTrue(tight["monotonic"], "samples must not step backwards")

                    # No call-frequency inflation.
                    # The reported time over a tight loop must not exceed real wall
                    # elapsed time plus the maximum jitter (plus a tolerance for
                    # the coarse Date.now() resolution and scheduling noise).
                    reported_elapsed = tight["reportedElapsed"]
                    date_elapsed = max(tight["dateElapsed"], 0)
                    self.assertLessEqual(
                        reported_elapsed,
                        date_elapsed + k + 2.0,
                        f"reported elapsed {reported_elapsed} inflated beyond bound "
                        f"for date elapsed {date_elapsed}",
                    )

                    # Real delay coherence.
                    self.assertLessEqual(
                        abs(delay["diff"]),
                        k + 5.0,
                        f"performance.now delta {delay['perfElapsed']} diverged from "
                        f"Date.now delta {delay['dateElapsed']}",
                    )

                    # Maximum lead bound.
                    self.assertLessEqual(
                        delay["lead"],
                        k + 2.0,
                        f"performance.now lead {delay['lead']} exceeded jitter bound",
                    )

        finally:
            driver.quit()
            server.shutdown()

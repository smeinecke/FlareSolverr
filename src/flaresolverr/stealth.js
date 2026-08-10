/**
 * stealth.js - minimal JS-only patch layer for custom Chromium builds.
 *
 * Custom Chromium handles the heavy lifting natively:
 *   - navigator.webdriver (gated by --disable-blink-features=AutomationControlled)
 *   - navigator.languages / language (--stealth-navigator-languages)
 *   - user agent and user-agent client hints (--user-agent command line)
 *   - WebGL vendor/renderer (--webgl-unmasked-*)
 *   - visualViewport coherence (--stealth-viewport-size)
 *   - mediaDevices.enumerateDevices (--stealth-no-media-devices returns an empty
 *     list natively)
 *
 * Two remaining JS-only defences are still injected via CDP:
 *   - performance.now: timing probes build a linear regression between
 *     performance.now() and Date.now(); an unjittered, microsecond-precise
 *     headless timer produces a near-perfect correlation. A small, bounded,
 *     monotonic noise floor breaks the correlation while leaving the API usable.
 *     The current implementation accumulates jitter across calls; a native
 *     Chromium/V8 patch is the long-term replacement.
 *   - Error.prepareStackTrace: a narrow guard that blocks CDP stack-trace
 *     probes from installing a non-native handler while keeping the property
 *     in its default undefined state. There is no reasonable source-level
 *     alternative for this without changing V8's public Error API.
 */
(() => {
  try {
    // Block CDP stack-trace probes from installing a non-native
    // Error.prepareStackTrace handler while keeping it undefined, matching
    // the default state of a real browser.
    try {
      Object.defineProperty(Error, "prepareStackTrace", {
        get: () => undefined,
        set: function () {},
        configurable: false,
        enumerable: false,
      });
    } catch (_) {}

    // Add bounded, monotonic jitter to performance.now to defeat timing probes
    // that rely on a perfectly linear, high-resolution headless timer.
    try {
      const origNow = performance.now.bind(performance);
      let last = 0;
      const nowFn = function () {
        const t = origNow();
        const jitter = Math.random() * 2.5;
        last = Math.max(t, last + jitter);
        return last;
      };
      nowFn.toString = function () {
        return "function now() { [native code] }";
      };
      Object.defineProperty(Performance.prototype, "now", {
        value: nowFn,
        configurable: false,
        writable: false,
      });
    } catch (_) {}
  } catch (_) {}
})();

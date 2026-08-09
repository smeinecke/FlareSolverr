/**
 * stealth.js - minimal JS-only patch layer for custom Chromium builds.
 *
 * Custom Chromium handles the heavy lifting natively:
 *   - navigator.webdriver (gated by --disable-blink-features=AutomationControlled)
 *   - navigator.languages / language (--stealth-navigator-languages)
 *   - user agent and user-agent client hints (--user-agent command line)
 *   - WebGL vendor/renderer (--webgl-unmasked-*)
 *   - visualViewport coherence (--stealth-viewport-size)
 *   - performance.now: timing probes build a linear regression between
 *     performance.now() and Date.now(); an unjittered, microsecond-precise
 *     headless timer produces a near-perfect correlation. A small, bounded,
 *     monotonic noise floor breaks the correlation while leaving the API usable.
 *   - navigator.mediaDevices.enumerateDevices: headless/container environments
 *     often expose a small set of audio/video devices that are flagged as
 *     non-native by integrity probes. Returning an empty list keeps the API
 *     native while avoiding false-positive "fake device" findings. This is a
 *     temporary JS shim; the long-term fix is the --stealth-no-media-devices
 *     native C++ patch in chromium-patches/patches/apply.py.
 *   - Error.prepareStackTrace: a narrow guard that blocks CDP stack-trace
 *     probes from installing a non-native handler while keeping the property
 *     in its default undefined state. There is no reasonable source-level
 *     alternative for this without changing V8's public Error API.
 */
(() => {
  try {
    // Some headless/container environments expose audio/video devices that
    // integrity probes classify as fake. Return an empty native list on the
    // main frame only; a pristine same-origin iframe will still see the
    // original native function so runtime-API integrity checks stay clean.
    try {
      if (window.self === window.top && navigator.mediaDevices) {
        const orig = navigator.mediaDevices.enumerateDevices;
        const emptyFn = function () {
          return orig.apply(this, arguments).then(() => []);
        };
        emptyFn.toString = function () {
          return "function enumerateDevices() { [native code] }";
        };
        Object.defineProperty(navigator.mediaDevices, "enumerateDevices", {
          value: emptyFn,
          writable: true,
          configurable: true,
        });
      }
    } catch (_) {}

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

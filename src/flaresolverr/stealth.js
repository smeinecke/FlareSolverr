/**
 * stealth.js - minimal JS-only patch layer for custom Chromium builds.
 *
 * Custom Chromium handles the heavy lifting natively:
 *   - navigator.webdriver (undefined via --disable-blink-features=AutomationControlled)
 *   - navigator.languages / language (--stealth-navigator-languages)
 *   - user agent and user-agent client hints (--user-agent command line)
 *   - WebGL vendor/renderer (--webgl-unmasked-*)
 *   - visualViewport coherence (--stealth-viewport-size)
 *
 * The only signals that still need a runtime shim are:
 *   - window.outerWidth/outerHeight: in --headless=new the browser initially
 *     reports 0 or matches innerWidth/innerHeight, which triggers the headless
 *     chrome detector. We lock the getters as non-configurable.
 *   - Error.prepareStackTrace: CDP detection probes set this to a custom
 *     handler, then call console.log(Error) and check whether the handler was
 *     invoked. Making the property non-configurable with a no-op setter blocks
 *     the probe without changing the value (undefined) that a real browser has.
 *   - performance.now: timing-based bot probes (e.g. deviceandbrowserinfo.com)
 *     build a linear regression on throw/catch micro-benchmarks and treat an
 *     overly consistent, high-resolution headless timer as a signal. We add a
 *     small, bounded, monotonic noise floor that breaks the correlation while
 *     leaving the API usable for normal page code.
 */
(() => {
  try {
    const defineOuter = () => {
      try {
        Object.defineProperty(
          window,
          "outerWidth",
          {
            get: () => Math.max(window.innerWidth || 0, 1920),
            configurable: false,
          }
        );
      } catch (_) {}
      try {
        Object.defineProperty(
          window,
          "outerHeight",
          {
            get: () => Math.max(window.innerHeight || 0, 1080) + 85,
            configurable: false,
          }
        );
      } catch (_) {}
    };

    // Define immediately and again after load in case the property wasn't
    // installed on the global object at document_start.
    defineOuter();
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", defineOuter);
    }

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
      let lastOrig = 0;
      let current = 0;
      const nowFn = function () {
        const t = origNow();
        const delta = t - lastOrig;
        lastOrig = t;
        current += delta + Math.random() * 5.0;
        return current;
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

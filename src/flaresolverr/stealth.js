/**
 * stealth.js - minimal JS-only patch layer for custom Chromium builds.
 *
 * Custom Chromium handles the heavy lifting natively:
 *   - navigator.webdriver (gated by --disable-blink-features=AutomationControlled)
 *   - navigator.languages / language (--stealth-navigator-languages)
 *   - user agent and user-agent client hints (--user-agent command line)
 *   - WebGL vendor/renderer (--webgl-unmasked-*)
 *   - visualViewport coherence (--stealth-viewport-size)
 *   - performance.now (no JS override; timing jitter is a low-value,
 *     easily-detectable signal that is not worth emulating)
 *
 * The only signals that still need a runtime shim are:
 *   - window.outerWidth/outerHeight: in --headless=new the browser may report
 *     values that do not include the window chrome. The getters are locked to
 *     plausible desktop dimensions while the native fix is being upstreamed.
 *   - Error.prepareStackTrace: a narrow guard that blocks CDP stack-trace
 *     probes from installing a non-native handler while keeping the property
 *     in its default undefined state. There is no reasonable source-level
 *     alternative for this without changing V8's public Error API.
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
  } catch (_) {}
})();

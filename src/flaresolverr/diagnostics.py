"""Browser consistency diagnostics for the custom Chromium build.

These utilities collect native browser state from the main window, iframes,
dedicated workers and shared workers without modifying page state. They are
intended for development and integration validation, not for runtime stealth.
"""

import json
from typing import Any

from selenium.webdriver.chrome.webdriver import WebDriver

BROWSER_CONSISTENCY_SCRIPT = """
(() => {
  const done = arguments[arguments.length - 1];
  const collectNavigator = (nav) => ({
    webdriver: nav.webdriver,
    typeof_webdriver: typeof nav.webdriver,
    userAgent: nav.userAgent,
    platform: nav.platform,
    language: nav.language,
    languages: Array.isArray(nav.languages) ? [...nav.languages] : nav.languages,
    hardwareConcurrency: nav.hardwareConcurrency,
    userAgentData: nav.userAgentData ? {
      brands: nav.userAgentData.brands,
      mobile: nav.userAgentData.mobile,
      platform: nav.userAgentData.platform,
    } : null,
  });

  const collectWindow = (w) => ({
    outerWidth: w.outerWidth,
    outerHeight: w.outerHeight,
    innerWidth: w.innerWidth,
    innerHeight: w.innerHeight,
    screen: {
      width: w.screen.width,
      height: w.screen.height,
      availWidth: w.screen.availWidth,
      availHeight: w.screen.availHeight,
    },
    visualViewport: w.visualViewport ? {
      width: w.visualViewport.width,
      height: w.visualViewport.height,
      scale: w.visualViewport.scale,
      offsetLeft: w.visualViewport.offsetLeft,
      offsetTop: w.visualViewport.offsetTop,
      pageLeft: w.visualViewport.pageLeft,
      pageTop: w.visualViewport.pageTop,
    } : null,
  });

  const probeAPIs = () => {
    const desc = (obj, name) => {
      const d = Object.getOwnPropertyDescriptor(obj, name);
      if (!d) return null;
      return {
        own: true,
        get: d.get ? d.get.toString().slice(0, 80) : null,
        set: d.set ? d.set.toString().slice(0, 80) : null,
        value: d.value,
        configurable: d.configurable,
        enumerable: d.enumerable,
      };
    };
    const protoDesc = (proto, name) => {
      const d = Object.getOwnPropertyDescriptor(proto, name);
      if (!d) return null;
      return {
        own: false,
        get: d.get ? d.get.toString().slice(0, 80) : null,
        set: d.set ? d.set.toString().slice(0, 80) : null,
        value: d.value,
        configurable: d.configurable,
        enumerable: d.enumerable,
      };
    };

    return {
      Worker: {
        own: desc(window, "Worker"),
        prototype: typeof Worker !== "undefined" ? Worker.toString().slice(0, 80) : null,
      },
      navigator_language: {
        language: protoDesc(Navigator.prototype, "language"),
        languages: protoDesc(Navigator.prototype, "languages"),
      },
      permissions_query: {
        own: desc(navigator.permissions, "query"),
        prototype: protoDesc(Permissions.prototype, "query"),
      },
      enumerateDevices: {
        own: desc(navigator.mediaDevices, "enumerateDevices"),
        prototype: protoDesc(MediaDevices.prototype, "enumerateDevices"),
      },
      webgl_getParameter: typeof WebGLRenderingContext !== "undefined" ? {
        own: desc(WebGLRenderingContext.prototype, "getParameter"),
        native_string: WebGLRenderingContext.prototype.getParameter.toString().slice(0, 80),
      } : null,
      error_prepareStackTrace: {
        own: desc(Error, "prepareStackTrace"),
        value: Error.prepareStackTrace,
      },
    };
  };

  const main = {
    navigator: collectNavigator(navigator),
    window: collectWindow(window),
    apis: probeAPIs(),
  };

  let iframe = null;
  try {
    const iframeEl = document.createElement("iframe");
    iframeEl.style.display = "none";
    document.body.appendChild(iframeEl);
    iframe = {
      navigator: collectNavigator(iframeEl.contentWindow.navigator),
      window: collectWindow(iframeEl.contentWindow),
    };
    document.body.removeChild(iframeEl);
  } catch (e) {
    iframe = { error: e.message };
  }

  const toTrustedScriptURL = (url) => {
    try {
      if (typeof trustedTypes !== "undefined" && trustedTypes.createPolicy) {
        const policy = trustedTypes.createPolicy("fs-diag", {
          createScriptURL: (s) => s,
        });
        return policy.createScriptURL(url);
      }
    } catch (_) {}
    return url;
  };

  const runWorker = (script) => new Promise((resolve) => {
    try {
      const blob = new Blob([script], { type: "application/javascript" });
      const url = toTrustedScriptURL(URL.createObjectURL(blob));
      const w = new Worker(url);
      w.onmessage = (e) => resolve({ ok: e.data });
      w.onerror = (e) => resolve({ error: e.message });
    } catch (e) {
      resolve({ error: e.message });
    }
  });

  const workerScript = `
    self.postMessage(({
      navigator: {
        webdriver: navigator.webdriver,
        typeof_webdriver: typeof navigator.webdriver,
        userAgent: navigator.userAgent,
        platform: navigator.platform,
        language: navigator.language,
        languages: Array.isArray(navigator.languages) ? [...navigator.languages] : navigator.languages,
        hardwareConcurrency: navigator.hardwareConcurrency,
      },
    }));
  `;

  const sharedWorkerScript = `
    self.onconnect = (e) => {
      const port = e.ports[0];
      port.postMessage(({
        navigator: {
          webdriver: navigator.webdriver,
          typeof_webdriver: typeof navigator.webdriver,
          userAgent: navigator.userAgent,
          platform: navigator.platform,
          language: navigator.language,
          languages: Array.isArray(navigator.languages) ? [...navigator.languages] : navigator.languages,
          hardwareConcurrency: navigator.hardwareConcurrency,
        },
      }));
    };
  `;

  return new Promise((resolve) => {
    (async () => {
      const worker = await runWorker(workerScript);
      let shared = null;
      try {
        if (typeof SharedWorker !== "undefined") {
          const blob = new Blob([sharedWorkerScript], { type: "application/javascript" });
          const url = toTrustedScriptURL(URL.createObjectURL(blob));
          const sw = new SharedWorker(url);
          shared = await new Promise((r) => {
            sw.port.onmessage = (e) => r({ ok: e.data });
            sw.port.onerror = (e) => r({ error: e.message });
            sw.port.start();
            setTimeout(() => r({ error: "timeout" }), 2000);
          });
        } else {
          shared = { error: "SharedWorker not supported" };
        }
      } catch (e) {
        shared = { error: e.message };
      }

      done({
        main,
        iframe,
        dedicated_worker: worker,
        shared_worker: shared,
      });
    })();
  });
})();
"""


def collect_browser_consistency(driver: WebDriver, page_url: str | None = None) -> dict[str, Any]:
    """Execute the consistency diagnostic and return the parsed result.

    Args:
        driver: A Selenium WebDriver connected to a Chromium instance.
        page_url: Optional URL to load before running the diagnostic. A regular
            http/https origin avoids Trusted Types and origin restrictions that
            can prevent Worker/SharedWorker construction from data: URLs.
    """
    if page_url:
        driver.get(page_url)
    elif not driver.current_url or driver.current_url == "about:blank":
        driver.get("data:text/html,<html><body></body></html>")
    driver.execute_script("return document.body")  # ensure a body exists
    result = driver.execute_async_script(BROWSER_CONSISTENCY_SCRIPT)
    if isinstance(result, str):
        return json.loads(result)
    return result

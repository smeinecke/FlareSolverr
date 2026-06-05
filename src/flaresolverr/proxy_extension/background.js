// Background service worker to manage Chrome proxy settings dynamically.
// Supports both authenticated and unauthenticated proxies via chrome.proxy API.

var FLARESOLVERR_PROXY_KEY = "flaresolverrProxy";
var currentAuth = null;

/**
 * Apply proxy settings to Chrome.
 * @param {Object} proxyConfig - The proxy configuration object.
 */
function applyProxyConfig(proxyConfig, callback) {
    chrome.proxy.settings.set(
        { value: proxyConfig, scope: "regular" },
        function() {
            if (chrome.runtime.lastError) {
                callback({ success: false, error: chrome.runtime.lastError.message });
            } else {
                callback({ success: true });
            }
        }
    );
}

/**
 * Restore proxy config from storage on startup.
 */
function restoreProxyFromStorage() {
    chrome.storage.local.get([FLARESOLVERR_PROXY_KEY, "flaresolverrProxyAuth"], function(result) {
        var config = result[FLARESOLVERR_PROXY_KEY];
        currentAuth = result.flaresolverrProxyAuth || null;
        if (config) {
            applyProxyConfig(config, function() {});
        } else {
            // Default to direct (no proxy)
            applyProxyConfig({ mode: "direct" }, function() {});
        }
    });
}

// Restore on startup
restoreProxyFromStorage();

// Handle messages from content script or extension pages
chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {
    if (!request || !request.mode) {
        sendResponse({ success: false, error: "Missing mode" });
        return false;
    }

    try {
        if (request.mode === "direct") {
            applyProxyConfig({ mode: "direct" }, function(result) {
                if (result.success) {
                    currentAuth = null;
                    chrome.storage.local.remove([FLARESOLVERR_PROXY_KEY]);
                    chrome.storage.local.remove(["flaresolverrProxyAuth"]);
                }
                sendResponse(result);
            });
        } else if (request.mode === "fixed_servers") {
            var proxyConfig = {
                mode: "fixed_servers",
                rules: request.rules
            };
            var newAuth = (request.auth && request.auth.username) ? request.auth : null;
            applyProxyConfig(proxyConfig, function(result) {
                if (result.success) {
                    currentAuth = newAuth;
                    chrome.storage.local.set({ [FLARESOLVERR_PROXY_KEY]: proxyConfig });
                    if (currentAuth) {
                        chrome.storage.local.set({ flaresolverrProxyAuth: currentAuth });
                    } else {
                        chrome.storage.local.remove(["flaresolverrProxyAuth"]);
                    }
                }
                sendResponse(result);
            });
        } else {
            sendResponse({ success: false, error: "Unknown mode: " + request.mode });
        }
    } catch (err) {
        sendResponse({ success: false, error: err.message });
    }
    return true;
});

// Handle proxy authentication
chrome.webRequest.onAuthRequired.addListener(
    function(details, callbackFn) {
        // currentAuth is updated synchronously in onMessage so there is never
        // a race between ACK and the first onAuthRequired event.
        if (currentAuth && currentAuth.username) {
            callbackFn({
                authCredentials: {
                    username: currentAuth.username,
                    password: currentAuth.password || ""
                }
            });
            return;
        }
        // Fallback to storage (e.g. service worker restart).
        chrome.storage.local.get(["flaresolverrProxyAuth"], function(result) {
            var auth = result.flaresolverrProxyAuth;
            if (auth && auth.username) {
                currentAuth = auth;
                callbackFn({
                    authCredentials: {
                        username: auth.username,
                        password: auth.password || ""
                    }
                });
            } else {
                callbackFn();
            }
        });
    },
    { urls: ["<all_urls>"] },
    ["asyncBlocking"]
);

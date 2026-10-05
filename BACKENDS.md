# Pluggable Backends

FlareSolverr supports multiple browser automation backends via the `DRIVER_BACKEND` environment variable. The default backend is `undetected_chromedriver`, which provides the most complete feature set (CDP commands, custom Chromium builds, stealth patches).

Alternative backends use a `BrowserContext` protocol facade that abstracts Selenium and Playwright operations behind a common interface. This allows features like browser actions, JavaScript injection, and session management to work across all backends without code changes.

## Quick Start

```bash
# Default (undetected-chromedriver)
flaresolverr

# Use Playwright
DRIVER_BACKEND=playwright flaresolverr

# Use Camoufox
DRIVER_BACKEND=camoufox flaresolverr

# Use SeleniumBase
DRIVER_BACKEND=seleniumbase flaresolverr
```

## Available Backends

| Backend | Driver | Type | CDP Support | Stealth | Notes |
| ------- | ------ | ---- | ----------- | ------- | ----- |
| `undetected_chromedriver` | Selenium | Chrome/Chromium | Full | Custom C++ patches + CDP JS | Default. Best compatibility. Custom Chromium hardening on amd64. |
| `playwright` | Playwright | Chromium | None | `--disable-blink-features=AutomationControlled` | Lightweight, fast startup. No CDP-dependent features. |
| `camoufox` | Playwright | Camoufox | None | Built-in anti-detect | Requires `camoufox` Python package (MIT, open-source). Advanced anti-fingerprinting. |
| `seleniumbase` | Selenium | Chrome | Full (passthrough) | UC mode | Requires `seleniumbase` package installed separately (pins `selenium==4.49.x`). |

## Environment Variable

| Name | Default | Description |
| ---- | ------- | ----------- |
| `DRIVER_BACKEND` | `undetected_chromedriver` | Selects the browser backend. Valid values: `undetected_chromedriver`, `custom_chromium` (alias for the same built-in Chromium path), `playwright`, `camoufox`, `seleniumbase`. |
| `PLAYWRIGHT_CHROME_EXECUTABLE_PATH` | none | Playwright backend only: launch this browser binary instead of Playwright's downloaded Chromium. If unset and no Playwright browser is installed, the bundled/system Chrome is used as a fallback. |
| `FLARESOLVERR_SINGLE_THREADED` | false | Run the API server on the single-threaded wsgiref adapter instead of waitress. Intended for testing Playwright-family backends whose contexts are not thread-safe. |

## Backend Details

### undetected_chromedriver (Default)

The original and most feature-complete backend. Uses [undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver) with additional stealth patches.

**Features:**
- Full CDP command support (`sessions.cdp`, `scriptInject`, custom headers, media blocking)
- Custom C++-patched Chromium builds (amd64 only) with native anti-detection
- CDP-based JavaScript stealth injection for other architectures
- Proxy support via Chrome extensions or command-line flags
- Session persistence and locking

**Limitations:**
- Higher memory usage than Playwright alternatives
- Chrome process management is more complex

### Playwright

A lightweight backend using [Playwright](https://playwright.dev/python/) Chromium. Good for environments where Playwright is already available or when fast startup is desired.

**Features:**
- Fast browser startup
- All core FlareSolverr features (requests, sessions, actions, cookies, screenshots)
- Cross-platform (works on amd64, arm64, etc.)

**Limitations:**
- **No arbitrary CDP support** — unknown CDP commands raise `NotImplementedError`, but the most common ones are translated to Playwright equivalents:
  - `scriptInject` → `page.add_init_script()`
  - `disableMedia` → `page.route()` with abort
  - Custom headers → `page.set_extra_http_headers()`
  - `sessions.cdp` still raises for commands outside the translation list
- JavaScript execution via `execute_script` and action `eval` works normally

**Install:**
```bash
pip install "flaresolverr[playwright]"
playwright install chromium
```

### Camoufox

Uses [Camoufox](https://camoufox.com/), a Playwright-based browser with advanced anti-fingerprinting built-in.

**Features:**
- Advanced anti-detection (WebGL spoofing, canvas noise, font randomization, etc.)
- No additional stealth patches needed
- Fast startup

**Limitations:**
- **No arbitrary CDP support** — same translation layer as Playwright (see above)
- Requires `camoufox` Python package

**Install:**
```bash
pip install "flaresolverr[camoufox]"
```

### SeleniumBase

Uses [SeleniumBase](https://github.com/mdmintz/SeleniumBase) Driver with UC mode.

**Features:**
- Simpler setup for users already familiar with SeleniumBase
- UC mode provides basic anti-detection
- Full CDP support — `sessions.cdp`, `scriptInject`, `disableMedia`, and custom headers pass through to the real ChromeDriver

**Limitations:**
- Less tested than the default backend
- Pins `selenium==4.49.x`, which conflicts with the main dependency set (`selenium==4.50.0`) — it must be installed in a dedicated environment

**Install:**
```bash
pip install "seleniumbase>=4.30"
# Note: SeleniumBase pins selenium==4.49.x, which conflicts with the main
# dependency set. Install it in a dedicated environment/container; it is
# intentionally not a flaresolverr extra.
```

## Feature Matrix

| Feature | undetected_chromedriver | Playwright | Camoufox | SeleniumBase |
| ------- | ---------------------- | ---------- | -------- | ------------ |
| `request.get` | ✅ | ✅ | ✅ | ✅ |
| `request.post` | ✅ | ✅ | ✅ | ✅ |
| `postDataRaw` | ✅ | ✅* | ✅* | ✅ |
| `sessions.create` | ✅ | ✅ | ✅ | ✅ |
| `sessions.destroy` | ✅ | ✅ | ✅ | ✅ |
| `sessions.get` | ✅ | ✅ | ✅ | ✅ |
| `sessions.eval` | ✅ | ✅ | ✅ | ✅ |
| `sessions.click` | ✅ | ✅ | ✅ | ✅ |
| `sessions.action` | ✅ | ✅ | ✅ | ✅ |
| `sessions.screenshot` | ✅ | ✅ | ✅ | ✅ |
| `sessions.network` | ✅ | ⚠️ | ⚠️ | ✅ |
| `sessions.cdp` | ✅ | ⚠️ | ⚠️ | ✅ |
| `scriptInject` | ✅ | ✅ | ✅ | ✅ |
| `disableMedia` | ✅ | ✅ | ✅ | ✅ |
| Custom headers via `headers` | ✅ | ✅ | ✅ | ✅ |
| Proxy support | ✅ | ✅ | ✅ | ✅ |
| Cookie handling | ✅ | ✅ | ✅ | ✅ |
| Browser actions | ✅ | ✅ | ✅ | ✅ |
| Stealth mode | Custom patches | Basic flags | Built-in | UC mode |
| Cloudflare managed challenge | ✅ | ❌ ¹ | ✅ ² | ✅ |
| Embedded Turnstile widget | ✅ | ❌ ³ | ✅ | ❌ ³ |

* `postDataRaw` on Playwright/Camoufox uses JavaScript XHR fallback instead of CDP `Fetch.continueRequest`.

¹ On Playwright the interstitial's Turnstile frame never mounts
(`window.frames.length == 0` in the challenge-state probe), so nothing can be
clicked and automatic verification never completes — the request times out.
Verified against scrapingcourse.com's managed challenge.

² Camoufox mounts the interstitial widget inside a closed shadow root — it is
invisible to `document.querySelectorAll('iframe')` but visible via
`window.frames`. The challenge-state probe detects this case
(`hiddenFrameCount`) and the TAB+SPACE verify click clears the challenge;
verified against scrapingcourse.com's managed challenge.

³ Widget is detected (`input[name='cf-turnstile-response']`) but no token is
produced within the timeout. Verified against scrapingcourse.com's
`/login/cf-turnstile` target. Camoufox obtained a token in ~8s on the same target.

Challenge-solving results are empirical (scrapingcourse.com targets) and
site-dependent — treat them as the current known state, not a guarantee.

## Troubleshooting

### Backend not found

```
ValueError: Unknown driver backend: 'playwright'. Valid backends: ['custom_chromium', 'undetected_chromedriver']
```

**Cause:** The backend package is not installed (uninstalled optional backends do not register, so they do not appear in the valid list).

**Fix:** Install the required package:
```bash
# Playwright
pip install "flaresolverr[playwright]" && playwright install chromium

# Camoufox
pip install "flaresolverr[camoufox]"

# SeleniumBase
pip install "seleniumbase>=4.30"  # pins selenium==4.49.x; install separately
```

### CDP command not supported

```
NotImplementedError: CDP command 'Debugger.enable' is not supported by the Playwright backend
```

**Cause:** You called a CDP command that is not in the translation layer.

**Fix:** The Playwright and Camoufox backends translate the most common CDP commands to Playwright equivalents:
- `Page.addScriptToEvaluateOnNewDocument` → `page.add_init_script()`
- `Emulation.setUserAgentOverride` → `page.set_extra_http_headers()` + `navigator.userAgent` init-script override
- `Network.setBlockedURLs` → `page.route()` with abort
- `Network.setExtraHTTPHeaders` → `page.set_extra_http_headers()`
- `Network.enable` → no-op

Arbitrary CDP commands (e.g., `Debugger.enable`, `Runtime.evaluate`) still raise `NotImplementedError`. Switch to `undetected_chromedriver` if you need full CDP support.

### Playwright browser fails to launch

```
browserType.launch: Executable doesn't exist at /home/user/.cache/ms-playwright/chromium-...
```

**Fix:** Run `playwright install chromium` to download browser binaries. If Playwright's
Chromium is not installed, the backend automatically falls back to the bundled/system
Chrome (`utils.get_chrome_exe_path()`); set `PLAYWRIGHT_CHROME_EXECUTABLE_PATH` to pick
a specific binary.

### Camoufox browser fails to launch

Camoufox ships its own patched Firefox build, downloaded on first use. If launch fails
with a missing-executable error, run `python -m camoufox fetch` (or reinstall the
package) to fetch the browser binary.

## Docker

Backend-specific Dockerfiles are available for CI/testing:

```bash
# Default UC backend image
docker build -f Dockerfile.backend-uc -t flaresolverr:uc .

# Playwright backend image
docker build -f Dockerfile.backend-playwright -t flaresolverr:playwright .

# Camoufox backend image
docker build -f Dockerfile.backend-camoufox -t flaresolverr:camoufox .

# SeleniumBase backend image
docker build -f Dockerfile.backend-seleniumbase -t flaresolverr:seleniumbase .
```

See `docker-compose.local.yml` for multi-backend orchestration examples.

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
| `camoufox` | Playwright | Camoufox | None | Built-in anti-detect | Requires `camoufox` Python package. Premium anti-fingerprinting. |
| `seleniumbase` | Selenium | Chrome | Partial | UC mode | Requires `seleniumbase` package. Simpler setup for some users. |

## Environment Variable

| Name | Default | Description |
| ---- | ------- | ----------- |
| `DRIVER_BACKEND` | `undetected_chromedriver` | Selects the browser backend. Valid values: `undetected_chromedriver`, `playwright`, `camoufox`, `seleniumbase`. |

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
- **No CDP support** — features that depend on Chrome DevTools Protocol will raise `NotImplementedError`:
  - `scriptInject` (CDP-based `Page.addScriptToEvaluateOnNewDocument`)
  - `Network.setBlockedURLs` (media blocking via `disableMedia`)
  - `Network.setExtraHTTPHeaders` (custom headers via CDP)
  - `sessions.cdp` command
- JavaScript execution via `execute_script` and action `eval` works normally
- Custom headers can be set at browser context level, but not per-request via CDP

**Install:**
```bash
pip install playwright
playwright install chromium
```

### Camoufox

Uses [Camoufox](https://camoufox.com/), a Playwright-based browser with advanced anti-fingerprinting built-in.

**Features:**
- Advanced anti-detection (WebGL spoofing, canvas noise, font randomization, etc.)
- No additional stealth patches needed
- Fast startup

**Limitations:**
- **No CDP support** — same as Playwright backend
- Requires `camoufox` Python package
- Premium feature (paid license for some use cases)

**Install:**
```bash
pip install "camoufox[geoip]"
```

### SeleniumBase

Uses [SeleniumBase](https://github.com/mdmintz/SeleniumBase) Driver with UC mode.

**Features:**
- Simpler setup for users already familiar with SeleniumBase
- UC mode provides basic anti-detection

**Limitations:**
- Partial CDP support (depends on SeleniumBase version)
- Less tested than the default backend

**Install:**
```bash
pip install flaresolverr[seleniumbase]
# or directly
pip install seleniumbase
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
| `sessions.network` | ✅ | ⚠️ | ⚠️ | ⚠️ |
| `sessions.cdp` | ✅ | ❌ | ❌ | ⚠️ |
| `scriptInject` | ✅ | ❌ | ❌ | ⚠️ |
| `disableMedia` | ✅ | ❌ | ❌ | ⚠️ |
| Custom headers via `headers` | ✅ | ❌ | ❌ | ⚠️ |
| Proxy support | ✅ | ✅ | ✅ | ✅ |
| Cookie handling | ✅ | ✅ | ✅ | ✅ |
| Browser actions | ✅ | ✅ | ✅ | ✅ |
| Stealth mode | Custom patches | Basic flags | Built-in | UC mode |

* `postDataRaw` on Playwright/Camoufox uses JavaScript XHR fallback instead of CDP `Fetch.continueRequest`.

## Troubleshooting

### Backend not found

```
ValueError: Unknown driver backend: 'playwright'. Valid backends: ['undetected_chromedriver']
```

**Cause:** The backend package is not installed.

**Fix:** Install the required package:
```bash
# Playwright
pip install playwright && playwright install chromium

# Camoufox
pip install "camoufox[geoip]"

# SeleniumBase
pip install seleniumbase
```

### CDP command not supported

```
NotImplementedError: CDP command 'Network.setBlockedURLs' is not supported by the Playwright backend
```

**Cause:** You are using a backend that does not support Chrome DevTools Protocol.

**Fix:** Switch to `undetected_chromedriver` backend, or avoid CDP-dependent features:
- Instead of `disableMedia`, accept that media will load
- Instead of `scriptInject`, use `sessions.eval` after page load
- Instead of custom headers via `headers`, configure them at the proxy level

### Playwright browser fails to launch

```
browserType.launch: Executable doesn't exist at /home/user/.cache/ms-playwright/chromium-...
```

**Fix:** Run `playwright install chromium` to download browser binaries.

### Camoufox license errors

Camoufox may require a license key for some features. See the [Camoufox documentation](https://camoufox.com/) for licensing details.

## Docker

Backend-specific Dockerfiles are available for CI/testing:

```bash
# Build Playwright backend image
docker build -f Dockerfile.backend-playwright -t flaresolverr:playwright .

# Build Camoufox backend image
docker build -f Dockerfile.backend-camoufox -t flaresolverr:camoufox .
```

See `docker-compose.local.yml` for multi-backend orchestration examples.

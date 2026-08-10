# Agent Notes

## Project

FlareSolverr is a proxy server that uses Chromium (custom-patched or stock via `undetected_chromedriver`) to bypass Cloudflare / DDoS-GUARD challenges. The main source lives in `src/flaresolverr/`.

## Verification

Run the test suite before finishing work:

```bash
# Full local validation (format, lint, typecheck, bandit, vulture, tests)
uv run make

# Unit tests only (default; integration tests are excluded by pyproject addopts)
PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest tests/unit

# Bot challenge integration test (requires the custom Chromium build)
PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest tests/integration/test_bot_challenge.py -m integration -s

# Integration JS-injection tests (requires a running server and httpbin on 127.0.0.1:8080)
# The duplicate-basename issue with tests/unit/test_js_injection.py is fixed by renaming
# the integration file to tests/integration/test_js_injection_integration.py.
PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest tests/integration/test_js_injection_integration.py -m integration -v
```

Integration tests are marked `integration` and excluded by default (`addopts = "-m 'not integration'"`).

For the full `tests/integration/test_api.py` suite, start `go-httpbin` on `127.0.0.1:8080`:

```bash
docker compose -f docker-compose.integration.yml up -d go-httpbin
```

The companion `bot-web-challenge` project uses:

```bash
npm run typecheck
npm run test
npm run build
```

## Key Architecture

- `src/flaresolverr/flaresolverr_service.py` — HTTP API and session lifecycle.
- `src/flaresolverr/utils.py` — Chrome start-up, options, stealth flag handling, proxy extension, custom-Chromium debugger connection.
- `src/flaresolverr/stealth.js` — minimal JS-only CDP-injected patches for custom Chromium.
- `src/flaresolverr/stealth_fallback.js` — CDP/fingerprint evasion for stock Chromium (i386/ARM where custom binary is unavailable).
- `src/flaresolverr/chrome/chrome` — default custom patched Chromium binary.
- `chromium-patches/patches/apply.py` — applies C++ source patches for custom Chromium builds.

## Learned Configuration

- Set `STEALTH_MODE=standard` to use the custom patched Chromium with active stealth.
- `get_webdriver()` starts custom Chromium manually (`subprocess.Popen`) and connects via the remote-debugging port to avoid `chromedriver` adding `--enable-automation`.
- `proxy_ext_dir` and `user_data_dir` are cleaned up in `get_webdriver()` if Chrome fails to start.
- `--user-agent` command-line switch is used instead of CDP `Emulation.setUserAgentOverride` so the UA is consistent across main, dedicated worker and shared worker contexts.
- `--stealth-navigator-languages` and `--stealth-viewport-size` custom switches are forwarded by `apply.py` to renderer processes.
- `navigator.hardwareConcurrency` is kept at a plausible value via CPU affinity (`_limit_cpu_affinity`) rather than JS patching.
- `performance.now()` uses stock Chromium behavior; the native jitter patch was removed after ablation.
- `Error.prepareStackTrace` uses stock V8 behavior; the non-writable property patch was removed after ablation.
- `navigator.mediaDevices.enumerateDevices` is handled natively by the `--stealth-no-media-devices` C++ patch (Patch 11). No JS shim is used.

## External Checks

With the current stealth configuration, `https://deviceandbrowserinfo.com/are_you_a_bot` reports:

```json
{ "isBot": false, "details": { ... all false ... } }
```

The `bot-web-challenge` integration tests (`test_bot_challenge.py`) pass with only an `info`-level `runtime-api:integrity` finding for a page-local `console.log` wrapper.

Additional integration tests:

```bash
# Event.isTrusted regression and cross-realm browser consistency
PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest tests/integration/test_event_istrusted.py tests/integration/test_browser_consistency.py -m integration -s
```

The consistency diagnostic lives in `src/flaresolverr/diagnostics.py` and is
invoked by `diagnostics.collect_browser_consistency(driver, page_url=...)`.
It should be run against an http/https origin (not `data:`) so that
Worker/SharedWorker construction and `navigator.userAgentData` are available.

## Stealth Design

See `STEALTH_DESIGN.md` for the full ownership inventory of every stealth
mechanism (native Chromium vs. launch/CDP configuration vs. JavaScript
compatibility workaround).

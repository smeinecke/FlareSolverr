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
- `performance.now()` uses stock Chromium behavior. The native timing jitter patch (Patch 13) was removed after ablation showed no reproducible difference from stock Chrome on the external timing signal and no internal regression.
- `Error.prepareStackTrace` uses stock V8 behavior; the non-writable property patch was removed after ablation.
- `navigator.mediaDevices.enumerateDevices` is handled natively by the `--stealth-no-media-devices` C++ patch (Patch 11). No JS shim is used.
- GPU / graphics identity is collected by `tests/integration/test_gpu_architecture.py` using CDP `SystemInfo.getInfo` and cross-realm page probes. The native WebGL vendor/renderer spoof (Patch 3) and the stale `--use-gl=swiftshader` flag have been removed; the custom build now exposes the natural ANGLE/GPU identity. In `--headless=new` the GPU process is disabled, so WebGL/WebGPU are unavailable. With a real display WebGL `UNMASKED_VENDOR/RENDERER` match the actual backend, making the graphics stack internally coherent.

## External Checks

The `bot-web-challenge` integration tests (`test_bot_challenge.py`) pass with only a `weak` `outer-eq-inner` finding and an `info`-level `runtime-api:integrity` finding for a page-local `console.log` wrapper.

`https://deviceandbrowserinfo.com/are_you_a_bot` has recently started reporting `isAutomatedWithCDP: true` and `hasInconsistentTimingResolution: true` for this environment; both signals also appear with stock Chrome and with previous custom builds, so they are not regressions from the current patch configuration. A no-Patch-13 ablation confirmed the same `bot-web-challenge` verdict and cross-realm consistency, so the native `performance.now()` jitter patch was removed.

Additional integration tests:

```bash
# Event.isTrusted regression and cross-realm browser consistency
PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest tests/integration/test_event_istrusted.py tests/integration/test_browser_consistency.py -m integration -s

# GPU / graphics identity diagnostic (custom build; compare with stock via CHROME_EXE_PATH / GPU_DIAG_VARIANT=stock)
PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest tests/integration/test_gpu_architecture.py -m integration -s
```

The consistency diagnostic lives in `src/flaresolverr/diagnostics.py` and is
invoked by `diagnostics.collect_browser_consistency(driver, page_url=...)`.
It should be run against an http/https origin (not `data:`) so that
Worker/SharedWorker construction and `navigator.userAgentData` are available.

## Patch Justification Audit

Last full no-Patch-3 bot-web-challenge baseline saved by `test_bot_challenge.py` to
`FLARESOLVERR_CHALLENGE_FULL` (e.g. `/tmp/p3_ablation/no_p3_no_swiftshader_challenge_full.json`)
when run against the current custom Chromium build. Verdict: `human`, risk `low`,
zero medium/strong/hard findings, `timing:integrity` passed,
`hasCrossRealmInconsistency` passed, `hasSyntheticEventTrustedInvariant` passed.

Remaining native patches in `chromium-patches/patches/apply.py` and their status:

| Patch | Signal | Justification | Runtime ablatable? | Notes |
|-------|--------|---------------|--------------------|-------|
| 2 | `navigator.webdriver` absent | Strong bot-detection signal; stock headless exposes `navigator.webdriver = true` | No (IDL annotation) | Required. Absence is verified by critical checks. |
| 3 | WebGL vendor/renderer | Was intended to hide headless/container GPU strings | No (C++ switch read) | **Removed after ablation.** In `--headless=new` the GPU process is disabled, so the patch is dormant. With a real display it forced an `Intel` identity over the actual NVIDIA/ANGLE backend, creating a cross-API incoherence. Removing it restores the natural ANGLE/GPU identity and the `bot-web-challenge` verdict did not change. |
| 6 | `HeadlessChrome` → `Chrome` in UA | `HeadlessChrome` token in `navigator.userAgent` is a strong signal | No (constant string) | Required unless using non-headless mode. |
| 7 | `visualViewport` matches `innerWidth/Height` | Headless can expose visual/layout viewport mismatch | Yes (`--stealth-viewport-size`) | Ablate by not passing the switch. |
| 8/10 | `navigator.languages` / ICU locale | Headless may return `[]` or OS-only locale, mismatching `Accept-Language` and `Intl` | Yes (`--stealth-navigator-languages`) | Ablate by not passing the switch; watch `navigator.languages` and `Intl` consistency. |
| 9 | Forward stealth switches to renderers | Required for any switch-based patch to reach workers/iframes | No (mechanical) | Required infrastructure. |
| 11 | `enumerateDevices()` returns empty | Headless may expose default/fake media devices | Yes (`--stealth-no-media-devices`) | Ablate by not passing the switch; watch `hasInconsistentMediaDevices`. |
| 12 | Remove ChromeDriver CDC alias | `window.cdc_*` is a well-known automation marker | No (chromedriver source patch) | Required while any ChromeDriver path is used. |

Patches already removed: 1 (trusted synthetic events), 13 (`performance.now` jitter), 14 (`Error.prepareStackTrace` guard), plus the switch-forwarding Patch 9b for Patch 13.

## Audit Findings (graphics, locale, viewport)

### Graphics / GPU identity

Run `tests/integration/test_gpu_architecture.py` to collect the data saved to
`FLARESOLVERR_GPU_DIAG` (default `/tmp/gpu_architecture_<variant>.json`).

- **Headless (`--headless=new`) custom build**: actual GL backend is
  `gl=disabled` (GPU process disabled); `webgl` and `webgpu` feature
  status are `disabled_off`. WebGL contexts cannot be created and the
  `--webgl-unmasked-*` spoof has been removed, so the graphics stack is
  internally coherent.
- **Headless stock Chrome 151.0.7922.108**: same disabled GPU state;
  `navigator.webdriver` is `false` (not `undefined/null` as in custom) and
  `enumerateDevices` returns 3 default devices unless the fallback JS is active.
- **Headed custom build (`HEADLESS=false`) on the test device**: the actual
  backend and WebGL `UNMASKED_VENDOR/RENDERER` now agree, both reporting
  `ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 2080/PCIe/SSE2, OpenGL 4.5.0)`
  / `Google Inc. (NVIDIA Corporation)`. This makes the graphics stack internally
  coherent. `navigator.gpu` is present but `requestAdapter()` returned no adapter
  in the test environment, so no WebGPU identity is currently exposable.

### Locale / language

- Custom build with `--stealth-navigator-languages=en-US,en` keeps
  `navigator.languages`, `navigator.language`, `Intl.DateTimeFormat`, and worker
  contexts at `en-US` consistently.
- Stock headless shows `de-DE,de` in the DedicatedWorker while main/iframe report
  `en-US,en`, demonstrating a cross-realm language inconsistency that the custom
  patch fixes.

### Viewport / screen

- Custom headless: `outerWidth/Height = 1920/1080`, `innerWidth/Height =
  1920/1080`, `visualViewport = 1920/1080`, `screen = 1920/1080`.
- Stock headless: `screen = 800/600`, `inner = 1920/993`, `outer = 1920/1080`,
  `visualViewport` matches `inner`. The custom CDP/flag configuration keeps a
  more consistent desktop-like viewport.

## Stealth Design

See `STEALTH_DESIGN.md` for the full ownership inventory of every stealth
mechanism (native Chromium vs. launch/CDP configuration vs. JavaScript
compatibility workaround).

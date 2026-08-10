# Stealth Architecture Design Note

This document is the living design note for the custom Chromium stealth layer.
It records the inventory of stealth mechanisms and the ownership model
(native Blink/Chromium vs. launch/CDP configuration vs. JavaScript fallback).

## Design rule

```text
Intrinsic browser identity / cross-realm browser state
    -> Chromium / Blink / ANGLE / ChromeDriver native layer

Per-session configuration
    -> supported Chromium launch flags, prefs, or CDP configuration

Browser API emulation through JavaScript
    -> remove wherever possible; keep only in fallback stock-Chromium mode
```

Custom-build mode should rely on native browser state and supported
configuration. Stock-Chromium fallback may retain best-effort JavaScript
compatibility workarounds because the binary is not under our control.

## Inventory and ownership

| Signal | Custom-build ownership | Current implementation | Classification | Notes |
|--------|------------------------|------------------------|----------------|-------|
| `navigator.webdriver` | Native (Blink) | C++ patch gates IDL attribute on `[RuntimeEnabled=AutomationControlled]`; `--disable-blink-features=AutomationControlled` | A | Must be absent/undefined in all realms. No JS getters. |
| `navigator.language` / `navigator.languages` | Native (Blink) + config | C++ patch `--stealth-navigator-languages=<list>`; `--accept-lang` and `--lang` also forwarded | A/B | Patch parses the switch value as the underlying language state for all contexts. `--lang` (Patch 10) keeps Intl.* defaults aligned with navigator.language. |
| `navigator.userAgent` | Config | `--user-agent` CLI switch (custom); CDP `Emulation.setUserAgentOverride` (fallback) | B | `--user-agent` propagates to all execution contexts. |
| `navigator.platform` | Native | Derived from UA / OS | A | No override. |
| `navigator.userAgentData` / UA-CH | Config + native propagation | `--user-agent` provides legacy UA; fallback JS patches brands | B/A | CDP metadata does not reach SharedWorkers; `--user-agent` covers legacy UA. UA-CH propagation gaps should be fixed natively, not via JS. |
| DedicatedWorker identity | Native / config | Same process/flags as main; no custom JS prelude | A/B | `--user-agent` and `--accept-lang` propagate. |
| SharedWorker identity | Native / config | No custom JS wrapper | A/B | UA/languages should derive from common browser state. |
| Permissions API | Native / config | Fallback JS overrides `navigator.permissions.query` for notifications; custom build uses no JS | B | Use Chromium profile / CDP permissions. No fabricated objects. |
| `mediaDevices.enumerateDevices` | Native | C++ patch `--stealth-no-media-devices` returns an empty list | A | No JS shim. Native empty list is less fingerprintable than any fake or real device objects. |
| WebGL vendor / renderer | Native (Blink) | C++ patch `--webgl-unmasked-vendor/renderer` | A | All WebGL contexts read same command-line value. |
| WebGPU adapter info | Not currently customized | Not patched | A | Should be coherent with WebGL if GPU identity is spoofed. |
| screen / window / outer size | Config | `--window-size`, CDP `setDeviceMetricsOverride`; `outerWidth/outerHeight` JS shim removed | B | Native `outerWidth`/`outerHeight` values are now coherent with `--headless=new` and the chosen window size; the JS patch was removed after testing. |
| visualViewport | Native (Blink) | C++ patch `--stealth-viewport-size` | B/A | Prevents `visualViewport` vs `innerWidth/innerHeight` mismatch in headless. May be removable if `--window-size` / CDP metrics are sufficient; under evaluation. |
| ChromeDriver CDC artifacts | Native (ChromeDriver) | C++ patch removes `cdc_*` alias injection from chromedriver | A | Prevent marker creation, not page-side cleanup. |
| `Event.isTrusted` | Native (input dispatch) | Global `--enable-trusted-synthetic-events` patch removed. Native CDP/ChromeDriver input stays trusted, JS-dispatched events stay untrusted. | A | Do not force `isTrusted=true` globally. |
| console method replacement | Fallback JS only | `stealth_fallback.js` wraps `console.log` | C | Low-value; keep only in fallback if necessary. |
| `speechSynthesis` fake voices | Fallback JS only | `stealth_fallback.js` inserts a fake voice | C | Low-value; fallback only. |
| `navigator.plugins` / `mimeTypes` | Fallback JS only | `stealth_fallback.js` fakes plugin/mime arrays | C | Low-value; fallback only. |
| `performance.now` timing jitter | Native (Blink) | C++ patch `--stealth-performance-now-jitter` adds monotonic noise in `Performance::now()` | A | Ablating it caused `hasInconsistentTimingResolution: true` on deviceandbrowserinfo.com. Kept; the current unbounded random walk causes call-frequency time inflation and should be capped in a future iteration. |
| `Error.prepareStackTrace` guard | Removed after ablation | Previously a native V8 flag; reverted because stock V8 does not expose `Error.prepareStackTrace` and disabling the flag produced no regression | D | Do not re-add; the property is not present in stock Chromium 151. |
| `Function.prototype.toString` / descriptor disguises | Remove | Not present in current `stealth.js` | D | Do not re-add. |
| Worker / SharedWorker constructor wrappers | Remove from custom | Only `stealth_fallback.js` wraps `window.Worker` | C | Custom Chromium uses native state, no wrappers. |

## Custom build end state (target)

```text
Custom Chromium
|
├── Native patches
│   ├── webdriver / automation exposure
│   ├── ChromeDriver artifact prevention
│   ├── cross-realm identity propagation gaps
│   ├── coherent GPU identity (WebGL; WebGPU when needed)
│   └── narrow headless-only fixes (visualViewport, outer dimensions if no config exists)
│
├── Supported configuration / CDP
│   ├── UA + UA-CH
│   ├── locale / Accept-Language / --lang
│   ├── permissions
│   ├── viewport / screen
│   └── other session parameters
│
└── stealth.js
    (empty for custom Chromium — all defences are now native)
```

## Upgrade maintenance notes

- The `[RuntimeEnabled=AutomationControlled]` webdriver gate depends on Blink
  IDL runtime features. If upstream moves the file, update `apply.py`.
- GPU identity should move deeper into ANGLE / Skia / Dawn as the spoofing
  scope grows; avoid duplicating WebGL and WebGPU values.
- Headless `outerWidth` / `outerHeight` / `visualViewport` patches are
  workarounds for specific headless-shell behavior. Re-evaluate after each
  major Chromium headless refactor. The `outerWidth`/`outerHeight` JS shim was
  removed in this audit; confirm during the next full integration run.
- `mediaDevices.enumerateDevices` is now handled by the `--stealth-no-media-devices`
  native patch (Patch 11). No JS fallback should be re-added.

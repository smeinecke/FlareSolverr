/**
 * stealth.js — JS-only fingerprint evasion patches for custom Chromium builds.
 *
 * This file is NOT used at runtime — the --preload-script C++ mechanism has a
 * known bug (v8::Script::Run from DidCreateScriptContext triggers microtask
 * re-entrancy causing renderer CPU spin). Stealth patches are instead injected
 * via Page.addScriptToEvaluateOnNewDocument (CDP) using stealth_fallback.js.
 *
 * Once the C++ preload injection is fixed (add v8::MicrotasksScope with
 * kDoNotRunMicrotasks in render_frame_impl.cc and rebuild Chromium), this file
 * should be populated with only the JS-only patches (see stealth_fallback.js)
 * and the --preload-script flag re-enabled in utils.py.
 *
 * C++ patches active on custom Chromium (handled at binary level):
 *   - navigator.webdriver → undefined (--disable-blink-features=AutomationControlled)
 *   - WebGL vendor/renderer (--webgl-unmasked-vendor, --webgl-unmasked-renderer)
 *   - isTrusted synthetic events (--enable-trusted-synthetic-events)
 *   - navigator.languages (--stealth-navigator-languages)
 */

/**
 * stealth.js — JS-only fingerprint evasion patches.
 *
 * When custom Chromium is used, this file is auto-injected at document_start
 * via the --preload-script flag (no CDP call required). The C++ patches handle:
 *   - navigator.webdriver, WebGL vendor/renderer, isTrusted, worker prelude.
 *
 * Patches below are grouped by signal. Each block is independently try-caught so
 * a failure in one never breaks the others.
 */
(() => {
  // ── console guard ────────────────────────────────────────────────────────────
  // CDP remote-debugging causes console.log(new Error()) to emit structured
  // devtools protocol output that fingerprinters can detect. Replace with a
  // plain-string formatter to hide the CDP artifact.
  try {
    const _log  = console.log.bind(console);
    const _safe = (...a) => _log(...a.map(x => x instanceof Error ? x.name + ': ' + x.message : x));
    console.log = _safe;
  } catch (_) {}

  // ── navigator.languages / language ───────────────────────────────────────────
  // NOTE: Now handled at C++ level via --stealth-navigator-languages flag.
  // The C++ patch in NavigatorLanguage::languages() returns ['en-US', 'en']
  // instead of empty array, avoiding JS property descriptor modification.

  // ── media devices ─────────────────────────────────────────────────────────────
  // Headless/container runs often return zero devices, which gets scored as a
  // weak automation signal on some pages. Provide a stable fallback only when
  // enumerateDevices returns empty.
  try {
    if (navigator.mediaDevices?.enumerateDevices) {
      const _enum = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
      navigator.mediaDevices.enumerateDevices = () =>
        _enum()
          .then(d => (Array.isArray(d) && d.length > 0 ? d : [
            { deviceId: 'default-mic', kind: 'audioinput', label: 'Default Microphone', groupId: 'default' },
            { deviceId: 'default-spk', kind: 'audiooutput', label: 'Default Speaker', groupId: 'default' },
          ]))
          .catch(() => ([
            { deviceId: 'default-mic', kind: 'audioinput', label: 'Default Microphone', groupId: 'default' },
            { deviceId: 'default-spk', kind: 'audiooutput', label: 'Default Speaker', groupId: 'default' },
          ]));
    }
  } catch (_) {}

  // ── navigator.plugins / mimeTypes ────────────────────────────────────────────
  // An empty plugin list is a classic headless indicator. Populate with the
  // built-in PDF viewer that every real Chrome install ships with.
  try {
    if (!navigator.plugins?.length) {
      const p   = { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format', version: '1' };
      const arr = { 0: p, length: 1, item: i => i === 0 ? p : null, namedItem: n => n === p.name ? p : null };
      Object.defineProperty(Navigator.prototype, 'plugins', { get: () => arr, configurable: true });
    }
    if (!navigator.mimeTypes?.length) {
      const m   = { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' };
      const arr = { 0: m, length: 1, item: i => i === 0 ? m : null, namedItem: n => n === m.type ? m : null };
      Object.defineProperty(Navigator.prototype, 'mimeTypes', { get: () => arr, configurable: true });
    }
  } catch (_) {}

  // ── speechSynthesis.getVoices ─────────────────────────────────────────────────
  // Containerised Chrome often returns zero voices; provide a realistic fallback.
  try {
    if (window.speechSynthesis?.getVoices) {
      const _orig = window.speechSynthesis.getVoices.bind(window.speechSynthesis);
      window.speechSynthesis.getVoices = () => {
        const v = _orig();
        return v?.length ? v : [{ default: true, lang: 'en-US', localService: true, name: 'Google US English', voiceURI: 'Google US English' }];
      };
    }
  } catch (_) {}

  // ── navigator.permissions.query (notifications) ───────────────────────────────
  // Return the actual Notification.permission state instead of a synthetic value.
  try {
    if (navigator.permissions?.query) {
      const _q = navigator.permissions.query.bind(navigator.permissions);
      navigator.permissions.query = p =>
        p?.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission, onchange: null })
          : _q(p);
    }
  } catch (_) {}

  // ── screen / outer dimensions ─────────────────────────────────────────────────
  // With Xvfb the virtual display can be smaller than the Chrome window, producing
  // an impossible screen < viewport combination that fingerprinters flag.
  try {
    const sw = screen.width, sh = screen.height, iw = innerWidth || 1280, ih = innerHeight || 800;
    if (sw < iw || sh < ih) {
      const ow = Math.max(iw, sw), oh = Math.max(ih, sh) + 85; // +85 ≈ browser chrome height
      try { Object.defineProperty(window, 'outerWidth',  { get: () => ow,      configurable: true }); } catch (_) {}
      try { Object.defineProperty(window, 'outerHeight', { get: () => oh,      configurable: true }); } catch (_) {}
      try {
        Object.defineProperty(screen, 'width',       { get: () => ow,      configurable: true });
        Object.defineProperty(screen, 'height',      { get: () => oh + 40, configurable: true }); // +40 ≈ taskbar
        Object.defineProperty(screen, 'availWidth',  { get: () => ow,      configurable: true });
        Object.defineProperty(screen, 'availHeight', { get: () => oh,      configurable: true });
      } catch (_) {}
    }
  } catch (_) {}

  // ── visualViewport ────────────────────────────────────────────────────────────
  // NOTE: Now handled at C++ level via --stealth-viewport-size flag.
  // The C++ patch in VisualViewport::Width() and ::Height() returns
  // innerWidth/innerHeight instead of the scaled visual viewport size,
  // avoiding JS property descriptor modification.

})();

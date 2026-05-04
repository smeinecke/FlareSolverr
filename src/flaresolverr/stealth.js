/**
 * stealth.js — JS-only fingerprint evasion patches for custom Chromium builds.
 *
 * Injected via --preload-script (C++ DidCreateDocumentElement hook).
 * Safe because DidCreateDocumentElement fires after V8 context creation is
 * complete. DO NOT inject from DidCreateScriptContext — that fires during V8
 * context creation while V8 holds internal spinlocks; Script::Compile there
 * causes 97% CPU spin.
 *
 * NOTE: --preload-script is currently commented out in utils.py pending a
 * Chromium rebuild that includes the DidCreateDocumentElement fix in apply.py.
 * Until then, stealth_fallback.js is injected via CDP instead.
 *
 * C++ patches active on custom Chromium (binary level):
 *   - navigator.webdriver → undefined
 *   - WebGL vendor/renderer (--webgl-unmasked-vendor/renderer)
 *   - isTrusted synthetic events (--enable-trusted-synthetic-events)
 *   - navigator.languages (--stealth-navigator-languages)
 *
 * JS-only patches below cover remaining signals.
 * Each block is independently try-caught so one failure never breaks others.
 */
(() => {
  // ── console guard ────────────────────────────────────────────────────────────
  try {
    const _log  = console.log.bind(console);
    const _safe = (...a) => _log(...a.map(x => x instanceof Error ? x.name + ': ' + x.message : x));
    console.log = _safe;
  } catch (_) {}

  // ── media devices ─────────────────────────────────────────────────────────────
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
  try {
    const sw = screen.width, sh = screen.height, iw = innerWidth || 1280, ih = innerHeight || 800;
    if (sw < iw || sh < ih) {
      const ow = Math.max(iw, sw), oh = Math.max(ih, sh) + 85;
      try { Object.defineProperty(window, 'outerWidth',  { get: () => ow,      configurable: true }); } catch (_) {}
      try { Object.defineProperty(window, 'outerHeight', { get: () => oh,      configurable: true }); } catch (_) {}
      try {
        Object.defineProperty(screen, 'width',       { get: () => ow,      configurable: true });
        Object.defineProperty(screen, 'height',      { get: () => oh + 40, configurable: true });
        Object.defineProperty(screen, 'availWidth',  { get: () => ow,      configurable: true });
        Object.defineProperty(screen, 'availHeight', { get: () => oh,      configurable: true });
      } catch (_) {}
    }
  } catch (_) {}

})();

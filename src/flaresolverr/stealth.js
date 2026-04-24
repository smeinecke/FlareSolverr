/**
 * stealth.js — CDP/fingerprint evasion patches injected via Page.addScriptToEvaluateOnNewDocument.
 *
 * Patches are grouped by signal. Each block is independently try-caught so a failure in one
 * never breaks the others. The WORKER_PRELUDE constant mirrors the subset of patches that must
 * also run inside Web Worker contexts (which have a separate JS engine instance).
 */
(() => {
  const PATCH_WEBGL = globalThis.__FS_STEALTH_PATCH_WEBGL === true;
  const BLOB_BYPASS = globalThis.__FS_STEALTH_BLOB_BYPASS === true;

  // ── console guard ────────────────────────────────────────────────────────────
  // CDP remote-debugging causes console.log(new Error()) to emit structured
  // devtools protocol output that fingerprinters can detect. Replace with a
  // plain-string formatter to hide the CDP artifact.
  try {
    const _log  = console.log.bind(console);
    const _safe = (...a) => _log(...a.map(x => x instanceof Error ? x.name + ': ' + x.message : x));
    try { Object.defineProperty(console, 'log', { value: _safe, writable: false, configurable: false }); }
    catch (_) { console.log = _safe; }
  } catch (_) {}

  // ── navigator.webdriver → undefined ──────────────────────────────────────────
  // ChromeDriver sets this to `true`. undetected-chromedriver patches the binary,
  // but we override both the prototype and the instance for belt-and-suspenders.
  try {
    const _undef = { get: () => undefined, configurable: true };
    Object.defineProperty(Navigator.prototype, 'webdriver', _undef);
    Object.defineProperty(navigator, 'webdriver', _undef);
  } catch (_) {}

  // ── window.chrome ─────────────────────────────────────────────────────────────
  // Fingerprinters verify that window.chrome and window.chrome.runtime exist.
  try {
    if (!window.chrome)              window.chrome = { app: { isInstalled: false }, runtime: {} };
    else if (!window.chrome.runtime) window.chrome.runtime = {};
  } catch (_) {}

  // ── navigator.languages / language ───────────────────────────────────────────
  // Headless Chrome can expose empty arrays; ensure non-empty and self-consistent.
  try {
    const langs = navigator.languages?.length ? navigator.languages : ['en-US', 'en'];
    const lang  = (typeof navigator.language === 'string' && navigator.language) ? navigator.language : langs[0];
    Object.defineProperty(Navigator.prototype, 'languages', { get: () => langs, configurable: true });
    Object.defineProperty(Navigator.prototype, 'language',  { get: () => lang,  configurable: true });
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

  // ── WebGL vendor / renderer (UNMASKED_VENDOR=37445, UNMASKED_RENDERER=37446) ──
  // Docker containers without GPU passthrough use the SwiftShader software
  // renderer, which is an unambiguous automation signal. Spoof to a real GPU.
  const GL_VENDOR   = 'Intel Inc.';
  const GL_RENDERER = 'Intel(R) Iris(TM) Graphics 6100';
  const _patchGL = proto => {
    const _orig = proto.getParameter;
    proto.getParameter = function(p) {
      if (p === 37445) return GL_VENDOR;
      if (p === 37446) return GL_RENDERER;
      return _orig.call(this, p);
    };
  };
  if (PATCH_WEBGL) {
    try { if (typeof WebGLRenderingContext  !== 'undefined') _patchGL(WebGLRenderingContext.prototype);  } catch (_) {}
    try { if (typeof WebGL2RenderingContext !== 'undefined') _patchGL(WebGL2RenderingContext.prototype); } catch (_) {}
  }

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

  // ── Web Worker patches ────────────────────────────────────────────────────────
  // Workers run in an isolated JS context; the patches above don't reach them.
  // We wrap window.Worker to prepend a minimal prelude to every worker script.
  // The prelude re-applies the subset of patches that fingerprinters check inside
  // workers: console guard, webdriver flag, and WebGL renderer strings.
  //
  // FIXED: Skip wrapping for blob: URLs which cause CSP violations on sites with
  // strict Content-Security-Policy (e.g., Cloudflare Turnstile challenges).
  // The blob: URL we create to inject the prelude violates 'script-src' directives.
  try {
    const _NW = window.Worker;
    if (_NW) {
      // Keep this prelude self-contained and minified — it becomes a string literal
      // inside a Blob and cannot reference the outer scope.
      const WORKER_PRELUDE = [
        '(()=>{',
        // console guard
        'try{const l=console.log.bind(console);',
        'const s=(...a)=>l(...a.map(x=>x instanceof Error?x.name+": "+x.message:x));',
        'try{Object.defineProperty(console,"log",{value:s,writable:false,configurable:false});}catch(_){console.log=s;}}catch(_){}',
        // webdriver
        'try{Object.defineProperty(Navigator.prototype,"webdriver",{get:()=>undefined,configurable:true});}catch(_){}',
        '})();',
      ].join('');

      const _WW = function(url, opts) {
        // Optional CSP-safe mode: skip blob URLs to avoid strict-CSP worker violations.
        if (BLOB_BYPASS && String(url).startsWith('blob:')) {
          return new _NW(url, opts);
        }
        try {
          const src  = WORKER_PRELUDE + '\nimportScripts(' + JSON.stringify(String(url)) + ');';
          const blob = new Blob([src], { type: 'application/javascript' });
          return new _NW(URL.createObjectURL(blob), opts);
        } catch (_) { return new _NW(url, opts); }
      };
      _WW.prototype = _NW.prototype;
      Object.defineProperty(window, 'Worker', { value: _WW, configurable: true, writable: true });
    }
  } catch (_) {}

})();

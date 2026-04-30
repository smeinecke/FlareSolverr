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
  // but the property may still survive as an own property on the navigator instance.
  // We delete the own property so the prototype accessor takes over — a non-native
  // getter defined directly on the instance is detectable via
  // Object.getOwnPropertyDescriptor(navigator, 'webdriver').
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined, configurable: true });
    try { delete navigator.webdriver; } catch (_) {}
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

  // ── navigator.userAgent / appVersion ─────────────────────────────────────────
  // Headless Chrome exposes the "HeadlessChrome" token, which many bot detectors
  // flag directly. Keep this patch local to JS fingerprinting context.
  try {
    const ua = navigator.userAgent;
    if (typeof ua === 'string' && ua.includes('HeadlessChrome')) {
      const patchedUA = ua.replace(/HeadlessChrome\//g, 'Chrome/');
      Object.defineProperty(Navigator.prototype, 'userAgent', { get: () => patchedUA, configurable: true });
    }
    const av = navigator.appVersion;
    if (typeof av === 'string' && av.includes('HeadlessChrome')) {
      const patchedAV = av.replace(/HeadlessChrome\//g, 'Chrome/');
      Object.defineProperty(Navigator.prototype, 'appVersion', { get: () => patchedAV, configurable: true });
    }
  } catch (_) {}

  // ── navigator.userAgentData.brands + platform ────────────────────────────────
  // Newer detections inspect UA-CH brand entries for "HeadlessChrome" and compare
  // userAgentData.platform against the navigator.userAgent string. We derive the
  // platform from the (already-patched) userAgent string so both are always
  // consistent, regardless of whether Emulation.setUserAgentOverride was called.
  try {
    const uad = navigator.userAgentData;
    if (uad && Array.isArray(uad.brands)) {
      const patchedBrands = uad.brands.map(b => ({
        ...b,
        brand: String(b?.brand || '').replace(/HeadlessChrome/g, 'Google Chrome'),
      }));
      // Derive platform from the current (patched) userAgent rather than uad.platform
      // to guarantee consistency between userAgentData.platform and the UA string.
      const _ua = navigator.userAgent;
      let _platform = uad.platform;
      if (/Windows/.test(_ua))               _platform = 'Windows';
      else if (/Macintosh|Mac OS X/.test(_ua)) _platform = 'macOS';
      else if (/Linux/.test(_ua))             _platform = 'Linux';
      else if (/Android/.test(_ua))           _platform = 'Android';
      else if (/iPhone|iPad|iPod/.test(_ua))  _platform = 'iOS';
      const patchedUAData = {
        brands: patchedBrands,
        mobile: uad.mobile,
        platform: _platform,
        getHighEntropyValues: typeof uad.getHighEntropyValues === 'function'
          ? uad.getHighEntropyValues.bind(uad)
          : undefined,
      };
      Object.defineProperty(Navigator.prototype, 'userAgentData', { get: () => patchedUAData, configurable: true });
    }
  } catch (_) {}

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
  // workers: console guard, webdriver flag, userAgent, and WebGL renderer strings.
  //
  // WebGL is included in the prelude only when PATCH_WEBGL is true (standard mode)
  // so that main-thread and worker WebGL values always match.
  //
  // CSP note: in csp-safe mode (BLOB_BYPASS=true) blob: worker injection is skipped
  // entirely; WebGL patching is also disabled for that mode so values stay consistent.
  try {
    const _NW = window.Worker;
    if (_NW) {
      // Build the prelude dynamically so WebGL patching matches the main-thread setting.
      // Everything here must be self-contained — it runs inside a Blob with no outer scope.
      const _preludeParts = [
        '(()=>{',
        // console guard
        'try{const l=console.log.bind(console);',
        'const s=(...a)=>l(...a.map(x=>x instanceof Error?x.name+": "+x.message:x));',
        'try{Object.defineProperty(console,"log",{value:s,writable:false,configurable:false});}catch(_){console.log=s;}}catch(_){}',
        // webdriver
        'try{Object.defineProperty(Navigator.prototype,"webdriver",{get:()=>undefined,configurable:true});}catch(_){}',
        // userAgent/appVersion
        'try{const ua=navigator.userAgent;if(typeof ua==="string"&&ua.includes("HeadlessChrome")){const p=ua.replace(/HeadlessChrome\\//g,"Chrome/");Object.defineProperty(Navigator.prototype,"userAgent",{get:()=>p,configurable:true});}const av=navigator.appVersion;if(typeof av==="string"&&av.includes("HeadlessChrome")){const q=av.replace(/HeadlessChrome\\//g,"Chrome/");Object.defineProperty(Navigator.prototype,"appVersion",{get:()=>q,configurable:true});}}catch(_){}',
        // mediaDevices.enumerateDevices fallback
        'try{if(navigator.mediaDevices&&navigator.mediaDevices.enumerateDevices){const e=navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);navigator.mediaDevices.enumerateDevices=()=>e().then(d=>Array.isArray(d)&&d.length>0?d:[{deviceId:"default-mic",kind:"audioinput",label:"Default Microphone",groupId:"default"},{deviceId:"default-spk",kind:"audiooutput",label:"Default Speaker",groupId:"default"}]).catch(()=>[{deviceId:"default-mic",kind:"audioinput",label:"Default Microphone",groupId:"default"},{deviceId:"default-spk",kind:"audiooutput",label:"Default Speaker",groupId:"default"}]);}}catch(_){}',
      ];
      if (PATCH_WEBGL) {
        // Mirror the same vendor/renderer spoof applied in the main thread.
        _preludeParts.push(
          'try{const GL_V="' + GL_VENDOR + '",GL_R="' + GL_RENDERER + '";' +
          'const _pGL=p=>{const _o=p.getParameter;p.getParameter=function(x){if(x===37445)return GL_V;if(x===37446)return GL_R;return _o.call(this,x);};};' +
          'if(typeof WebGLRenderingContext!=="undefined")_pGL(WebGLRenderingContext.prototype);' +
          'if(typeof WebGL2RenderingContext!=="undefined")_pGL(WebGL2RenderingContext.prototype);' +
          '}catch(_){}'
        );
      }
      _preludeParts.push('})();');
      const WORKER_PRELUDE = _preludeParts.join('');

      const _WW = function(url, opts) {
        const urlStr = String(url);
        // Optional CSP-safe mode: skip blob URLs to avoid strict-CSP worker violations.
        if (BLOB_BYPASS && urlStr.startsWith('blob:')) {
          return new _NW(urlStr, opts);
        }
        try {
          let src;
          if (urlStr.startsWith('blob:')) {
            // Read the blob content synchronously NOW, before the caller revokes the URL.
            // Callers commonly do `new Worker(blobUrl); URL.revokeObjectURL(blobUrl)` in the
            // same tick, which would make a later importScripts(blobUrl) call fail.
            const xhr = new XMLHttpRequest();
            xhr.open('GET', urlStr, false /* synchronous */);
            xhr.send();
            src = WORKER_PRELUDE + '\n' + xhr.responseText;
          } else {
            src = WORKER_PRELUDE + '\nimportScripts(' + JSON.stringify(urlStr) + ');';
          }
          const blob = new Blob([src], { type: 'application/javascript' });
          return new _NW(URL.createObjectURL(blob), opts);
        } catch (_) { return new _NW(url, opts); }
      };
      _WW.prototype = _NW.prototype;
      Object.defineProperty(window, 'Worker', { value: _WW, configurable: true, writable: true });
    }
  } catch (_) {}

})();

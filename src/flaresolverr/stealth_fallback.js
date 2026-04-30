/**
 * stealth_fallback.js — CDP/fingerprint evasion patches injected via
 * Page.addScriptToEvaluateOnNewDocument. Used on 386/armv7 targets where
 * the custom patched Chromium binary is not available.
 *
 * Patches are grouped by signal. Each block is independently try-caught so a
 * failure in one never breaks the others.
 */
(() => {
  const PATCH_WEBGL = globalThis.__FS_STEALTH_PATCH_WEBGL === true;
  const BLOB_BYPASS = globalThis.__FS_STEALTH_BLOB_BYPASS === true;

  // ── console guard ────────────────────────────────────────────────────────────
  try {
    const _log  = console.log.bind(console);
    const _safe = (...a) => _log(...a.map(x => x instanceof Error ? x.name + ': ' + x.message : x));
    try { Object.defineProperty(console, 'log', { value: _safe, writable: false, configurable: false }); }
    catch (_) { console.log = _safe; }
  } catch (_) {}

  // ── navigator.webdriver → undefined ──────────────────────────────────────────
  try {
    const _undef = { get: () => undefined, configurable: true };
    Object.defineProperty(Navigator.prototype, 'webdriver', _undef);
    Object.defineProperty(navigator, 'webdriver', _undef);
  } catch (_) {}

  // ── window.chrome ─────────────────────────────────────────────────────────────
  try {
    if (!window.chrome)              window.chrome = { app: { isInstalled: false }, runtime: {} };
    else if (!window.chrome.runtime) window.chrome.runtime = {};
  } catch (_) {}

  // ── navigator.languages / language ───────────────────────────────────────────
  try {
    const langs = navigator.languages?.length ? navigator.languages : ['en-US', 'en'];
    const lang  = (typeof navigator.language === 'string' && navigator.language) ? navigator.language : langs[0];
    Object.defineProperty(Navigator.prototype, 'languages', { get: () => langs, configurable: true });
    Object.defineProperty(Navigator.prototype, 'language',  { get: () => lang,  configurable: true });
  } catch (_) {}

  // ── navigator.userAgent / appVersion ─────────────────────────────────────────
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

  // ── navigator.userAgentData.platform ─────────────────────────────────────────
  try {
    const uad = navigator.userAgentData;
    if (uad) {
      const _ua = navigator.userAgent;
      let _platform = uad.platform;
      if (/Windows/.test(_ua))                _platform = 'Windows';
      else if (/Macintosh|Mac OS X/.test(_ua)) _platform = 'macOS';
      else if (/Linux/.test(_ua))              _platform = 'Linux';
      else if (/Android/.test(_ua))            _platform = 'Android';
      else if (/iPhone|iPad|iPod/.test(_ua))   _platform = 'iOS';

      const patchedBrands = Array.isArray(uad.brands) ? uad.brands.map(b => ({
        ...b,
        brand: String(b?.brand || '').replace(/HeadlessChrome/g, 'Google Chrome'),
      })) : uad.brands;

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

  // ── WebGL vendor / renderer (UNMASKED_VENDOR=37445, UNMASKED_RENDERER=37446) ──
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

  // ── Web Worker patches ────────────────────────────────────────────────────────
  // Workers run in an isolated JS context. Wrap window.Worker to prepend a
  // minimal prelude that re-applies the detectable patches inside each worker.
  //
  // WORKER_PRELUDE is built dynamically to match the main-thread settings so
  // that hasInconsistentWorkerValues stays clean.
  //
  // Blob URL revocation fix: callers may do new Worker(blobUrl) + revokeObjectURL
  // synchronously. importScripts(blobUrl) would then fail asynchronously. We use
  // a synchronous XHR to read the blob content before it can be revoked.
  try {
    const _NW = window.Worker;
    if (_NW) {
      const _preludeParts = [
        '(()=>{',
        // console guard
        'try{const l=console.log.bind(console);',
        'const s=(...a)=>l(...a.map(x=>x instanceof Error?x.name+": "+x.message:x));',
        'try{Object.defineProperty(console,"log",{value:s,writable:false,configurable:false});}catch(_){console.log=s;}}catch(_){}',
        // webdriver
        'try{const u={get:()=>undefined,configurable:true};',
        'Object.defineProperty(Navigator.prototype,"webdriver",u);',
        'Object.defineProperty(navigator,"webdriver",u);}catch(_){}',
        // userAgent/appVersion
        'try{const ua=navigator.userAgent;if(typeof ua==="string"&&ua.includes("HeadlessChrome")){const p=ua.replace(/HeadlessChrome\\//g,"Chrome/");Object.defineProperty(Navigator.prototype,"userAgent",{get:()=>p,configurable:true});}const av=navigator.appVersion;if(typeof av==="string"&&av.includes("HeadlessChrome")){const q=av.replace(/HeadlessChrome\\//g,"Chrome/");Object.defineProperty(Navigator.prototype,"appVersion",{get:()=>q,configurable:true});}}catch(_){}',
        // mediaDevices fallback
        'try{if(navigator.mediaDevices&&navigator.mediaDevices.enumerateDevices){const e=navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);navigator.mediaDevices.enumerateDevices=()=>e().then(d=>Array.isArray(d)&&d.length>0?d:[{deviceId:"default-mic",kind:"audioinput",label:"Default Microphone",groupId:"default"},{deviceId:"default-spk",kind:"audiooutput",label:"Default Speaker",groupId:"default"}]).catch(()=>[{deviceId:"default-mic",kind:"audioinput",label:"Default Microphone",groupId:"default"},{deviceId:"default-spk",kind:"audiooutput",label:"Default Speaker",groupId:"default"}]);}}catch(_){}',
      ];

      if (PATCH_WEBGL) {
        _preludeParts.push(
          // WebGL spoof — must match main thread when PATCH_WEBGL=true
          'try{const GL_V="Intel Inc.",GL_R="Intel(R) Iris(TM) Graphics 6100";' +
          'const pg=p=>{const o=p.getParameter;p.getParameter=function(x){if(x===37445)return GL_V;if(x===37446)return GL_R;return o.call(this,x);};};' +
          'if(typeof WebGLRenderingContext!=="undefined")pg(WebGLRenderingContext.prototype);' +
          'if(typeof WebGL2RenderingContext!=="undefined")pg(WebGL2RenderingContext.prototype);}catch(_){}'
        );
      }

      _preludeParts.push('})();');
      const WORKER_PRELUDE = _preludeParts.join('');

      const _WW = function(url, opts) {
        if (BLOB_BYPASS && String(url).startsWith('blob:')) {
          return new _NW(url, opts);
        }
        try {
          const urlStr = String(url);
          let src;
          if (urlStr.startsWith('blob:')) {
            // Read synchronously before the caller can revoke the URL.
            const xhr = new XMLHttpRequest();
            xhr.open('GET', urlStr, false);
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

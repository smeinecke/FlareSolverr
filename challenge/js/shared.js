/**
 * Bot Detection Challenge - Shared Utilities
 * Common functions used by both static and interaction detectors
 */

(function() {
    'use strict';

    // Bot user agent patterns
    const BOT_PATTERNS = [
        /bot/i, /crawler/i, /spider/i, /scraper/i, /automated/i,
        /headless/i, /phantom/i, /selenium/i, /puppeteer/i,
        /playwright/i, /webdriver/i, /nightmare/i, /slimer/i
    ];

    // Headless default screen resolutions
    const HEADLESS_RESOLUTIONS = [
        { width: 800, height: 600 },
        { width: 1280, height: 720 },
        { width: 1280, height: 800 },
        { width: 1920, height: 1080 }
    ];

    /**
     * Check if user agent matches bot patterns
     */
    function checkBotUserAgent() {
        const ua = navigator.userAgent;
        return BOT_PATTERNS.some(pattern => pattern.test(ua));
    }

    /**
     * Check navigator.webdriver property
     */
    function checkWebdriver() {
        return navigator.webdriver === true;
    }

    /**
     * Check for webdriver in iframe
     */
    function checkWebdriverInFrame() {
        try {
            const iframe = document.createElement('iframe');
            iframe.style.display = 'none';
            document.body.appendChild(iframe);
            const frameWindow = iframe.contentWindow;
            const hasWebdriver = frameWindow && frameWindow.navigator && frameWindow.navigator.webdriver === true;
            document.body.removeChild(iframe);
            return hasWebdriver;
        } catch (e) {
            return false;
        }
    }

    /**
     * Check for Playwright globals
     */
    function checkPlaywright() {
        return typeof window.__pwInitScripts !== 'undefined' ||
               typeof window.__playwright__binding__ !== 'undefined' ||
               typeof window._playwrightBinding !== 'undefined';
    }

    /**
     * Check for inconsistent chrome object
     */
    function checkInconsistentChrome() {
        const isChrome = /Chrome/.test(navigator.userAgent) && /Google Inc/.test(navigator.vendor);
        if (!isChrome) return false;

        // Check if chrome object exists and has expected properties
        if (typeof window.chrome === 'undefined') return true;

        // Check for expected chrome properties
        const expectedProps = ['loadTimes', 'csi', 'app'];
        const hasExpected = expectedProps.some(prop => prop in window.chrome);

        return !hasExpected;
    }

    /**
     * Check for PhantomJS
     */
    function checkPhantomJS() {
        return typeof window.callPhantom !== 'undefined' ||
               typeof window._phantom !== 'undefined' ||
               typeof window.phantom !== 'undefined';
    }

    /**
     * Check for Nightmare.js
     */
    function checkNightmare() {
        return typeof window.__nightmare !== 'undefined';
    }

    /**
     * Check for Sequentum
     */
    function checkSequentum() {
        try {
            return window.external && window.external.toString &&
                   window.external.toString().indexOf('Sequentum') !== -1;
        } catch (e) {
            return false;
        }
    }

    /**
     * Check for Selenium Chrome default marker
     */
    function checkSeleniumChromeDefault() {
        for (let key in window) {
            if (key.indexOf('cdc_') !== -1 || key.indexOf('$cdc_') !== -1) {
                return true;
            }
        }

        // Check in document as well
        for (let key in document) {
            if (key.indexOf('cdc_') !== -1 || key.indexOf('$cdc_') !== -1) {
                return true;
            }
        }

        return false;
    }

    /**
     * Check for headless Chrome indicators
     */
    function checkHeadlessChrome() {
        const indicators = [];

        // Check plugins - headless usually has 0 or 1
        if (navigator.plugins && navigator.plugins.length <= 1) {
            indicators.push(`lowPluginCount (${navigator.plugins.length} plugins)`);
        }

        // Check languages
        if (!navigator.languages || navigator.languages.length === 0) {
            indicators.push('noLanguages');
        }

        // Check permission query behavior
        try {
            if (typeof navigator.permissions === 'undefined') {
                indicators.push('noPermissions');
            }
        } catch (e) {
            indicators.push('permissionsError');
        }

        // Check for Chrome specific headless features
        if (/HeadlessChrome/.test(navigator.userAgent)) {
            indicators.push('headlessInUA');
        }

        if (indicators.length > 0) {
            return {
                indicators,
                description: `Headless Chrome detected: ${indicators.slice(0, 2).join(', ')}${indicators.length > 2 ? '...' : ''}`
            };
        }

        return false;
    }

    /**
     * Check client hints consistency
     */
    function checkInconsistentClientHints() {
        if (!navigator.userAgentData) {
            return false; // Not supported, can't check
        }

        const hints = navigator.userAgentData;
        const ua = navigator.userAgent;
        const inconsistencies = [];

        // Check brand consistency
        if (hints.brands) {
            const hasChromeBrand = hints.brands.some(b => b.brand.includes('Chrome') || b.brand.includes('Chromium'));
            const uaHasChrome = /Chrome/.test(ua) || /Chromium/.test(ua);

            if (hasChromeBrand !== uaHasChrome) {
                inconsistencies.push('brandMismatch');
            }
        }

        // Check platform consistency (basic)
        const platform = hints.platform;
        const uaPlatform = navigator.platform;

        if (platform && uaPlatform) {
            const platformMap = {
                'Windows': /Win/,
                'macOS': /Mac/,
                'Linux': /Linux/,
                'Android': /Android/,
                'iOS': /iPhone|iPad|iPod/
            };

            let platformMatch = false;
            for (const [hintPlatform, uaPattern] of Object.entries(platformMap)) {
                if (platform.includes(hintPlatform) && uaPattern.test(uaPlatform)) {
                    platformMatch = true;
                    break;
                }
            }

            if (!platformMatch && platform !== uaPlatform) {
                inconsistencies.push('platformMismatch');
            }
        }

        if (inconsistencies.length > 0) {
            return {
                inconsistencies,
                description: `Client hints inconsistent: ${inconsistencies.join(', ')} - possible UA spoofing`
            };
        }

        return false;
    }

    /**
     * Check WebGL for inconsistencies
     */
    function checkWebGLInconsistent() {
        try {
            const canvas = document.createElement('canvas');
            const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');

            if (!gl) return { reason: 'webglNotSupported', description: 'WebGL not supported - suspicious for modern browser' };

            const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
            if (!debugInfo) return false; // Cannot determine

            const vendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
            const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);

            // Check for headless/swiftshader indicators
            const suspiciousRenderers = [
                'SwiftShader', 'llvmpipe', 'software', 'Google SwiftShader'
            ];

            if (suspiciousRenderers.some(r => renderer && renderer.indexOf(r) !== -1)) {
                return {
                    vendor,
                    renderer,
                    reason: 'softwareRenderer',
                    description: `Software renderer detected: ${renderer}`
                };
            }

            // Check for null/undefined values
            if (!vendor || !renderer) {
                return {
                    vendor: vendor || 'null',
                    renderer: renderer || 'null',
                    reason: 'missingInfo',
                    description: 'Missing WebGL vendor/renderer info'
                };
            }

            return false;
        } catch (e) {
            return { reason: 'exception', message: e.message, description: `WebGL error: ${e.message}` };
        }
    }

    /**
     * Check for inconsistent GPU features
     */
    function checkInconsistentGPUFeatures() {
        try {
            const canvas = document.createElement('canvas');
            const gl = canvas.getContext('webgl');

            if (!gl) return { reason: 'webglNotSupported', description: 'WebGL not available - suspicious for modern browsers' };

            const maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
            const maxViewportDims = gl.getParameter(gl.MAX_VIEWPORT_DIMS);

            // Extremely low limits indicate software rendering (2048 is common for integrated GPUs)
            if (maxTextureSize < 1024 || (maxViewportDims && maxViewportDims[0] < 1024)) {
                return {
                    maxTextureSize,
                    maxViewportDims: maxViewportDims ? `${maxViewportDims[0]}x${maxViewportDims[1]}` : 'N/A',
                    reason: 'veryLowLimits',
                    description: `Very low GPU limits (texture: ${maxTextureSize}) suggest software rendering`
                };
            }

            return false;
        } catch (e) {
            return { reason: 'exception', message: e.message, description: 'Error accessing WebGL' };
        }
    }

    /**
     * Check CDP via Error.prepareStackTrace
     */
    function checkCDPViaStackTrace() {
        try {
            let accessed = false;
            const originalPrepareStackTrace = Error.prepareStackTrace;
            Error.prepareStackTrace = function(e, trace) {
                accessed = true;
                return originalPrepareStackTrace ? originalPrepareStackTrace(e, trace) : trace.toString();
            };
            const err = new Error('');
            void err.stack; // Must access .stack to trigger prepareStackTrace
            Error.prepareStackTrace = originalPrepareStackTrace; // Restore

            if (accessed) {
                return { reason: 'prepareStackTraceAccessed', description: 'Error.prepareStackTrace was accessed - CDP/devtools detected' };
            }
            return false;
        } catch (e) {
            return false;
        }
    }

    /**
     * Check audio fingerprint for headless indicators
     */
    function checkAudioFingerprint() {
        return new Promise((resolve) => {
            try {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                const OfflineAudioContext = window.OfflineAudioContext || window.webkitOfflineAudioContext;

                if (!AudioContext || !OfflineAudioContext) {
                    resolve({ reason: 'audioNotSupported', description: 'AudioContext not available' });
                    return;
                }

                // Try to create offline context for fingerprinting
                const ctx = new OfflineAudioContext(1, 44100, 44100);
                const osc = ctx.createOscillator();
                const compressor = ctx.createDynamicsCompressor();

                osc.type = 'triangle';
                osc.frequency.value = 10000;

                compressor.threshold.value = -50;
                compressor.knee.value = 40;
                compressor.ratio.value = 12;
                compressor.attack.value = 0;
                compressor.release.value = 0.25;

                osc.connect(compressor);
                compressor.connect(ctx.destination);
                osc.start(0);

                ctx.startRendering();
                ctx.oncomplete = function(e) {
                    try {
                        const buffer = e.renderedBuffer.getChannelData(0);
                        // Sum samples from 4500-5000 range
                        let sum = 0;
                        for (let i = 4500; i < 5000; i++) {
                            sum += Math.abs(buffer[i]);
                        }

                        // Headless Chrome produces different sums than normal Chrome
                        // Normal Chrome typically produces non-zero values
                        if (sum === 0 || sum < 0.001) {
                            resolve({
                                sum: sum.toFixed(6),
                                reason: 'suspiciousSum',
                                description: `Audio fingerprint sum (${sum.toFixed(6)}) indicates headless/sandboxed environment`
                            });
                        } else {
                            resolve(false);
                        }
                    } catch (err) {
                        resolve({ reason: 'processingError', description: 'Error processing audio data' });
                    }
                };

                // Timeout fallback
                setTimeout(() => resolve({ reason: 'timeout', description: 'Audio fingerprint timed out' }), 2000);
            } catch (e) {
                resolve({ reason: 'exception', description: `Audio fingerprint error: ${e.message}` });
            }
        });
    }

    /**
     * Check canvas fingerprint consistency
     */
    function checkCanvasFingerprint() {
        try {
            const canvas = document.createElement('canvas');
            canvas.width = 400;
            canvas.height = 200;
            const ctx = canvas.getContext('2d');

            // Draw standard fingerprint content
            ctx.rect(0, 0, 10, 10);
            ctx.rect(2, 2, 6, 6);
            ctx.textBaseline = 'alphabetic';
            ctx.fillStyle = '#f60';
            ctx.fillRect(125, 1, 62, 20);
            ctx.fillStyle = '#069';
            ctx.font = '11pt no-real-font-123';
            ctx.fillText('Cwm fjordbank glyphs vext quiz, 😃', 2, 15);
            ctx.fillStyle = 'rgba(102, 204, 0, 0.2)';
            ctx.font = '18pt Arial';
            ctx.fillText('Cwm fjordbank glyphs vext quiz, 😃', 4, 45);
            ctx.globalCompositeOperation = 'multiply';
            ctx.fillStyle = 'rgb(255,0,255)';
            ctx.beginPath();
            ctx.arc(50, 50, 50, 0, 2 * Math.PI, true);
            ctx.closePath();
            ctx.fill();
            ctx.fillStyle = 'rgb(0,255,255)';
            ctx.beginPath();
            ctx.arc(100, 50, 50, 0, 2 * Math.PI, true);
            ctx.closePath();
            ctx.fill();
            ctx.fillStyle = 'rgb(255,255,0)';
            ctx.beginPath();
            ctx.arc(75, 100, 50, 0, 2 * Math.PI, true);
            ctx.closePath();
            ctx.fill();
            ctx.fillStyle = 'rgb(255,0,255)';
            ctx.arc(75, 75, 75, 0, 2 * Math.PI, true);
            ctx.arc(75, 75, 25, 0, 2 * Math.PI, true);
            ctx.fill('evenodd');

            // Check if we got valid pixel data
            const data = canvas.toDataURL();
            if (!data || data.length < 100) {
                return { reason: 'emptyCanvas', description: 'Canvas produced empty/invalid data' };
            }

            return false;
        } catch (e) {
            return { reason: 'exception', description: `Canvas error: ${e.message}` };
        }
    }

    /**
     * Check for CDP automation in main context
     */
    function checkAutomatedWithCDP() {
        const cdpMarkers = [
            '__cdp_eval', '__cdp_js_executor', '__selenium_eval',
            '__fxdriver_eval', '__webdriver_eval', 'cdc_adoQpoasnfa76pfcZLmcfl_',
            '$cdc_asdjflasutopfhvcZLmcfl_'
        ];

        for (const marker of cdpMarkers) {
            if (typeof window[marker] !== 'undefined') {
                return { marker, description: `CDP marker found: ${marker}` };
            }
        }

        return false;
    }

    /**
     * Check for iframe behavior is overridden
     */
    function checkIframeOverridden() {
        try {
            const iframe = document.createElement('iframe');
            iframe.style.display = 'none';
            document.body.appendChild(iframe);

            const contentWindow = iframe.contentWindow;

            // Check if contentWindow has been tampered with
            const originalToString = Object.prototype.toString.call(contentWindow);
            const expectedToString = '[object Window]';

            // Try to access a property that should exist
            const hasNavigator = 'navigator' in contentWindow;
            const navigatorProto = contentWindow.navigator && Object.getPrototypeOf(contentWindow.navigator);

            document.body.removeChild(iframe);

            // If contentWindow has been overridden, these checks might fail
            if (!hasNavigator) {
                return { reason: 'noNavigator', description: 'Iframe navigator missing - anti-detection script likely active' };
            }

            // Check if toString has been modified
            if (contentWindow.toString && contentWindow.toString.toString().indexOf('[native code]') === -1) {
                return { reason: 'toStringModified', description: 'Iframe toString modified - anti-detection evasion detected' };
            }

            return false;
        } catch (e) {
            return { reason: 'exception', message: e.message, description: `Iframe check error: ${e.message}` };
        }
    }

    /**
     * Check hardware concurrency
     */
    function checkHighHardwareConcurrency() {
        const cores = navigator.hardwareConcurrency;

        if (!cores || cores === 0) {
            return false; // Not available
        }

        // High core counts might indicate cloud/VM environments
        if (cores > 16) {
            return {
                cores,
                threshold: 16,
                description: `${cores} CPU cores detected (high for consumer device) - possible VM/cloud environment`
            };
        }

        return false;
    }

    /**
     * Check for headless Chrome default screen resolution
     */
    function checkHeadlessResolution() {
        const width = window.screen.width;
        const height = window.screen.height;

        // Check for headless defaults
        for (const res of HEADLESS_RESOLUTIONS) {
            if (width === res.width && height === res.height) {
                return {
                    width,
                    height,
                    match: res,
                    description: `Resolution ${width}x${height} matches headless Chrome default`
                };
            }
        }

        // Also check for extremely unusual aspect ratios
        // Portrait mode (0.5-0.7) is common on mobile/rotated monitors
        // Ultrawide (2.0-3.5) is also increasingly common
        const aspectRatio = width / height;
        if (aspectRatio < 0.4 || aspectRatio > 3.5) {
            return {
                width,
                height,
                aspectRatio: aspectRatio.toFixed(2),
                reason: 'extremeAspect',
                description: `Extreme aspect ratio ${aspectRatio.toFixed(2)} detected - may indicate emulation`
            };
        }

        return false;
    }

    /**
     * Run Web Worker based tests
     */
    function runWorkerTests() {
        return new Promise((resolve) => {
            try {
                const workerCode = `
                    self.onmessage = function(e) {
                        const results = {
                            userAgent: navigator.userAgent,
                            webdriver: navigator.webdriver,
                            platform: navigator.platform,
                            hardwareConcurrency: navigator.hardwareConcurrency,
                            languages: navigator.languages,
                            hasCDP: false
                        };

                        // Check for CDP in worker
                        const cdpMarkers = ['__cdp_eval', '__cdp_js_executor', '__selenium_eval'];
                        for (const marker of cdpMarkers) {
                            if (typeof self[marker] !== 'undefined') {
                                results.hasCDP = true;
                                break;
                            }
                        }

                        self.postMessage(results);
                    };
                `;

                const blob = new Blob([workerCode], { type: 'application/javascript' });
                const worker = new Worker(URL.createObjectURL(blob));

                worker.onmessage = function(e) {
                    worker.terminate();
                    resolve(e.data);
                };

                worker.onerror = function(e) {
                    worker.terminate();
                    resolve({ error: e.message });
                };

                // Timeout fallback
                setTimeout(() => {
                    worker.terminate();
                    resolve({ timeout: true });
                }, 2000);

                worker.postMessage('start');
            } catch (e) {
                resolve({ error: e.message, notSupported: true });
            }
        });
    }

    /**
     * Compare main context vs worker context values
     */
    async function checkInconsistentWorkerValues() {
        const workerData = await runWorkerTests();

        if (workerData.error) {
            return { reason: 'workerError', message: workerData.error, description: 'Web Worker failed to execute' };
        }

        if (workerData.notSupported) {
            return false; // Cannot determine - workers not supported
        }

        if (workerData.timeout) {
            return { reason: 'workerTimeout', description: 'Web Worker timed out - possible automation blocking' };
        }

        const inconsistencies = [];
        const details = {};

        // Compare userAgent
        if (workerData.userAgent !== navigator.userAgent) {
            inconsistencies.push('userAgent');
            details.userAgent = { main: navigator.userAgent.slice(0, 50) + '...', worker: workerData.userAgent.slice(0, 50) + '...' };
        }

        // Compare webdriver (treat undefined, false, null as equivalent "not detected")
        const mainWebdriver = navigator.webdriver === true;
        const workerWebdriver = workerData.webdriver === true;
        if (mainWebdriver !== workerWebdriver) {
            inconsistencies.push('webdriver');
            details.webdriver = { main: navigator.webdriver, worker: workerData.webdriver };
        }

        // Compare platform
        if (workerData.platform !== navigator.platform) {
            inconsistencies.push('platform');
            details.platform = { main: navigator.platform, worker: workerData.platform };
        }

        // Compare hardware concurrency
        if (workerData.hardwareConcurrency !== navigator.hardwareConcurrency) {
            inconsistencies.push('hardwareConcurrency');
            details.hardwareConcurrency = { main: navigator.hardwareConcurrency, worker: workerData.hardwareConcurrency };
        }

        if (inconsistencies.length > 0) {
            return {
                inconsistencies,
                details,
                description: `Worker context differs in: ${inconsistencies.join(', ')} - indicates environment spoofing`
            };
        }

        return false;
    }

    /**
     * Check CDP in Web Worker
     */
    async function checkAutomatedWithCDPInWorker() {
        const workerData = await runWorkerTests();
        return workerData.hasCDP === true;
    }

    /**
     * Analyze weak signals collectively
     */
    function analyzeWeakSignals() {
        const signals = [];

        // Check for missing properties that real browsers have
        if (typeof window.devicePixelRatio === 'undefined') {
            signals.push('noDevicePixelRatio');
        }

        // Check for suspicious navigator properties
        if (navigator.vendor === '' || navigator.vendor === undefined) {
            signals.push('noVendor');
        }

        // Check for common evasion attempts
        if (navigator.webdriver === false && /Chrome/.test(navigator.userAgent)) {
            // Setting webdriver to false when it should be undefined is suspicious
            const descriptor = Object.getOwnPropertyDescriptor(navigator, 'webdriver');
            if (descriptor && !descriptor.get && descriptor.value === false) {
                signals.push('fakeWebdriverFalse');
            }
        }

        // Check for overwritten native functions
        const nativeToString = Function.prototype.toString.call(Function.prototype.toString);
        if (nativeToString.indexOf('[native code]') === -1) {
            signals.push('toStringTampered');
        }

        if (signals.length >= 2) {
            const descriptions = {
                'noDevicePixelRatio': 'Missing devicePixelRatio',
                'noVendor': 'Missing navigator.vendor',
                'fakeWebdriverFalse': 'navigator.webdriver set to false (should be undefined)',
                'toStringTampered': 'Function.toString has been modified'
            };

            return {
                signals,
                description: `Weak signals: ${signals.slice(0, 2).map(s => descriptions[s] || s).join(', ')}${signals.length > 2 ? '...' : ''}`
            };
        }

        return false;
    }

    /**
     * Create a result item element
     */
    function createResultElement(label, value, isBoolean = true, details = null) {
        const div = document.createElement('div');
        div.className = 'result-item';

        const labelSpan = document.createElement('span');
        labelSpan.className = 'label';
        labelSpan.textContent = label;

        const valueSpan = document.createElement('span');
        const isFailed = isBoolean ? value : (value !== false && value !== null && value !== undefined);
        valueSpan.className = 'value ' + (isBoolean ? (value ? 'true' : 'false') : (isFailed ? 'true' : 'false'));
        valueSpan.textContent = isBoolean ? (value ? 'YES' : 'NO') : 'YES';

        div.appendChild(labelSpan);
        div.appendChild(valueSpan);

        // Add details tooltip for failed tests
        if (isFailed && details) {
            const detailsSpan = document.createElement('span');
            detailsSpan.className = 'result-details';

            let detailsText = '';
            if (typeof details === 'object') {
                if (details.description) {
                    detailsText = details.description;
                } else if (details.reason) {
                    detailsText = `Reason: ${details.reason}`;
                    if (details.message) detailsText += ` (${details.message})`;
                } else {
                    detailsText = JSON.stringify(details).slice(0, 100);
                }
            } else {
                detailsText = String(details);
            }

            detailsSpan.textContent = detailsText;
            detailsSpan.title = detailsText; // For hover
            div.appendChild(detailsSpan);
            div.classList.add('has-details');
        }

        return div;
    }

    /**
     * Show loading state
     */
    function showLoading(container) {
        container.innerHTML = '<div class="loading"><span class="spinner"></span>Running detection tests...</div>';
    }

    // Expose shared utilities
    window.BotDetectorShared = {
        checkBotUserAgent,
        checkWebdriver,
        checkWebdriverInFrame,
        checkPlaywright,
        checkInconsistentChrome,
        checkPhantomJS,
        checkNightmare,
        checkSequentum,
        checkSeleniumChromeDefault,
        checkHeadlessChrome,
        checkWebGLInconsistent,
        checkAutomatedWithCDP,
        checkCDPViaStackTrace,
        checkAudioFingerprint,
        checkCanvasFingerprint,
        checkInconsistentClientHints,
        checkInconsistentGPUFeatures,
        checkIframeOverridden,
        checkHighHardwareConcurrency,
        checkHeadlessResolution,
        checkInconsistentWorkerValues,
        checkAutomatedWithCDPInWorker,
        analyzeWeakSignals,
        createResultElement,
        showLoading,
        runWorkerTests
    };

})();

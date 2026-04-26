/**
 * Bot Detection Challenge - Static Fingerprinting Detector
 * Runs all static detection tests and displays results
 */

(function() {
    'use strict';

    const shared = window.BotDetectorShared;

    /**
     * Run all static detection tests
     */
    async function runStaticDetection() {
        const results = {
            hasBotUserAgent: shared.checkBotUserAgent(),
            hasWebdriverTrue: shared.checkWebdriver(),
            hasWebdriverInFrameTrue: shared.checkWebdriverInFrame(),
            isPlaywright: shared.checkPlaywright(),
            hasInconsistentChromeObject: shared.checkInconsistentChrome(),
            isPhantom: shared.checkPhantomJS(),
            isNightmare: shared.checkNightmare(),
            isSequentum: shared.checkSequentum(),
            isSeleniumChromeDefault: shared.checkSeleniumChromeDefault(),
            isHeadlessChrome: shared.checkHeadlessChrome(),
            isWebGLInconsistent: shared.checkWebGLInconsistent(),
            isAutomatedWithCDP: shared.checkAutomatedWithCDP(),
            hasInconsistentClientHints: shared.checkInconsistentClientHints(),
            hasInconsistentGPUFeatures: shared.checkInconsistentGPUFeatures(),
            isIframeOverridden: shared.checkIframeOverridden(),
            hasHighHardwareConcurrency: shared.checkHighHardwareConcurrency(),
            hasHeadlessChromeDefaultScreenResolution: shared.checkHeadlessResolution(),
        };

        // Async tests
        results.hasInconsistentWorkerValues = await shared.checkInconsistentWorkerValues();
        results.isAutomatedWithCDPInWebWorker = await shared.checkAutomatedWithCDPInWorker();
        results.hasSuspiciousWeakSignals = shared.analyzeWeakSignals();

        // New tests from device_info.min.js analysis
        results.isAutomatedViaStackTrace = shared.checkCDPViaStackTrace();
        results.hasCanvasFingerprintIssue = shared.checkCanvasFingerprint();
        results.hasAudioFingerprintIssue = await shared.checkAudioFingerprint();

        return results;
    }

    /**
     * Display results in the container
     */
    function displayResults(results, container) {
        container.innerHTML = '';

        const resultsGrid = document.createElement('div');
        resultsGrid.className = 'results-grid';

        // Add all result items
        const resultItems = [
            { label: 'hasBotUserAgent', value: results.hasBotUserAgent },
            { label: 'hasWebdriverTrue', value: results.hasWebdriverTrue },
            { label: 'hasWebdriverInFrameTrue', value: results.hasWebdriverInFrameTrue },
            { label: 'isPlaywright', value: results.isPlaywright },
            { label: 'hasInconsistentChromeObject', value: results.hasInconsistentChromeObject },
            { label: 'isPhantom', value: results.isPhantom },
            { label: 'isNightmare', value: results.isNightmare },
            { label: 'isSequentum', value: results.isSequentum },
            { label: 'isSeleniumChromeDefault', value: results.isSeleniumChromeDefault },
            { label: 'isHeadlessChrome', value: results.isHeadlessChrome !== false, details: results.isHeadlessChrome },
            { label: 'isWebGLInconsistent', value: results.isWebGLInconsistent !== false, details: results.isWebGLInconsistent },
            { label: 'isAutomatedWithCDP', value: results.isAutomatedWithCDP },
            { label: 'isAutomatedWithCDPInWebWorker', value: results.isAutomatedWithCDPInWebWorker },
            { label: 'hasInconsistentClientHints', value: results.hasInconsistentClientHints !== false, details: results.hasInconsistentClientHints },
            { label: 'hasInconsistentGPUFeatures', value: results.hasInconsistentGPUFeatures !== false, details: results.hasInconsistentGPUFeatures },
            { label: 'isIframeOverridden', value: results.isIframeOverridden !== false, details: results.isIframeOverridden },
            { label: 'hasInconsistentWorkerValues', value: results.hasInconsistentWorkerValues !== false, details: results.hasInconsistentWorkerValues },
            { label: 'hasHighHardwareConcurrency', value: results.hasHighHardwareConcurrency !== false, details: results.hasHighHardwareConcurrency },
            { label: 'hasHeadlessChromeDefaultScreenResolution', value: results.hasHeadlessChromeDefaultScreenResolution !== false, details: results.hasHeadlessChromeDefaultScreenResolution },
            { label: 'hasSuspiciousWeakSignals', value: results.hasSuspiciousWeakSignals !== false, details: results.hasSuspiciousWeakSignals },
            { label: 'isAutomatedViaStackTrace', value: results.isAutomatedViaStackTrace !== false, details: results.isAutomatedViaStackTrace },
            { label: 'hasCanvasFingerprintIssue', value: results.hasCanvasFingerprintIssue !== false, details: results.hasCanvasFingerprintIssue },
            { label: 'hasAudioFingerprintIssue', value: results.hasAudioFingerprintIssue !== false, details: results.hasAudioFingerprintIssue },
        ];

        for (const item of resultItems) {
            const isBoolean = typeof item.value === 'boolean';
            const hasDetails = item.details !== undefined && item.details !== false;
            resultsGrid.appendChild(shared.createResultElement(item.label, item.value, isBoolean, hasDetails ? item.details : null));
        }

        container.appendChild(resultsGrid);

        // Update overall status
        updateOverallStatus(results);
    }

    /**
     * Update overall bot/human status
     */
    function updateOverallStatus(results) {
        const statusContainer = document.getElementById('overall-status');
        if (!statusContainer) return;

        // Count positive detections
        let botIndicators = 0;
        const criticalTests = [
            'hasWebdriverTrue',
            'hasWebdriverInFrameTrue',
            'isPlaywright',
            'isPhantom',
            'isSeleniumChromeDefault'
        ];

        for (const test of criticalTests) {
            if (results[test] === true) {
                botIndicators++;
            }
        }

        // Check array/object results (tests that return objects when failed)
        if (results.isHeadlessChrome && results.isHeadlessChrome.indicators) botIndicators++;
        if (results.isWebGLInconsistent) botIndicators++;
        if (results.isAutomatedWithCDP) botIndicators++;
        if (results.hasInconsistentWorkerValues) botIndicators++;
        if (results.hasInconsistentGPUFeatures) botIndicators++;
        if (results.hasInconsistentClientHints) botIndicators++;
        if (results.isIframeOverridden) botIndicators++;
        if (results.hasHighHardwareConcurrency) botIndicators++;
        if (results.hasHeadlessChromeDefaultScreenResolution) botIndicators++;
        if (results.hasSuspiciousWeakSignals) botIndicators++;
        if (results.isAutomatedViaStackTrace) botIndicators++;
        if (results.hasCanvasFingerprintIssue) botIndicators++;
        if (results.hasAudioFingerprintIssue) botIndicators++;

        let statusClass, statusText;
        if (botIndicators >= 2) {
            statusClass = 'bot';
            statusText = `BOT DETECTED (${botIndicators} indicators)`;
        } else if (botIndicators === 1) {
            statusClass = 'pending';
            statusText = `SUSPICIOUS (${botIndicators} indicator)`;
        } else {
            statusClass = 'human';
            statusText = 'HUMAN (0 indicators)';
        }

        statusContainer.innerHTML = `<span class="status-badge ${statusClass}">${statusText}</span>`;
    }

    /**
     * Initialize and run detection
     */
    async function init() {
        const resultsContainer = document.getElementById('static-results');
        if (!resultsContainer) return;

        shared.showLoading(resultsContainer);

        // Small delay to let page render
        await new Promise(r => setTimeout(r, 100));

        const results = await runStaticDetection();
        displayResults(results, resultsContainer);

        // Store results globally for test mode access
        window.lastStaticResults = results;
    }

    /**
     * Simulate bot signatures for testing
     */
    function simulateBotMode() {
        // Override navigator properties to simulate bot
        const originalWebdriver = navigator.webdriver;
        const originalUA = navigator.userAgent;

        // Create temporary overrides
        Object.defineProperty(navigator, 'webdriver', {
            get: () => true,
            configurable: true
        });

        // Add Selenium marker
        window.$cdc_asdjflasutopfhvcZLmcfl_ = {};

        // Re-run detection
        init();

        // Cleanup after detection
        setTimeout(() => {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => originalWebdriver,
                configurable: true
            });
            delete window.$cdc_asdjflasutopfhvcZLmcfl_;
        }, 500);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose functions
    window.StaticDetector = {
        run: init,
        simulateBot: simulateBotMode
    };

})();

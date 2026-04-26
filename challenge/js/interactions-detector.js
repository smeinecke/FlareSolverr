/**
 * Bot Detection Challenge - Interactions Detector
 * Tracks mouse movements, typing patterns, and form submission timing
 */

(function() {
    'use strict';

    const shared = window.BotDetectorShared;

    // Tracking state
    let tracking = {
        mouseEvents: [],
        keyEvents: [],
        formStartTime: null,
        firstFocusTime: null,
        lastActivityTime: null,
        submitTime: null,
        totalKeystrokes: 0,
        mousePathLength: 0,
        lastMousePos: null,
        cdpLeakChecks: []
    };

    const MAX_EVENTS = 500; // Prevent memory issues

    /**
     * Start tracking interactions
     */
    function startTracking() {
        resetTracking();

        // Mouse tracking
        document.addEventListener('mousemove', onMouseMove, { passive: true });
        document.addEventListener('mousedown', onMouseDown, { passive: true });
        document.addEventListener('mouseup', onMouseUp, { passive: true });

        // Keyboard tracking
        document.addEventListener('keydown', onKeyDown, { passive: true });
        document.addEventListener('keyup', onKeyUp, { passive: true });
        document.addEventListener('keypress', onKeyPress, { passive: true });

        // Focus tracking for form
        const form = document.getElementById('login-form');
        if (form) {
            form.addEventListener('focusin', onFormFocus, { passive: true });
            form.addEventListener('submit', onFormSubmit);
        }

        // Track all inputs in the form
        const inputs = document.querySelectorAll('#login-form input');
        inputs.forEach(input => {
            input.addEventListener('focus', () => {
                if (!tracking.firstFocusTime) {
                    tracking.firstFocusTime = Date.now();
                }
                tracking.lastActivityTime = Date.now();
            });
            input.addEventListener('input', onInput);
        });

        tracking.formStartTime = Date.now();
    }

    /**
     * Reset tracking state
     */
    function resetTracking() {
        tracking = {
            mouseEvents: [],
            keyEvents: [],
            formStartTime: null,
            firstFocusTime: null,
            lastActivityTime: null,
            submitTime: null,
            totalKeystrokes: 0,
            mousePathLength: 0,
            lastMousePos: null,
            cdpLeakChecks: []
        };
    }

    /**
     * Mouse move handler with CDP leak detection
     */
    function onMouseMove(e) {
        const now = Date.now();
        const pos = { x: e.clientX, y: e.clientY };

        // CDP mouse leak detection
        // CDP-injected mouse events often have screenX === clientX (no scrollbar offset)
        const scrollX = window.scrollX || window.pageXOffset || 0;
        const scrollY = window.scrollY || window.pageYOffset || 0;
        const expectedScreenX = pos.x + scrollX;
        const expectedScreenY = pos.y + scrollY;

        const screenMismatch = Math.abs(e.screenX - expectedScreenX) > 2 ||
                               Math.abs(e.screenY - expectedScreenY) > 2;

        if (tracking.mouseEvents.length < MAX_EVENTS) {
            tracking.mouseEvents.push({
                type: 'move',
                x: pos.x,
                y: pos.y,
                screenX: e.screenX,
                screenY: e.screenY,
                time: now,
                screenMismatch
            });
        }

        // Calculate path length
        if (tracking.lastMousePos) {
            const dx = pos.x - tracking.lastMousePos.x;
            const dy = pos.y - tracking.lastMousePos.y;
            tracking.mousePathLength += Math.sqrt(dx * dx + dy * dy);
        }
        tracking.lastMousePos = pos;

        // Collect CDP leak checks
        if (tracking.cdpLeakChecks.length < 100) {
            tracking.cdpLeakChecks.push(screenMismatch);
        }

        tracking.lastActivityTime = now;
    }

    function onMouseDown(e) {
        if (tracking.mouseEvents.length < MAX_EVENTS) {
            tracking.mouseEvents.push({
                type: 'down',
                x: e.clientX,
                y: e.clientY,
                button: e.button,
                time: Date.now()
            });
        }
    }

    function onMouseUp(e) {
        if (tracking.mouseEvents.length < MAX_EVENTS) {
            tracking.mouseEvents.push({
                type: 'up',
                x: e.clientX,
                y: e.clientY,
                button: e.button,
                time: Date.now()
            });
        }
    }

    function onKeyDown(e) {
        if (tracking.keyEvents.length < MAX_EVENTS) {
            tracking.keyEvents.push({
                type: 'down',
                key: e.key,
                code: e.code,
                time: Date.now()
            });
        }
        tracking.totalKeystrokes++;
        tracking.lastActivityTime = Date.now();
    }

    function onKeyUp(e) {
        if (tracking.keyEvents.length < MAX_EVENTS) {
            tracking.keyEvents.push({
                type: 'up',
                key: e.key,
                code: e.code,
                time: Date.now()
            });
        }
        tracking.lastActivityTime = Date.now();
    }

    function onKeyPress(e) {
        tracking.lastActivityTime = Date.now();
    }

    function onInput(e) {
        tracking.lastActivityTime = Date.now();
    }

    function onFormFocus(e) {
        if (!tracking.firstFocusTime) {
            tracking.firstFocusTime = Date.now();
        }
    }

    /**
     * Form submission handler
     */
    function onFormSubmit(e) {
        e.preventDefault();
        tracking.submitTime = Date.now();

        analyzeAndShowResults();
    }

    /**
     * Analyze all tracking data
     */
    function analyzeTrackingData() {
        const results = {
            // Include static tests
            hasBotUserAgent: shared.checkBotUserAgent(),
            hasWebdriverTrue: shared.checkWebdriver(),
            hasWebdriverInFrameTrue: shared.checkWebdriverInFrame(),
            isPlaywright: shared.checkPlaywright(),
            isSeleniumChromeDefault: shared.checkSeleniumChromeDefault(),
            isHeadlessChrome: shared.checkHeadlessChrome(),
            isAutomatedWithCDP: shared.checkAutomatedWithCDP(),
        };

        // Interaction-based tests
        results.suspiciousClientSideBehavior = analyzeSuspiciousBehavior();
        results.superHumanSpeed = analyzeSuperHumanSpeed();
        results.hasCDPMouseLeak = analyzeCDPMouseLeak();

        return results;
    }

    /**
     * Analyze for suspicious client-side behavior
     */
    function analyzeSuspiciousBehavior() {
        const suspicious = [];

        // Check for no mouse movement
        if (tracking.mouseEvents.length < 10) {
            suspicious.push('insufficientMouseMovement');
        }

        // Check for perfectly straight lines (bot-like movement)
        if (tracking.mouseEvents.length > 50) {
            const straightLines = countStraightLines();
            const moveEvents = tracking.mouseEvents.filter(e => e.type === 'move').length;
            // Very high threshold - humans have some jitter even when moving "straight"
            if (moveEvents > 30 && straightLines > moveEvents * 0.95) {
                suspicious.push('tooManyStraightLines');
            }
        }

        // Check for uniform timing between events
        if (tracking.mouseEvents.length > 20) {
            const uniformTiming = checkUniformTiming(tracking.mouseEvents);
            if (uniformTiming) {
                suspicious.push('uniformEventTiming');
            }
        }

        // Check for instant form completion
        const formDuration = tracking.submitTime - tracking.firstFocusTime;
        if (tracking.firstFocusTime && formDuration < 1000) { // Less than 1 second
            suspicious.push('instantFormCompletion');
        }

        // Check for no typing (paste-only)
        if (tracking.totalKeystrokes === 0 && tracking.submitTime) {
            const emailField = document.getElementById('email');
            const passwordField = document.getElementById('password');
            if ((emailField && emailField.value) || (passwordField && passwordField.value)) {
                suspicious.push('pasteOnlyInput');
            }
        }

        if (suspicious.length > 0) {
            const descriptions = {
                'insufficientMouseMovement': `Only ${tracking.mouseEvents.length} mouse events detected`,
                'tooManyStraightLines': 'Mouse path shows >80% straight lines (bot-like)',
                'uniformEventTiming': 'Mouse events have suspiciously uniform timing',
                'instantFormCompletion': `Form completed in ${formDuration}ms - too fast`,
                'pasteOnlyInput': 'Form filled without keystrokes (paste-only)'
            };

            return {
                behaviors: suspicious,
                description: suspicious.map(b => descriptions[b] || b).join('; ')
            };
        }

        return false;
    }

    /**
     * Count straight line segments in mouse path
     */
    function countStraightLines() {
        let straightCount = 0;
        const moveEvents = tracking.mouseEvents.filter(e => e.type === 'move');

        for (let i = 2; i < moveEvents.length; i++) {
            const p1 = moveEvents[i - 2];
            const p2 = moveEvents[i - 1];
            const p3 = moveEvents[i];

            // Check if three points are collinear (approximately)
            // Using cross product: if result is near 0, points are collinear
            const crossProduct = Math.abs((p2.x - p1.x) * (p3.y - p2.y) - (p2.y - p1.y) * (p3.x - p2.x));
            // Threshold: allow some natural wobble in human movement
            // Scale threshold by distance - longer lines can have more deviation
            const distance = Math.sqrt(Math.pow(p3.x - p1.x, 2) + Math.pow(p3.y - p1.y, 2));
            const threshold = Math.max(50, distance * 0.1); // 10% of line length or minimum 50px
            if (crossProduct < threshold) {
                straightCount++;
            }
        }

        return straightCount;
    }

    /**
     * Check for uniform timing between events
     */
    function checkUniformTiming(events) {
        if (events.length < 10) return false;

        const intervals = [];
        for (let i = 1; i < events.length; i++) {
            intervals.push(events[i].time - events[i - 1].time);
        }

        const avg = intervals.reduce((a, b) => a + b, 0) / intervals.length;
        const variance = intervals.reduce((acc, val) => acc + Math.pow(val - avg, 2), 0) / intervals.length;
        const stdDev = Math.sqrt(variance);

        // If standard deviation is very low, timing is suspiciously uniform
        return stdDev < 5; // Less than 5ms variance
    }

    /**
     * Analyze for super-human typing speed
     */
    function analyzeSuperHumanSpeed() {
        if (!tracking.firstFocusTime || !tracking.submitTime) {
            return false;
        }

        const totalTime = tracking.submitTime - tracking.firstFocusTime;
        const keystrokes = tracking.totalKeystrokes;

        if (keystrokes === 0) return false;

        // Calculate typing speed (characters per second)
        const cps = keystrokes / (totalTime / 1000);

        // Human typing is typically 3-8 CPS, superhuman is > 15 CPS
        if (cps > 15) {
            return {
                charsPerSecond: cps.toFixed(1),
                totalTime: totalTime,
                keystrokes: keystrokes,
                threshold: 15,
                description: `Typing speed ${cps.toFixed(1)} CPS exceeds human limit (15 CPS)`
            };
        }

        // Also check for suspiciously fast form completion
        if (totalTime < 500 && keystrokes > 5) {
            return {
                charsPerSecond: cps.toFixed(1),
                totalTime: totalTime,
                keystrokes: keystrokes,
                reason: 'tooFastCompletion',
                description: `Form completed in ${totalTime}ms - too fast for human input`
            };
        }

        return false;
    }

    /**
     * Analyze for CDP mouse leak
     */
    function analyzeCDPMouseLeak() {
        if (tracking.cdpLeakChecks.length < 20) {
            return false; // Not enough data
        }

        const mismatches = tracking.cdpLeakChecks.filter(m => m).length;
        const ratio = mismatches / tracking.cdpLeakChecks.length;

        // If more than 80% of mouse events show screen coordinate mismatch
        // and we have scrollbars, this indicates CDP mouse leak
        const hasScrollbars = document.documentElement.scrollHeight > window.innerHeight ||
                             document.documentElement.scrollWidth > window.innerWidth;

        if (ratio > 0.8 && hasScrollbars) {
            return {
                mismatchRatio: ratio.toFixed(2),
                totalEvents: tracking.cdpLeakChecks.length,
                mismatches: mismatches,
                hasScrollbars: true,
                description: `${(ratio * 100).toFixed(0)}% mouse events show CDP screen coordinate leak`
            };
        }

        // Also check for suspiciously exact screen coordinates
        // CDP automation often sets screenX/Y to clientX/Y without adding window position offset
        // In normal browsers, screenX = clientX + window.screenX (window position on screen)
        const windowScreenX = typeof window.screenX !== 'undefined' ? window.screenX : window.screenLeft || 0;
        const windowScreenY = typeof window.screenY !== 'undefined' ? window.screenY : window.screenTop || 0;

        // Only meaningful check if window is not at (0,0)
        if (windowScreenX !== 0 || windowScreenY !== 0) {
            // Check if screen coords fail to account for window position
            const suspiciousExactMatches = tracking.mouseEvents.filter(e => {
                if (e.type !== 'move') return false;
                // Expected: screenX = clientX (e.x) + window.screenX
                // CDP bug: screenX = clientX (forgets to add window position)
                const expectedScreenX = e.x + windowScreenX;
                const expectedScreenY = e.y + windowScreenY;
                const screenXWrong = Math.abs(e.screenX - expectedScreenX) < 5;
                const screenYWrong = Math.abs(e.screenY - expectedScreenY) < 5;
                // Suspicious if screen coords match client coords (missing window offset)
                return screenXWrong && screenYWrong;
            }).length;

            if (suspiciousExactMatches > tracking.mouseEvents.length * 0.8 && tracking.mouseEvents.length > 20) {
                const ratio = suspiciousExactMatches / tracking.mouseEvents.length;
                return {
                    exactMatchRatio: ratio.toFixed(2),
                    windowPosition: { x: windowScreenX, y: windowScreenY },
                    reason: 'missingWindowOffset',
                    description: `${(ratio * 100).toFixed(0)}% events missing window position offset - CDP artifact`
                };
            }
        }

        return false;
    }

    /**
     * Display interaction analysis results
     */
    function displayResults(results, container) {
        container.innerHTML = '';

        // Interaction tests
        const interactionSection = document.createElement('div');
        interactionSection.innerHTML = '<h3>Interaction Analysis</h3>';

        const resultsGrid = document.createElement('div');
        resultsGrid.className = 'results-grid';

        const resultItems = [
            { label: 'suspiciousClientSideBehavior', value: results.suspiciousClientSideBehavior !== false, details: results.suspiciousClientSideBehavior },
            { label: 'superHumanSpeed', value: results.superHumanSpeed !== false, details: results.superHumanSpeed },
            { label: 'hasCDPMouseLeak', value: results.hasCDPMouseLeak !== false, details: results.hasCDPMouseLeak },
        ];

        for (const item of resultItems) {
            const isBoolean = typeof item.value === 'boolean';
            const hasDetails = item.details !== undefined && item.details !== false && item.details !== null;
            resultsGrid.appendChild(shared.createResultElement(item.label, item.value, isBoolean, hasDetails ? item.details : null));
        }

        interactionSection.appendChild(resultsGrid);
        container.appendChild(interactionSection);

        // Static tests section
        const staticSection = document.createElement('div');
        staticSection.innerHTML = '<h3>Static Fingerprinting</h3>';

        const staticGrid = document.createElement('div');
        staticGrid.className = 'results-grid';

        const staticItems = [
            { label: 'hasBotUserAgent', value: results.hasBotUserAgent },
            { label: 'hasWebdriverTrue', value: results.hasWebdriverTrue },
            { label: 'hasWebdriverInFrameTrue', value: results.hasWebdriverInFrameTrue },
            { label: 'isPlaywright', value: results.isPlaywright },
            { label: 'isSeleniumChromeDefault', value: results.isSeleniumChromeDefault },
            { label: 'isHeadlessChrome', value: results.isHeadlessChrome !== false },
            { label: 'isAutomatedWithCDP', value: results.isAutomatedWithCDP },
        ];

        for (const item of staticItems) {
            staticGrid.appendChild(shared.createResultElement(item.label, item.value, true));
        }

        staticSection.appendChild(staticGrid);
        container.appendChild(staticSection);

        // Update overall status
        updateOverallStatus(results);

        // Add tracking stats
        addTrackingStats(container);
    }

    /**
     * Add tracking statistics
     */
    function addTrackingStats(container) {
        const statsDiv = document.createElement('div');
        statsDiv.className = 'info-section';
        statsDiv.innerHTML = `
            <h3>Tracking Statistics</h3>
            <ul>
                <li>Mouse events: ${tracking.mouseEvents.length}</li>
                <li>Key events: ${tracking.keyEvents.length}</li>
                <li>Mouse path length: ${Math.round(tracking.mousePathLength)} px</li>
                <li>Total keystrokes: ${tracking.totalKeystrokes}</li>
                <li>Form completion time: ${tracking.submitTime && tracking.firstFocusTime ?
                    (tracking.submitTime - tracking.firstFocusTime) + ' ms' : 'N/A'}</li>
            </ul>
        `;
        container.appendChild(statsDiv);
    }

    /**
     * Update overall bot/human status
     */
    function updateOverallStatus(results) {
        const statusContainer = document.getElementById('overall-status');
        if (!statusContainer) return;

        let botIndicators = 0;

        // Static indicators
        const staticTests = ['hasWebdriverTrue', 'hasWebdriverInFrameTrue', 'isPlaywright', 'isSeleniumChromeDefault'];
        for (const test of staticTests) {
            if (results[test] === true) botIndicators++;
        }
        if (results.isHeadlessChrome && results.isHeadlessChrome.indicators) botIndicators++;
        if (results.isAutomatedWithCDP) botIndicators++;

        // Interaction indicators
        if (results.suspiciousClientSideBehavior) botIndicators++;
        if (results.superHumanSpeed) botIndicators++;
        if (results.hasCDPMouseLeak) botIndicators++;

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
     * Analyze and show results
     */
    function analyzeAndShowResults() {
        const container = document.getElementById('interaction-results');
        if (container) {
            container.innerHTML = '<div class="loading"><span class="spinner"></span>Analyzing interactions...</div>';
        }

        // Small delay to show loading state
        setTimeout(() => {
            const results = analyzeTrackingData();
            if (container) {
                displayResults(results, container);
            }
            window.lastInteractionResults = results;
        }, 100);
    }

    /**
     * Simulate bot interactions for testing
     */
    function simulateBotMode() {
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => true,
            configurable: true
        });

        // Pre-fill form quickly
        const emailField = document.getElementById('email');
        const passwordField = document.getElementById('password');

        if (emailField) {
            emailField.value = 'test@example.com';
            emailField.dispatchEvent(new Event('input', { bubbles: true }));
        }
        if (passwordField) {
            passwordField.value = 'password123';
            passwordField.dispatchEvent(new Event('input', { bubbles: true }));
        }

        // Simulate instant typing
        tracking.totalKeystrokes = 25;
        tracking.firstFocusTime = Date.now() - 200;
        tracking.submitTime = Date.now();

        // Add some mouse events with CDP-like patterns
        for (let i = 0; i < 50; i++) {
            tracking.mouseEvents.push({
                type: 'move',
                x: 100 + i * 5,
                y: 200,
                screenX: 100 + i * 5, // Same as client (no scroll offset)
                screenY: 200,
                time: Date.now() + i * 16,
                screenMismatch: true
            });
            tracking.cdpLeakChecks.push(true);
        }

        // Trigger analysis
        analyzeAndShowResults();
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startTracking);
    } else {
        startTracking();
    }

    // Expose functions
    window.InteractionDetector = {
        start: startTracking,
        reset: resetTracking,
        analyze: analyzeAndShowResults,
        simulateBot: simulateBotMode,
        getTrackingData: () => tracking
    };

})();

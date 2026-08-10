/**
 * stealth.js - minimal JS-only patch layer for custom Chromium builds.
 *
 * Custom Chromium now handles all major stealth signals natively:
 *   - navigator.webdriver (--disable-blink-features=AutomationControlled)
 *   - navigator.languages / language (--stealth-navigator-languages)
 *   - user agent and user-agent client hints (--user-agent command line)
 *   - visualViewport coherence (--stealth-viewport-size)
 *   - mediaDevices.enumerateDevices (--stealth-no-media-devices)
 *   - WebGL vendor/renderer is intentionally not spoofed; it exposes the
 *     natural ANGLE/GPU identity for internal consistency.
 *
 * This file is intentionally empty for custom Chromium. It is still loaded via
 * CDP so that the injection path exists, but it performs no page-side
 * modifications. If a new JS-only defence is needed in the future, it belongs
 * here only until it can be moved into the native layer.
 */

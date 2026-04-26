# Bot Detection Challenge

This directory contains a local bot detection challenge for testing FlareSolverr's stealth capabilities.

## Overview

These pages implement bot detection techniques similar to [deviceandbrowserinfo.com](https://deviceandbrowserinfo.com/are_you_a_bot) but run locally for faster, more reliable testing.

### Pages

- **`index.html`** - Landing page with links to both tests
- **`static.html`** - Static fingerprinting tests (20+ bot detection signals)
- **`interactions.html`** - Interaction-based tests (mouse, typing, timing analysis)

### Static Detection Tests

| Test | Description |
|------|-------------|
| `hasBotUserAgent` | Detects known bot patterns in User-Agent |
| `hasWebdriverTrue` | Checks `navigator.webdriver === true` |
| `hasWebdriverInFrameTrue` | Checks webdriver in iframe context |
| `isPlaywright` | Detects Playwright-specific globals |
| `hasInconsistentChromeObject` | Validates `window.chrome` properties |
| `isPhantom` | Detects PhantomJS |
| `isNightmare` | Detects Nightmare.js |
| `isSequentum` | Detects Sequentum scraping tool |
| `isSeleniumChromeDefault` | Detects Selenium `cdc_` markers |
| `isHeadlessChrome` | Detects headless-specific features |
| `isWebGLInconsistent` | Detects SwiftShader/llvmpipe renderers |
| `isAutomatedWithCDP` | Detects CDP automation markers |
| `isAutomatedViaStackTrace` | Detects CDP via Error.prepareStackTrace |
| `hasCanvasFingerprintIssue` | Validates canvas rendering |
| `hasAudioFingerprintIssue` | Detects headless audio output |
| `hasInconsistentClientHints` | Checks User-Agent Data consistency |
| `hasInconsistentGPUFeatures` | Detects software rendering |
| `isIframeOverridden` | Detects anti-detection scripts |
| `hasInconsistentWorkerValues` | Compares main/worker context values |
| `hasHighHardwareConcurrency` | Detects VM/cloud environments (>16 cores) |
| `hasHeadlessChromeDefaultScreenResolution` | Detects headless resolutions |
| `hasSuspiciousWeakSignals` | Collective weak signal analysis |

### Interaction Detection Tests

| Test | Description |
|------|-------------|
| `suspiciousClientSideBehavior` | Mouse path analysis, form timing |
| `superHumanSpeed` | Typing speed > 15 CPS |
| `hasCDPMouseLeak` | Detects CDP screen coordinate leak |

## Usage

### Manual Testing

1. Open `static.html` in a browser to see static detection results
2. Open `interactions.html`, fill the form, and submit to see interaction analysis
3. Use the "Simulate bot" checkbox to test detection accuracy

### Programmatic Access

Click "Show JSON Output" or "Copy JSON" to get machine-readable results:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "userAgent": "...",
  "url": "...",
  "tests": {
    "hasWebdriverTrue": { "passed": true, "value": false, "description": null },
    "isHeadlessChrome": { "passed": false, "value": {...}, "description": "..." }
  },
  "summary": {
    "totalTests": 22,
    "passed": 20,
    "failed": 2,
    "botDetected": true,
    "indicatorCount": 2
  }
}
```

### Integration with FlareSolverr

Execute JavaScript to retrieve results:

```python
# For static tests
results = driver.execute_script("return JSON.stringify(window.lastStaticResults)")

# For interaction tests
results = driver.execute_script("return JSON.stringify(window.lastInteractionResults)")
```

## Running Tests

### Unit Tests (verify page structure)

```bash
cd /home/stefan/github/FlareSolverr
python -m pytest tests/unit/test_challenge_pages.py -v
```

### Integration Tests (verify FlareSolverr passes)

1. Start FlareSolverr:
   ```bash
   python -m flaresolverr
   ```

2. Run tests:
   ```bash
   cd /home/stefan/github/FlareSolverr
   python -m pytest tests/integration/test_bot_challenge_local.py -v
   ```

### All Integration Tests

```bash
cd /home/stefan/github/FlareSolverr
python -m pytest tests/integration/ -v
```

## GitHub Pages Deployment

To host these pages on GitHub Pages:

1. Go to repository Settings → Pages
2. Set "Source" to "Deploy from a branch"
3. Select branch and set folder to `/challenge`
4. Save and wait for deployment
5. Access at `https://yourusername.github.io/FlareSolverr/`

## False Positive Fixes

Recent fixes for false positives on valid browsers:

- **GPU Features**: Raised threshold from 4096 → 1024 (2048 is normal for integrated GPUs)
- **Worker Webdriver**: Treat `undefined`/`false`/`null` as equivalent "not detected"
- **Straight Lines**: Changed from fixed area threshold to dynamic cross-product with 95% threshold
- **CDP Mouse Leak**: Skip check when window is at (0,0) where screenX === clientX is normal

## File Structure

```
challenge/
├── index.html                 # Landing page
├── static.html               # Static detection page
├── interactions.html         # Interaction detection page
├── css/
│   └── style.css            # Shared styles
├── js/
│   ├── shared.js            # Common detection utilities
│   ├── static-detector.js   # Static test runner
│   └── interactions-detector.js  # Interaction test runner
└── README.md               # This file
```

## References

- Based on detection techniques from [deviceandbrowserinfo.com](https://deviceandbrowserinfo.com/are_you_a_bot)
- Audio fingerprinting based on [fingerprintjs2](https://github.com/Valve/fingerprintjs2)
- CDP detection via [puppeteer-extra-stealth](https://github.com/berstend/puppeteer-extra) evasion techniques

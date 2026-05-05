# Captcha Solvers

FlareSolverr includes a pluggable captcha solver interface.

## Overview

| Solver | Name | Type | Status |
|--------|------|------|--------|
| Built-in | `default` | Cloudflare / DDoS-Guard challenges | Always available |

## Configuration

Set the `CAPTCHA_SOLVER` environment variable to select the active solver (default: `"default"`):

```bash
CAPTCHA_SOLVER=default
```

The `captchaSolver` request parameter overrides this per-request:

```json
{"cmd": "request.get", "url": "https://example.com", "captchaSolver": "default"}
```

An unknown solver name returns an error immediately:

```json
{
  "status": "error",
  "message": "Request parameter 'captchaSolver' = 'unknown' is invalid. Available solvers: ['default']"
}
```

## Default Solver

The built-in `default` solver handles Cloudflare challenges through browser automation. It does not require any additional dependencies and is always available.

### How It Works

The default solver operates through the following steps:

#### 1. Challenge Detection

When a page loads, the solver checks for challenge indicators:

**Page Titles:**
- `Just a moment...` - Cloudflare challenge page
- `DDoS-Guard` - DDoS-Guard protection

**CSS Selectors:**
- `#cf-challenge-running` - Active challenge indicator
- `.ray_id` - Cloudflare Ray ID element
- `#cf-please-wait` - Please wait message
- `#challenge-spinner` - Loading spinner
- `#turnstile-wrapper` - Turnstile captcha container
- `.lds-ring` - Loading animation
- Custom selectors for specific sites (EbookParadijs, Film-Paleis, etc.)

#### 2. Access Denied Check

Before attempting to solve, the solver checks for blocked access:

- Title checks: `Access denied`, `Attention Required! | Cloudflare`
- CSS selectors for error codes
- If detected, returns error: "Cloudflare has blocked this request. Probably your IP is banned"

#### 3. Challenge Resolution

If a challenge is detected, the solver enters a resolution loop:

```
Loop until challenge disappears:
  1. Wait for challenge title to change (timeout: ~2s)
  2. Wait for challenge selectors to disappear from DOM
  3. If timeout occurs:
     - Click the verify checkbox (simulates human interaction)
     - Continue loop
  4. If challenge elements gone: break loop
```

The `click_verify` function:
- Locates the challenge checkbox or turnstile element
- Simulates mouse movement to the element
- Clicks the verify button when present
- Handles "Verify you are human" buttons
- Extracts turnstile tokens if present

#### 4. Post-Solve Handling

After challenge resolution:

1. **Wait for redirect** - Cloudflare typically reloads the page; the solver waits for the original HTML element to become stale
2. **Optional wait** - If `waitInSeconds` is specified, waits before capturing response
3. **Screenshot** - If `returnScreenshot` is true, captures a Base64 PNG
4. **Cookie extraction** - Retrieves all cookies from the browser
5. **Response building** - Returns URL, status, cookies, userAgent, HTML, and optional screenshot

### Turnstile Support

For Turnstile captchas requiring Tab key navigation:

- Set `tabs_till_verify` parameter (number of Tab presses needed)
- The solver presses Tab X times to focus the turnstile
- Extracts the `cf-turnstile-response` token
- Returns token in the `turnstile_token` response field

### Limitations

- **hCaptcha / reCAPTCHA**: Not supported by the default solver
- **Enterprise challenges**: Some enterprise-level Cloudflare protection may not be bypassable
- **Rate limiting**: Repeated failures may result in IP bans

### When to Use

The default solver is ideal for:
- Standard Cloudflare "Checking your browser" challenges
- DDoS-Guard protection pages
- Sites with simple JavaScript challenges
- Turnstile captchas with `tabs_till_verify` parameter

## Custom Solvers

The solver interface is designed for extension. To add a custom solver:

1. Subclass `CaptchaSolver` from `captcha_solvers.py`
2. Implement `name`, `is_available()`, and `solve(driver, captcha_type)`
3. Register it with the global `SOLVER_MANAGER` at startup

```python
from captcha_solvers import CaptchaSolver, SOLVER_MANAGER
from selenium.webdriver.chrome.webdriver import WebDriver
from flaresolverr.backends import BrowserContext

class MySolver(CaptchaSolver):
    name = "my-solver"

    def is_available(self) -> bool:
        return True  # or check for optional dependency

    def solve(self, driver: WebDriver | BrowserContext, captcha_type: str) -> bool:
        # drive the already-open browser session to solve the captcha
        # return True on success, False otherwise
        return False

SOLVER_MANAGER.register_solver(MySolver())
```

Once registered, the solver is selectable via `CAPTCHA_SOLVER=my-solver` or per-request with `"captchaSolver": "my-solver"`.

## References

- [FlareSolverr Issue #738](https://github.com/FlareSolverr/FlareSolverr/issues/738)

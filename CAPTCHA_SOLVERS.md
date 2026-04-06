# Captcha Solvers

FlareSolverr includes a pluggable captcha solver interface that supports multiple solving methods.

## Overview

By default, FlareSolverr uses its built-in browser automation to handle Cloudflare challenges. For sites with hCaptcha or reCAPTCHA challenges, optional AI-based solvers can be installed.

| Solver | Name | Type | Status |
|--------|------|------|--------|
| Built-in | `default` | Cloudflare challenges | Always available |
| [hcaptcha-challenger](https://github.com/QIN2DIM/hcaptcha-challenger) | `hcaptcha-challenger` | hCaptcha | Optional dependency |
| [recaptcha-challenger](https://github.com/QIN2DIM/recaptcha-challenger) | `recaptcha-challenger` | reCAPTCHA | Optional dependency |

## Configuration

Set the `CAPTCHA_SOLVER` environment variable to change the solver:

```bash
CAPTCHA_SOLVER=hcaptcha-challenger
```

If the configured solver is not available or fails to solve a challenge, FlareSolverr will return an error:

```json
{
  "status": "error",
  "message": "Captcha detected but no automatic solver is configured."
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

- **hCaptcha**: Not supported by default solver (requires `hcaptcha-challenger`)
- **reCAPTCHA**: Not supported by default solver (requires `recaptcha-challenger`)
- **Enterprise challenges**: Some enterprise-level Cloudflare protection may not be bypassable
- **Rate limiting**: Repeated failures may result in IP bans

### When to Use

The default solver is ideal for:
- Standard Cloudflare "Checking your browser" challenges
- DDoS-Guard protection pages
- Sites with simple JavaScript challenges
- Turnstile captchas with `tabs_till_verify` parameter

## hcaptcha-challenger

An AI-based solver for hCaptcha challenges using multimodal large language models.

### Installation

Install the optional dependency:

```bash
# From source
pip install hcaptcha-challenger

# Using uv
uv pip install hcaptcha-challenger
```

### Usage

Set the environment variable and make requests:

```bash
export CAPTCHA_SOLVER=hcaptcha-challenger
python src/flaresolverr.py
```

### Requirements

- Python 3.9+
- Additional AI model dependencies (downloaded on first use)
- Sufficient disk space for model files

### Notes

- The solver automatically downloads required AI models on first use
- Processing time depends on hardware capabilities (GPU acceleration recommended)
- See the [hcaptcha-challenger documentation](https://github.com/QIN2DIM/hcaptcha-challenger) for advanced configuration

## recaptcha-challenger

An AI-based solver for reCAPTCHA v2 and v3 challenges.

### Installation

Install the optional dependency:

```bash
# From source
pip install recaptcha-challenger

# Using uv
uv pip install recaptcha-challenger
```

### Usage

Set the environment variable and make requests:

```bash
export CAPTCHA_SOLVER=recaptcha-challenger
python src/flaresolverr.py
```

### Requirements

- Python 3.9+
- Additional AI model dependencies
- Sufficient disk space for model files

### Notes

- Supports reCAPTCHA v2 and v3
- The solver automatically downloads required AI models on first use
- Processing time depends on hardware capabilities
- See the [recaptcha-challenger documentation](https://github.com/QIN2DIM/recaptcha-challenger) for advanced configuration

## Docker Usage

To use an optional solver in Docker, you need to install the dependency when building the image or extend the official image:

```dockerfile
FROM ghcr.io/smeinecke/flaresolverr:latest

# Install additional solver
RUN pip install hcaptcha-challenger

# Set the solver
ENV CAPTCHA_SOLVER=hcaptcha-challenger
```

## Checking Available Solvers

On startup, FlareSolverr logs which solvers are available:

```
INFO hcaptcha-challenger solver loaded successfully
INFO Registered captcha solver: hcaptcha-challenger
```

If a solver is not installed, you'll see:

```
DEBUG hcaptcha-challenger not installed, solver unavailable
```

## Troubleshooting

### Solver not loading

- Verify the package is installed: `pip list | grep challenger`
- Check FlareSolverr logs for import errors
- Ensure Python version compatibility (3.9+)

### Solver fails to solve

- Check that the challenge type matches the solver (hCaptcha vs reCAPTCHA)
- Verify the site doesn't use enterprise/enterprise+ protection
- Check available disk space for model downloads
- Review solver-specific documentation for configuration options

### Model download issues

If AI models fail to download:
- Check internet connectivity from the container/host
- Verify firewall rules allow HTTPS connections
- Manually download models following solver documentation

## References

- [hcaptcha-challenger GitHub](https://github.com/QIN2DIM/hcaptcha-challenger)
- [recaptcha-challenger GitHub](https://github.com/QIN2DIM/recaptcha-challenger)
- [FlareSolverr Issue #738](https://github.com/FlareSolverr/FlareSolverr/issues/738)

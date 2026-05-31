# FlareSolverr

[![Latest release](https://img.shields.io/github/v/release/smeinecke/FlareSolverr)](https://github.com/smeinecke/FlareSolverr/releases)
[![GitHub issues](https://img.shields.io/github/issues/smeinecke/FlareSolverr)](https://github.com/smeinecke/FlareSolverr/issues)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/smeinecke/FlareSolverr)](https://github.com/smeinecke/FlareSolverr/pulls)
[![GitHub Repo stars](https://img.shields.io/github/stars/smeinecke/FlareSolverr)](https://github.com/smeinecke/FlareSolverr)

> **Note:** This is a fork of the original [FlareSolverr/FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) repository with additional features and fixes.

FlareSolverr is a proxy server to bypass Cloudflare and DDoS-GUARD protection.

## How it works

FlareSolverr starts a proxy server, and it waits for user requests in an idle state using few resources.
When some request arrives, it uses [Selenium](https://www.selenium.dev) with the
[undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver)
to create a web browser (Chrome). It opens the URL with user parameters and waits until the Cloudflare challenge
is solved (or timeout). The HTML code and the cookies are sent back to the user, and those cookies can be used to
bypass Cloudflare using other HTTP clients.

**NOTE**: Web browsers consume a lot of memory. If you are running FlareSolverr on a machine with few RAM, do not make
many requests at once. With each request a new browser is launched.

It is also possible to use a permanent session. However, if you use sessions, you should make sure to close them as
soon as you are done using them.

## Installation

### Docker

It is recommended to install using a Docker container because the project depends on an external browser that is
already included within the image.

Docker images are available in:

- GitHub Container Registry => `ghcr.io/smeinecke/flaresolverr:latest`
- GitHub Packages => <https://github.com/smeinecke/FlareSolverr/pkgs/container/flaresolverr>

Supported architectures are:

| Architecture | Tag          | Notes                                           |
| ------------ | ------------ | ----------------------------------------------- |
| x86          | linux/386    | Uses stock Debian Chromium (no stealth patches) |
| x86-64       | linux/amd64  | Includes custom stealth Chromium                |
| ARM32        | linux/arm/v7 | Uses stock Debian Chromium (no stealth patches) |
| ARM64        | linux/arm64  | Uses stock Debian Chromium (no stealth patches) |

> **Note:** The custom stealth-patched Chromium build is only available for **amd64**. On other architectures FlareSolverr falls back to the stock Debian `chromium` package; stealth mode still works but with reduced hardening (CDP-based JS patches only, no C++ binary patches).

We provide a `docker-compose.yml` configuration file. Clone this repository and execute
`docker-compose up -d` _(Compose V1)_ or `docker compose up -d` _(Compose V2)_ to start
the container.

If you prefer the `docker cli` execute the following command:

**Bash**

```bash
docker run -d \
  --name=flaresolverr \
  -p 8191:8191 \
  -e LOG_LEVEL=info \
  --restart unless-stopped \
  ghcr.io/smeinecke/flaresolverr:latest
```

**Command Prompt or Powershell**

```cmd
docker run -d --name=flaresolverr -p 8191:8191 -e LOG_LEVEL=info --restart unless-stopped ghcr.io/smeinecke/flaresolverr:latest
```

If your host OS is Debian, make sure `libseccomp2` version is 2.5.x. You can check the version with `sudo apt-cache policy libseccomp2`
and update the package with `sudo apt install libseccomp2=2.5.1-1~bpo10+1` or `sudo apt install libseccomp2=2.5.1-1+deb11u1`.
Remember to restart the Docker daemon and the container after the update.

### Podman

If you prefer Podman, see [PODMAN.md](./PODMAN.md) for two ready-to-run examples:

- a standard Podman deployment
- a restricted deployment with separate networks and a `dnsdist` DNS sidecar so FlareSolverr itself has no public egress

### HAProxy / Clustering

If you want to run multiple FlareSolverr instances behind a load balancer with session-aware routing, see [HAPROXY.md](./HAPROXY.md). It covers how to use the `X-FlareSolverr-Session` header with HAProxy to ensure requests for the same session always reach the backend that owns it.

### Precompiled binaries

> **Warning**
> Precompiled binaries are only available for x64 architecture. For other architectures see Docker images.

This is the recommended way for Windows users.

- Download the [FlareSolverr executable](https://github.com/smeinecke/FlareSolverr/releases) from the release's page. It is available for Windows x64 and Linux x64.
- Execute FlareSolverr binary. In the environment variables section you can find how to change the configuration.

### From source code

> **Warning**
> Installing from source code only works for x64 architecture. For other architectures see Docker images.

- Install [Python 3.13](https://www.python.org/downloads/).
- Install [Chrome](https://www.google.com/intl/en_us/chrome/) (all OS) or [Chromium](https://www.chromium.org/getting-involved/download-chromium/) (just Linux, it doesn't work in Windows) web browser.
- (Only in Linux) Install [Xvfb](https://en.wikipedia.org/wiki/Xvfb) package.
- (Only in macOS) Install [XQuartz](https://www.xquartz.org/) package.
- Install [uv](https://github.com/astral-sh/uv) (a fast Python package installer).
- Clone this repository and open a shell in that path.
- Run `uv sync` command to install FlareSolverr dependencies.
- Run `uv run python src/flaresolverr.py` command to start FlareSolverr.

### From source code (FreeBSD/TrueNAS CORE)

- Run `pkg install chromium python313 py313-pip xorg-vfbserver` command to install the required dependencies.
- Install [uv](https://github.com/astral-sh/uv) (a fast Python package installer).
- Clone this repository and open a shell in that path.
- Run `uv sync` command to install FlareSolverr dependencies.
- Run `uv run python src/flaresolverr.py` command to start FlareSolverr.

### Systemd service

We provide an example Systemd unit file `flaresolverr.service` as reference. You have to modify the file to suit your needs: paths, user and environment variables.

## Usage

Example Bash request:

```bash
curl -L -X POST 'http://localhost:8191/v1' \
-H 'Content-Type: application/json' \
--data-raw '{
  "cmd": "request.get",
  "url": "http://www.google.com/",
  "maxTimeout": 60000
}'
```

Example Python request:

```py
import requests

url = "http://localhost:8191/v1"
headers = {"Content-Type": "application/json"}
data = {
    "cmd": "request.get",
    "url": "http://www.google.com/",
    "maxTimeout": 60000
}
response = requests.post(url, headers=headers, json=data)
print(response.text)
```

Example PowerShell request:

```ps1
$body = @{
    cmd = "request.get"
    url = "http://www.google.com/"
    maxTimeout = 60000
} | ConvertTo-Json

irm -UseBasicParsing 'http://localhost:8191/v1' -Headers @{"Content-Type"="application/json"} -Method Post -Body $body
```

### Commands

#### + `sessions.create`

This will launch a new browser instance which will retain cookies until you destroy it with `sessions.destroy`.
This comes in handy, so you don't have to keep solving challenges over and over and you won't need to keep sending
cookies for the browser to use.

This also speeds up the requests since it won't have to launch a new browser instance for every request.

| Parameter | Notes                                                                                                                                                                                                                                                                                                             |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| session   | Optional. The session ID that you want to be assigned to the instance. If isn't set a random UUID will be assigned.                                                                                                                                                                                               |
| proxy     | Optional, default disabled. Eg: `"proxy": {"url": "http://127.0.0.1:8888"}`. You must include the proxy schema in the URL: `http://`, `socks4://` or `socks5://`. Authorization (username/password) is supported. Eg: `"proxy": {"url": "http://127.0.0.1:8888", "username": "testuser", "password": "testpass"}` |
| stealth   | Optional, default uses `STEALTH_MODE`. Enables/disables stealth patches for this session. If a session already exists, this value must match the session's existing stealth mode. |
| stealthMode | Optional enum override: `"off"`, `"standard"`, `"csp-safe"`. Preferred over `stealth` for explicit behavior. |
| userAgent | Optional. Custom browser user agent for the session. If a session already exists, this must match the existing configured value. |
| acceptLanguage | Optional. Overrides the global `ACCEPT_LANGUAGE` for this session. Example: `"acceptLanguage": "de-DE,de"`. Once set on a session it cannot be changed without destroying and recreating the session. |
| enabledServices | Optional. List of challenge services to enable for this session. Default: `["cloudflare", "ddos_guard"]`. Controls which challenge types are detected and resolved. |
| sessionMaxRuntime | Optional. Per-session maximum lifetime in seconds. Overrides the global `SESSION_MAX_RUNTIME` env var. Session is destroyed when lifetime exceeds this value. |
| sessionIdleTimeout | Optional. Per-session idle timeout in seconds. Overrides the global `SESSION_IDLE_TIMEOUT` env var. Session is destroyed when idle longer than this value. |

#### + `sessions.list`

Returns a list of all the active sessions. More for debugging if you are curious to see how many sessions are running.
You should always make sure to properly close each session when you are done using them as too many may slow your
computer down.

Example response:

```json
{
  "sessions": ["session_id_1", "session_id_2", "session_id_3..."]
}
```

#### + `sessions.destroy`

This will properly shutdown a browser instance and remove all files associated with it to free up resources for a new
session. When you no longer need to use a session you should make sure to close it.

| Parameter | Notes                                         |
| --------- | --------------------------------------------- |
| session   | The session ID that you want to be destroyed. |

#### + `sessions.get`

Retrieves the current state of a session without re-navigating. Returns the current URL, page title, full page source,
cookies, and user agent.

| Parameter | Notes                               |
| --------- | ----------------------------------- |
| session   | The session ID to retrieve info for. |

#### + `sessions.eval`

Executes arbitrary JavaScript in the session's browser context. Useful for inspecting page state, reading custom JS
variables, or interacting with the DOM directly.

| Parameter | Notes                                              |
| --------- | -------------------------------------------------- |
| session   | The session ID to execute JS in.                   |
| script    | The JavaScript code to execute.                    |

#### + `sessions.network`

Retrieves Chrome DevTools Protocol performance logs from a session. Useful for debugging network traffic, request/response
headers, and cookie behavior. Requires the session to have been created with performance logging enabled (enabled by default
in sessions).

| Parameter | Notes                                                |
| --------- | ---------------------------------------------------- |
| session   | The session ID to retrieve network logs from.       |

#### + `sessions.click`

Clicks an element in the session's browser using an XPath selector. Useful for interacting with pages (e.g. clicking a
"Verify" or "Try again" button) without triggering a full page navigation.

| Parameter | Notes                                                |
| --------- | ---------------------------------------------------- |
| session   | The session ID to click in.                         |
| selector  | XPath selector for the element to click.              |

#### + `sessions.action`

Executes a list of browser actions in a session without re-navigating. Uses the same action format as `request.get`/`request.post`.

| Parameter | Notes                                                |
| --------- | ---------------------------------------------------- |
| session   | The session ID to execute actions in.                |
| actions   | List of action objects. Supported types: `fill`, `click`, `wait_for`, `wait`, `eval`. |

Example:
```json
{
  "cmd": "sessions.action",
  "session": "my-session",
  "actions": [
    {"type": "wait", "seconds": 2},
    {"type": "click", "selector": "//button[contains(.,'Verify')]"},
    {"type": "wait_for", "selector": "//div[@id='results']"}
  ]
}
```

#### + `sessions.screenshot`

Captures a screenshot of the current session page and returns it as a Base64-encoded PNG.

| Parameter | Notes                                                |
| --------- | ---------------------------------------------------- |
| session   | The session ID to capture.                           |

#### + `sessions.cdp`

Executes a Chrome DevTools Protocol (CDP) command directly on the session's browser instance.
Useful for advanced debugging, injecting scripts before page load, or accessing low-level browser features.

| Parameter  | Notes                                                |
| ---------- | ---------------------------------------------------- |
| session    | The session ID to target.                            |
| cdp_cmd    | The CDP command name, e.g. `Page.addScriptToEvaluateOnNewDocument`. |
| cdp_params | Optional. Dictionary of parameters for the CDP command. |

Example:
```json
{
  "cmd": "sessions.cdp",
  "session": "my-session",
  "cdp_cmd": "Page.addScriptToEvaluateOnNewDocument",
  "cdp_params": {
    "source": "console.log('injected')"
  }
}
```

#### + `request.get`

| Parameter           | Notes                                                                                                                                                                                                                                                                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| url                 | Mandatory                                                                                                                                                                                                                                                                                                                                    |
| session             | Optional. Will send the request from an existing browser instance. If one is not sent it will create a temporary instance that will be destroyed immediately after the request is completed. Can also be passed as the `X-FlareSolverr-Session` HTTP header (body value takes precedence). |
| session_ttl_minutes | Optional. FlareSolverr will automatically rotate expired sessions based on the TTL provided in minutes.                                                                                                                                                                                                                                      |
| sessionMaxRuntime   | Optional. Per-session maximum lifetime in seconds. Overrides the global `SESSION_MAX_RUNTIME` env var for this request's session. Session is destroyed when lifetime exceeds this value. |
| sessionIdleTimeout  | Optional. Per-session idle timeout in seconds. Overrides the global `SESSION_IDLE_TIMEOUT` env var for this request's session. Session is destroyed when idle longer than this value. |
| maxTimeout          | Optional, default value 60000. Max timeout to solve the challenge in milliseconds.                                                                                                                                                                                                                                                           |
| cookies             | Optional. Will be used by the headless browser. Eg: `"cookies": [{"name": "cookie1", "value": "value1"}, {"name": "cookie2", "value": "value2"}]`.                                                                                                                                                                                           |
| headers             | Optional. Custom HTTP headers to send with the request. Useful for sites requiring specific referrers or custom headers. Supports dict format: `"headers": [{"name": "Referer", "value": "https://example.com"}]` or string format: `"headers": ["Referer: https://example.com"]`.                                                          |
| returnOnlyCookies   | Optional, default false. Only returns the cookies. Response data, headers and other parts of the response are removed.                                                                                                                                                                                                                       |
| returnScreenshot    | Optional, default false. Captures a screenshot of the final rendered page after all challenges and waits are completed. The screenshot is returned as a Base64-encoded PNG string in the `screenshot` field of the response.                                                                                                                 |
| proxy               | Optional, default disabled. Eg: `"proxy": {"url": "http://127.0.0.1:8888"}`. You must include the proxy schema in the URL: `http://`, `socks4://` or `socks5://`. Authorization (username/password) is supported when `username` and `password` are provided. Eg: `"proxy": {"url": "http://127.0.0.1:8888", "username": "testuser", "password": "testpass"}`. (When the `session` parameter is set, the proxy is ignored; a session specific proxy can be set in `sessions.create`.) |
| waitInSeconds       | Optional, default none. Length to wait in seconds after solving the challenge, and before returning the results. Useful to allow it to load dynamic content.                                                                                                                                                                                 |
| disableMedia        | Optional, default false. When true FlareSolverr will prevent media resources (images, CSS, and fonts) from being loaded to speed up navigation.                                                                                                                                                                                              |
| tabs_till_verify    | Optional, default none. Number of times the `Tab` button is needed to be pressed to end up on the turnstile captcha, in order to verify it. After verifying the captcha, the result will be stored in the solution under `turnstile_token`.                                                                                                  |
| actions             | Optional, default none. List of browser actions to perform after the page loads and any challenge is resolved, but before capturing the response. See [Browser Actions](#browser-actions) below.                                                                                                                                             |
| captchaSolver       | Optional, default uses the global `CAPTCHA_SOLVER` environment variable (fallback: `"default"`). Overrides the solver used for this specific request. Currently only `"default"` is supported. Custom solvers can be registered via the `SolverManager` API. An unknown solver name returns an error immediately. |
| stealth             | Optional, default uses `STEALTH_MODE`. Enables/disables stealth patches for this request. With `session`, this must match the session's configured stealth mode. |
| stealthMode         | Optional enum override: `"off"`, `"standard"`, `"csp-safe"`. Preferred over `stealth` for explicit behavior. |
| userAgent           | Optional. Custom browser user agent override. For `session` requests, this can only be set on session initialization and must stay consistent afterwards. |
| acceptLanguage      | Optional. Overrides the browser `Accept-Language` header for this request (or session initialization). Uses the global `ACCEPT_LANGUAGE` env var when omitted. Example: `"acceptLanguage": "fr-FR,fr"`. |
| enabledServices     | Optional. Overrides the session's challenge services for this request. Controls which challenge types are detected and resolved. Example: `"enabledServices": ["cloudflare", "brave"]`. |

> **Warning**
> If you want to use Cloudflare clearance cookie in your scripts, make sure you use the FlareSolverr User-Agent too. If they don't match you will see the challenge.

Example response from running the `curl` above:

```json
{
  "solution": {
    "url": "https://www.google.com/?gws_rd=ssl",
    "status": 200,
    "headers": {
      "status": "200",
      "date": "Thu, 16 Jul 2020 04:15:49 GMT",
      "expires": "-1",
      "cache-control": "private, max-age=0",
      "content-type": "text/html; charset=UTF-8",
      "strict-transport-security": "max-age=31536000",
      "p3p": "CP=\"This is not a P3P policy! See g.co/p3phelp for more info.\"",
      "content-encoding": "br",
      "server": "gws",
      "content-length": "61587",
      "x-xss-protection": "0",
      "x-frame-options": "SAMEORIGIN",
      "set-cookie": "1P_JAR=2020-07-16-04; expires=Sat..."
    },
    "response": "<!DOCTYPE html>...",
    "cookies": [
      {
        "name": "NID",
        "value": "204=QE3Ocq15XalczqjuDy52HeseG3zAZuJzID3R57...",
        "domain": ".google.com",
        "path": "/",
        "expires": 1610684149.307722,
        "size": 178,
        "httpOnly": true,
        "secure": true,
        "session": false,
        "sameSite": "None"
      },
      {
        "name": "1P_JAR",
        "value": "2020-07-16-04",
        "domain": ".google.com",
        "path": "/",
        "expires": 1597464949.307626,
        "size": 19,
        "httpOnly": false,
        "secure": true,
        "session": false,
        "sameSite": "None"
      }
    ],
    "userAgent": "Windows NT 10.0; Win64; x64) AppleWebKit/5...",
    "turnstile_token": "03AGdBq24k3lK7JH2v8uN1T5F..."
  },
  "status": "ok",
  "message": "",
  "startTimestamp": 1594872947467,
  "endTimestamp": 1594872949617,
  "version": "1.0.0"
}
```

### Browser Actions

The `actions` parameter accepts a list of action objects executed sequentially in the live browser after the page has loaded. This enables form filling, button clicks, and waiting for dynamic content — useful for pages where bot detection only runs after user interaction.

All `selector` values must be **XPath** expressions.

| Action type | Parameters | Description |
| ----------- | ---------- | ----------- |
| `fill` | `selector` (XPath), `value` (string) | Scrolls to the element, clicks to focus, then types the value character-by-character with randomised inter-key delays to mimic human typing speed. |
| `click` | `selector` (XPath), `humanLike` (bool, default `false`) | Scrolls the element into view and clicks. When `humanLike` is `true`, uses bezier-curve mouse movement for a more natural trajectory; the default uses `move_to_element` which is more robust for elements near viewport edges. |
| `wait_for` | `selector` (XPath), `timeout` (ms, optional, default `15000`) | Blocks until the matched element becomes visible. Default timeout is 15 seconds; override with e.g. `"timeout": 30000` for 30s. |
| `wait` | `seconds` (number) | Sleeps for the given number of seconds. Useful to allow interaction trackers to warm up before the first input. |
| `eval` | `script` (string) | Executes JavaScript in the page and captures the return value. The result is returned in `solution.evalResult` (single value) or as a list if multiple `eval` actions are used. |

Example — fill and submit a login form, then wait for the result element to appear:

```json
{
  "cmd": "request.get",
  "url": "https://example.com/login",
  "actions": [
    { "type": "wait",     "seconds": 2 },
    { "type": "fill",     "selector": "//input[@id='email']",    "value": "user@example.com" },
    { "type": "fill",     "selector": "//input[@id='password']", "value": "s3cr3t!" },
    { "type": "click",    "selector": "//button[@type='submit']" },
    { "type": "wait_for", "selector": "//div[@id='dashboard']" }
  ]
}
```

Example — execute JavaScript to read localStorage after solving a challenge:

```json
{
  "cmd": "request.get",
  "url": "https://example.com/protected",
  "actions": [
    { "type": "eval", "script": "return localStorage.getItem('key')" }
  ]
}
```

> **Note:** `fill` types one character at a time with random delays (60–180 ms per keystroke). This is intentional — bot-detection interaction trackers flag instant value injection as superhuman behaviour.

### + `request.post`

This works like `request.get`, with the addition of the postData parameter. Note that `tabs_till_verify` is currently supported only for GET requests and requires one extra argument.

| Parameter | Notes                                                                    |
| --------- | ------------------------------------------------------------------------ |
| postData  | Must be a string with `application/x-www-form-urlencoded`. Eg: `a=b&c=d` |
| headers   | Optional. Same format as `request.get`. Custom HTTP headers to send.    |

## Request Flow

The following diagram illustrates how FlareSolverr processes requests:

```mermaid
flowchart TD
    A[API Client] -->|POST /v1| B[FlareSolverr API]
    B --> C{Session?}
    C -->|New session| D[Launch Chrome]
    C -->|Existing| E[Reuse browser]
    D --> F[Navigate to URL]
    E --> F
    F --> G{Challenge detected?}
    G -->|No| H[Wait for page load]
    G -->|Yes| I[Default Solver]
    I --> J[Check page title<br/>for challenge markers]
    J --> K[Check CSS selectors<br/>e.g., #cf-challenge-running]
    K --> L{Challenge found?}
    L -->|No| H
    L -->|Yes| M[Wait for challenge<br/>elements to disappear]
    M --> N[Click verify checkbox<br/>if needed]
    N --> O[Wait for page redirect]
    O --> P{Solve successful?}
    P -->|No| Q[Return error response]
    P -->|Yes| H
    H --> AA{actions?}
    AA -->|Yes| AB[Execute browser actions<br/>fill / click / wait_for / wait]
    AA -->|No| R{waitInSeconds?}
    AB --> R{waitInSeconds?}
    R -->|Yes| S[Wait specified time]
    R -->|No| T[returnScreenshot?]
    S --> T
    T -->|Yes| U[Capture screenshot]
    T -->|No| V[Build response]
    U --> V
    V --> W[Return cookies, HTML,<br/>headers, userAgent]
    W --> X[Send JSON response]
    X --> A
    Q --> X
```

The **default solver** handles Cloudflare challenges through browser automation:

- Detects challenges by checking page titles ("Just a moment...") and CSS selectors
- Waits for challenge elements to disappear from the DOM
- Automatically clicks the verify checkbox when presented
- Waits for page redirect after successful verification

## Environment variables

| Name               | Default                | Notes                                                                                                                                    |
| ------------------ | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| LOG_LEVEL          | info                   | Verbosity of the logging. Use `LOG_LEVEL=debug` for more information.                                                                    |
| LOG_FILE           | none                   | Path to capture log to file. Example: `/config/flaresolverr.log`.                                                                         |
| LOG_HTML           | false                  | Only for debugging. If `true` all HTML that passes through the proxy will be logged to the console in `debug` level.                     |
| PROXY_URL          | none                   | URL for proxy. Will be overwritten by `request` or `sessions` proxy, if used. Example: `http://127.0.0.1:8080`.                          |
| PROXY_USERNAME     | none                   | Username for proxy. Will be overwritten by `request` or `sessions` proxy, if used. Example: `testuser`.                                  |
| PROXY_PASSWORD     | none                   | Password for proxy. Will be overwritten by `request` or `sessions` proxy, if used. Example: `testpass`.                                  |
| CAPTCHA_SOLVER     | default                | Captcha solving method. It is used when a captcha is encountered. See the Captcha Solvers section.                                       |
| TZ                 | UTC                    | Timezone used in the logs and the web browser. Example: `TZ=Europe/London`.                                                              |
| LANG               | none                   | Language used in the web browser. Example: `LANG=en_GB`.                                                                                 |
| ACCEPT_LANGUAGE    | en-US,en               | Default `Accept-Language` header sent by the browser. Can be overridden per-request or per-session via the `acceptLanguage` parameter. Example: `ACCEPT_LANGUAGE=de-DE,de`. |
| HEADLESS           | true                   | Only for debugging. To run the web browser in headless mode or visible.                                                                  |
| DISABLE_MEDIA      | false                  | To disable loading images, CSS, and other media in the web browser to save network bandwidth.                                            |
| DISABLE_QUIC       | true                   | Disables QUIC/HTTP3 in Chrome (`--disable-quic --disable-http3`) to avoid challenge transport instability on some networks/environments. |
| MINIMAL_FINGERPRINT | true                  | If `true`, avoids extra anti-detection Chrome flags (`--disable-blink-features=AutomationControlled` and site-isolation-disabling flags) to keep browser behavior closer to stock Chrome. |
| STEALTH_MODE       | off                    | Global stealth mode. Supported values: `off`, `standard`, `csp-safe` (also accepts legacy `true/false`). `standard` does **not** enable blob-worker bypass by default. Custom C++-patched Chromium hardening is only available on **amd64**; other architectures use CDP-based JS patches only. |
| UC_HEADLESS_AUTO_UA_OVERRIDE | false      | Controls undetected_chromedriver automatic headless UA override. Default `false` means no automatic UA replacement. |
| PORT               | 8191                   | Listening port. You don't need to change this if you are running on Docker.                                                              |
| HOST               | 0.0.0.0                | Listening interface. You don't need to change this if you are running on Docker.                                                         |
| PROMETHEUS_ENABLED | false                  | Enable Prometheus exporter. See the Prometheus section below.                                                                            |
| PROMETHEUS_PORT    | 8192                   | Listening port for Prometheus exporter. See the Prometheus section below.                                                                |
| SESSION_MAX_RUNTIME | none                  | Maximum lifetime of a session in seconds. When set, sessions older than this are automatically destroyed. Overrides per-session `sessionMaxRuntime`. |
| SESSION_IDLE_TIMEOUT | 900                 | Maximum idle time of a session in seconds (default: 15 minutes). Sessions idle longer than this are automatically destroyed. Overrides per-session `sessionIdleTimeout`. Always active. |
| SESSION_MAX_COUNT    | none                  | Maximum number of concurrent sessions. When exceeded, oldest idle sessions are destroyed first. |
| MAX_PARALLEL_REQUESTS | none                  | Maximum number of parallel requests processed at the same time. When exceeded, new requests receive HTTP 429 so clients can retry later. |
| XVFB_WIDTH         | 1920                   | Width of the Xvfb virtual display in pixels. Only used in headless mode on Linux.                                                       |
| XVFB_HEIGHT        | 1080                   | Height of the Xvfb virtual display in pixels. Only used in headless mode on Linux.                                                       |
| XVFB_COLORDEPTH    | 24                     | Color depth (bits per pixel) of the Xvfb virtual display. Common values: 8, 16, 24, 32. Only used in headless mode on Linux.          |

Environment variables are set differently depending on the operating system. Some examples:

- Docker: Take a look at the Docker section in this document. Environment variables can be set in the `docker-compose.yml` file or in the Docker CLI command.
- Linux: Run `export LOG_LEVEL=debug` and then run `flaresolverr` in the same shell.
- Windows: Open `cmd.exe`, run `set LOG_LEVEL=debug` and then run `flaresolverr.exe` in the same shell.

## Prometheus exporter

The Prometheus exporter for FlareSolverr is disabled by default. It can be enabled with the environment variable `PROMETHEUS_ENABLED`. If you are using Docker make sure you expose the `PROMETHEUS_PORT`.

Example metrics:

```shell
# HELP flaresolverr_request_total Total requests with result
# TYPE flaresolverr_request_total counter
flaresolverr_request_total{domain="nowsecure.nl",result="solved"} 1.0
# HELP flaresolverr_request_created Total requests with result
# TYPE flaresolverr_request_created gauge
flaresolverr_request_created{domain="nowsecure.nl",result="solved"} 1.690141657157109e+09
# HELP flaresolverr_request_duration Request duration in seconds
# TYPE flaresolverr_request_duration histogram
flaresolverr_request_duration_bucket{domain="nowsecure.nl",le="0.0"} 0.0
flaresolverr_request_duration_bucket{domain="nowsecure.nl",le="10.0"} 1.0
flaresolverr_request_duration_bucket{domain="nowsecure.nl",le="25.0"} 1.0
flaresolverr_request_duration_bucket{domain="nowsecure.nl",le="50.0"} 1.0
flaresolverr_request_duration_bucket{domain="nowsecure.nl",le="+Inf"} 1.0
flaresolverr_request_duration_count{domain="nowsecure.nl"} 1.0
flaresolverr_request_duration_sum{domain="nowsecure.nl"} 5.858
# HELP flaresolverr_request_duration_created Request duration in seconds
# TYPE flaresolverr_request_duration_created gauge
flaresolverr_request_duration_created{domain="nowsecure.nl"} 1.6901416571570296e+09
```

## Captcha Solvers

FlareSolverr includes a pluggable captcha solver interface. The built-in `default` solver handles Cloudflare challenges automatically.

The `CAPTCHA_SOLVER` environment variable selects the active solver (default: `"default"`). Custom solvers can be added by subclassing `CaptchaSolver` and registering them with `SOLVER_MANAGER.register_solver()`.

For details on the solver API, see [CAPTCHA_SOLVERS.md](./CAPTCHA_SOLVERS.md).

## Python Client Library

FlareSolverr includes a Python client library for easy integration. It is installed automatically with the package.

```python
from flaresolverr.client import FlareSolverrClient, ActionQueue

client = FlareSolverrClient("http://localhost:8191")

# Simple GET request
response = client.request.get("https://example.com")
print(response.solution.response)

# With browser actions (form filling, clicking, etc.)
actions = (
    ActionQueue()
    .fill("//input[@id='email']", "user@example.com")
    .fill("//input[@id='password']", "secret")
    .click("//button[@type='submit']")
    .build()
)
response = client.request.get("https://example.com/login", actions=actions)
```

For detailed documentation, see [src/flaresolverr/client/README.md](./src/flaresolverr/client/README.md).

## Clustering with HAProxy

FlareSolverr sessions are stored in local memory, so when running multiple instances behind a load balancer you must ensure session affinity (sticky sessions). FlareSolverr accepts the session ID via the `X-FlareSolverr-Session` HTTP header in addition to the JSON body. This allows HAProxy (or any reverse proxy) to inspect incoming traffic and route requests to the correct backend without parsing the request body.

Quick example with HAProxy:

```haproxy
backend flaresolverr_backend
    balance hdr(X-FlareSolverr-Session)
    hash-type consistent
    option httpchk GET /health
    server fs1 10.0.0.11:8191 check
    server fs2 10.0.0.12:8191 check
    server fs3 10.0.0.13:8191 check
```

For a full configuration including Docker Compose, client integration notes, and operational considerations, see [HAPROXY.md](./HAPROXY.md).

## Related projects

- C# implementation => <https://github.com/FlareSolverr/FlareSolverrSharp>

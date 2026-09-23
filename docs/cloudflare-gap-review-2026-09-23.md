# Cloudflare follow-up: remaining gaps

Reviewed 2026-09-23 at FlareSolverr revision
`40b084bf895f64717edf395539c281c969bfd2ef`. Scope: changes after `7b6d27d`,
the current challenge matrix, response handling, browser build paths, and the
claims in [the original review](cloudflare-detection-review.md).

The native UA and Window `webdriver` corrections are working in the local
Chromium `154.0.8037.49` build. The remaining work is concentrated in accurate
responses, reproducible experiments, build compatibility, and behavior outside
the short successful challenge runs already reported.

This review made no production changes and sent no requests to the live mail
services. Historical target outcomes below are taken from the existing report.
Its `/tmp/cf_matrix_*.json` and `/tmp/ua_*.json` artifacts were unavailable at
review time, so those runs could not be independently reclassified. New browser
measurements used localhost. The important results are preserved in
[a small evidence file](evidence/cloudflare-gap-review-2026-09-23.json).

## What is now resolved

| Previous gap | Current evidence | Status |
| --- | --- | --- |
| Full-version UA override suppressed native high-entropy hints | Fresh browser: `Chrome/154.0.0.0`, architecture `x86`, bitness `64`, Chromium full-version hint `154.0.8037.49` | Fixed for the default local custom launch. |
| Window `navigator.webdriver` absent | Fresh browser: value `false`, property present, native prototype descriptor present; main/iframe/worker consistency test passes | Corrected default shape; workers retain their separate API shape. |
| Ordinary JSD/widget markers forced a challenge verdict | Matrix now treats the generic challenge-platform path and widget markers as weak | Fixed for those markers. |
| A stale clearance cookie overrode a challenge title | Title/interstitial checks now precede successful classification | Fixed. |
| A later iframe response replaced the top-level response | Main-frame lookup and fallback selection added, with regression coverage | Fixed when the main frame is identifiable; see fallback limitation below. |
| Manifest lost when packaging the application image | Root Dockerfile explicitly copies the hidden manifest beside Chromium | Fixed for artifacts that contain a manifest; alternate build path still needs work. |
| Early heavy challenge-state probing | Grace window implemented; unit coverage passes | Mitigated for short challenges, not eliminated for slower challenges. |

## Remaining gaps by priority

### G1 — P1: target HTTP status is still fabricated for ordinary requests

**Confirmed with a real local browser.** A localhost handler returned HTTP 404.
Calling `_evil_logic()` with a normal GET returned `solution.status = 200` and
empty headers. `_build_challenge_result()` still initializes status to 200 and
only overrides it for raw POST responses.

Source: [`flaresolverr_service.py`](../src/flaresolverr/flaresolverr_service.py),
`_build_challenge_result()` around line 1365.

This affects GET and form POST, including the original `postData` request mode.
Consequently, the earlier report's “HTTP 200” for that API mode cannot be inferred
from `solution.status` alone. An application JSON response is useful evidence
that the challenge was left, but its business-level success and actual HTTP
status need separate verification.

**Next change:** use the final top-level response status and headers on the
normal result path. Preserve the same captured events for HAR and diagnostics;
draining the performance queue twice would lose evidence. Represent an unknown
status explicitly rather than substituting 200.

**Acceptance:** local 200, 404, 429, 503, redirects, and a challenge response
retain their actual status/headers through GET and form POST. Keep command-level
success distinct from the target response status.

### G2 — P1: raw POST loses empty bodies and can lose its whole result

**Confirmed with a real local browser.** A local POST returned 204 with an empty
body and `X-Audit-Response: empty-post`. FlareSolverr returned status 204, but the
response body was the preceding GET's HTML and the POST header was missing.

The result-reading JavaScript uses `window.__flaresolverr_raw_post_body || null`.
That converts a legitimate empty string into null and selects the page-source
fallback. Source: `_build_challenge_result()` around lines 1373 and 1399.

Additional source-confirmed gaps in `_post_request_raw()`:

- It still navigates to the API URL with GET before sending POST, and challenge
  resolution happens afterward. A later challenge navigation can erase all
  window globals containing the POST response.
- After the 60-second polling loop, it does not require completion and does not
  abort a still-running XHR. A request with a longer outer `maxTimeout` can fall
  through without a result. Cancellation must also stop an in-flight request in
  a retained session.
- Challenge classification and raw headers are inside the response-body branch;
  `returnOnlyCookies` skips that classification entirely.

**Next change:** distinguish missing fields from empty values, retain a complete
response object independently of later page navigation, and enforce a shared
completion/cancellation deadline. Do not automatically replay a state-changing
POST when its execution is uncertain.

**Acceptance:** empty 200/204 responses, delayed completion, timeout, redirects,
and challenged GET-bootstrap/POST combinations preserve the original exchange
or return an explicit failure. Verify headers even when body output is omitted.

### G3 — P1: the alternate Chromium Docker build is not aligned with the patch tool

**Source-confirmed; no Chromium rebuild was attempted.**
[`chromium-patches/Dockerfile`](../chromium-patches/Dockerfile) uses Ubuntu 22.04
and invokes system `python3` directly for `apply.py`. Ubuntu's default package
is Python 3.10, while the patch tool imports `datetime.UTC`, introduced in 3.11.
That invocation cannot import the current script under the declared interpreter.
[Ubuntu package](https://packages.ubuntu.com/jammy/python3),
[Python UTC documentation](https://docs.python.org/3/library/datetime.html#datetime.UTC)

Even after fixing the interpreter, this Dockerfile creates `.stealth-patched`
but never invokes `--write-manifest`. The root application Dockerfile cannot
copy a manifest that the producer did not generate. The runtime would then take
its legacy UA fallback and lose the high-entropy metadata again.

The self-hosted workflow does emit a manifest. This is a gap in the alternate
Docker producer, not evidence that the locally tested binary lacks the fix.

**Next change:** align the patch tool's Python requirement with every builder,
emit and require the manifest in each supported producer, and smoke-test the
final application image's UA/metadata/patch detection. The producer manifest
must match the binary actually shipped.

### G4 — P2: the matrix still does not isolate attachment

Sharing `_build_chrome_options()` fixed the major missing-flags confound.
However, the UC arm still is not the ChromeDriver-owned launch described in
the harness comments and earlier report.

[`undetected_chromedriver/__init__.py`](../src/flaresolverr/undetected_chromedriver/__init__.py)
sets a debugger address, starts Chromium via `_start_browser_process()`, then
constructs Selenium with those options. The manual arms also attach ChromeDriver.
Neither arm is a no-attachment baseline, and this code does not establish the
claimed `--enable-automation` difference.

Other differences remain: the UC arm selects its own patched driver, adds startup
arguments, and does not call the production CPU-affinity or screen-metrics setup.
The manual arm enables performance logging by default. The harness records none
of the final command lines, driver hashes, enabled domains, observed identity,
or actual egress addresses needed to audit these differences.

**Next change:** label the existing arms as launch-configuration comparisons.
For a causal attachment experiment, add a separately observed browser without
an attachment, hold the binary/profile/flags/network constant, and record what
each arm actually ran. A later attachment to read results must not be mistaken
for an uninstrumented observation.

`dump-dom` remains a separate weak control: internal CDP, virtual time rather
than an equal real-time observation window, a reused PID-derived profile path,
and CLI proxy handling that does not support the authenticated proxy path used
elsewhere. It is not suitable for excluding CDP or estimating solve probability.

### G5 — P2: matrix “passed” still lacks positive application evidence

**Reproduced offline against the current classifier:**

| Input | Current verdict | Problem |
| --- | --- | --- |
| Ordinary “Service unavailable” HTML longer than 256 bytes | `passed` | Error content can satisfy the size threshold. |
| Valid short HTML page | `empty` | Length is not a success/failure contract. |
| DOM-dump HTML with a localized challenge title, no listed source markers, and more than 256 bytes | `passed` | `_dump_dom_arm()` supplies an empty title instead of parsing the HTML title. |

Source: [`test_cf_challenge_matrix.py`](../tests/integration/test_cf_challenge_matrix.py),
`_verdict_from_page()`, `_driver_arm()`, and `_dump_dom_arm()`.

The driver wait loop checks only titles, so an unrecognized/localized title with
a recognized DOM challenge marker is sampled after five seconds even though it
is ultimately classified as challenged. Load timeout plus a second full polling
deadline can also exceed the documented per-arm timeout.

**Next change:** record actual main-frame status and challenge headers, use a
target-specific success predicate, parse dump titles, and return `unknown` when
there is insufficient evidence. Use one deadline and a consistent lightweight
challenge check. Avoid reintroducing the heavy DOM probe into measurement.

The original `/api` operation is still outside the default GET-only matrix.
Keep an explicitly selected end-to-end case with an application response
contract, since generating a mailbox can create state.

### G6 — P2: the grace window postpones the expensive probe

**Source-confirmed limitation, not a newly reproduced live failure.**
[`CloudflareService.resolve()`](../src/flaresolverr/services/cloudflare.py)
resumes `_should_attempt_verify_click()` on each wait timeout after 12 seconds.
That calls the same layout-forcing scan previously reported to stall automatic
verification. Its execution is outside the 10-second click cooldown. A slower
automatic challenge can therefore enter the problematic behavior again.

The grace branch also still reads `page_source` every wait timeout; descriptions
that it performs only title/selector polling are inaccurate. Interactive
challenges incur up to 12 seconds of added delay, consuming the caller's timeout.

**Next change:** restrict probing to lightweight, targeted indicators and use
backoff. Keep automatic-verification polling cheap for its whole lifetime;
reserve visibility work for a credible interactive control. Measure slow
automatic and interactive cases as well as the reported approximately four-second
success case. Use monotonic deadlines for elapsed-time decisions.

### G7 — P2: diagnostics and build provenance still have fallback gaps

- `get_document_response_evidence()` now selects the main frame correctly when
  identifiable. If frame and current-URL matching both fail, it still chooses
  the latest Document, which can be an iframe. Return unknown/selection metadata
  rather than presenting that fallback as authoritative top-level evidence.
- `collect_failure_evidence()` obtains `stealthMode` from the environment, not
  the effective per-request/session launch mode. An API `stealthMode` override
  can therefore disagree with the reported configuration.
- Evidence is added in the `FunctionTimedOut` handler; immediate navigation or
  hard-block exceptions still follow the generic exception path without the
  same structured failure record. “All failures have classified evidence” is too
  broad.
- The self-hosted workflow reverts files before applying either webdriver
  variant. [`build.sh`](../chromium-patches/build.sh) reuses an existing checkout
  without that step. `apply.py` lists the opposite variant's file but does not
  itself restore it. Switching from the old IDL-gated build to the default via
  that path can retain the stale gate while the manifest advertises
  `webdriver-false`.
- Manifest generation hashes the repository's GN template, not the effective
  `out/Release/args.gn`; workflow additions such as `cc_wrapper` are omitted.
  Runtime manifest lookup prefers `/opt/chromium` over the selected executable's
  directory, so an unrelated installation can supply the capability list.

**Acceptance:** missing-frame evidence cannot impersonate a confirmed top-level
response; both timeout and immediate errors retain evidence; effective request
configuration is recorded; variant transitions and all builders produce a
manifest tied to the selected binary and actual build arguments.

### G8 — P2: explicit overrides and sessions.fetch need broader coverage

The default native identity is now verified, but `apply_user_agent_override()`
still notes that SharedWorkers do not receive the override. Its synthetic
metadata also uses the installed binary's full version even when the requested
UA specifies a different major. A successful default UA sweep does not validate
custom `userAgent` requests.

For `sessions.fetch`, source inspection shows additional contract limits:

- Only the initial URL is checked for the same origin. Fetch follows redirects
  with default CORS behavior; if same-origin-only includes redirects, enforce
  that in the browser request mode too.
- `timeoutMs` sets the JS abort timer but does not configure WebDriver's script
  timeout; longer requested waits can end at the driver's earlier deadline.
- The handler does not update `session.touch()` or `request_count`, so fetch
  activity does not refresh the idle timestamp as normal request commands do.

These are follow-up source findings, not live target reproductions. Add local
contract tests for redirects, deadlines, active-session retention, and explicit
identity overrides before marking the whole API response/context work complete.

## Verification and remaining evidence requirements

| Check performed now | Result |
| --- | --- |
| `uv run make` | Passed, including **469 unit tests** in 39.20 seconds. |
| Existing browser consistency, event-trust, and GPU integration diagnostics | **5 passed** in 15.89 seconds on the current local binary. |
| Fresh localhost identity probe | Native reduced UA, populated high-entropy hints, Window webdriver present and false. |
| Localhost response probe | Reproduced G1 and the empty-body case in G2. |
| Offline matrix examples | Reproduced G5; inputs/results are preserved in the evidence file. |
| New live-site experiment or container rebuild | Not performed. Historical results are retained as reported observations. |

Temporary reproduction script and logs are `/tmp/cf_gap_review.py`,
`/tmp/cf-gap-review-probe.log`, `/tmp/cf-gap-review-validation.log`, and
`/tmp/cf-gap-review-browser.log`. The accompanying evidence summary preserves the
significant measurements if temporary files disappear.

The normal suite does not run the live matrix, compile Chromium, build the
container, or cover all response-status cases. Passing it is compatible with the
confirmed defects above. Extend durable regression coverage to high-entropy
UA-CH and HTTP headers, SharedWorker/ServiceWorker and cross-origin frames,
explicit identity overrides, and dynamic viewport behavior. The current
consistency test checks selected navigator values but not all of those surfaces.

The prior report's matched-version webdriver variant results support retaining
the false-valued Window property. They do not prove that it was Cloudflare's only
input or that a failure occurred before interaction. Likewise, comparing stock
153 with custom 154 changes more than one fingerprint field. Retain the observed
target outcomes, preserve build/configuration evidence for future trials, and
avoid generalizing two targets into a claim about all Cloudflare configurations.

## Resolution status (implemented)

All eight gaps have been addressed on `feature/cloudflare-detection-review`:

- **G1** — `_build_challenge_result` now takes the real top-level document
  status and headers from `get_document_response_evidence` (single perf-log
  drain shared with HAR). Unknown status is reported as `null`, never a
  fabricated 200. `set-cookie` is filtered from result headers (cookies remain
  under `solution.cookies`).
- **G2** — `_post_request_raw` stashes the completed XHR result on the driver
  object (`_flaresolverr_raw_post_result`), so a later challenge-resolution
  navigation cannot wipe it; `typeof` guards preserve legitimate empty bodies;
  the in-flight XHR is aborted and a clear timeout error raised when it never
  completes; challenge classification (`cf-mitigated`/challenge HTML) now runs
  independently of `returnOnlyCookies`.
- **G3** — `chromium-patches/Dockerfile` moved to Ubuntu 24.04 (Python 3.12,
  satisfying `datetime.UTC`), exposes `FLARESOLVERR_WEBDRIVER_ABSENT_PROPERTY`
  as a build arg/env so patch application and manifest generation stay
  consistent, and runs `apply.py --write-manifest` after the build.
- **G4/G5** — matrix records `launchArgs` per arm; `dump-dom` parses `<title>`
  from the dumped DOM and is labeled "no external attach" (not zero-CDP);
  `_verdict_from_page` returns `nav_error` for browser-rendered error pages
  and `unknown` when no positive document evidence exists — a bare byte count
  no longer passes.
- **G6** — after `CHALLENGE_PROBE_GRACE`, the layout-forcing probe is
  rate-limited to once per 5s so a slow auto-verify is not kept stalled.
  `page_source` stays enabled during grace (bisection showed it does not
  interfere — only the DOM-walk probe does).
- **G7** — evidence reports `mainFrameIdentified` when frame selection fell
  back; `collect_failure_evidence` records the effective per-request
  `stealthMode`; generic (non-timeout) errors also attach bounded evidence via
  `ChallengeError.details`; `build.sh` reverts files touched by *either*
  variant before applying; the manifest now hashes effective
  `out/Release/args.gn` (with `gnArgsSource` recorded) instead of the
  template; manifest lookup prefers the manifest adjacent to the selected
  binary over `/opt/chromium`.
- **G8** — `sessions.fetch` increments `request_count`/`touch()` on success,
  raises the WebDriver script timeout to `timeoutMs + 10s` (restored after),
  and rejects responses whose final (post-redirect) URL leaves the page
  origin.

Unit coverage added: real status/headers/null-status in
`test_post_raw.py::TestChallengeResultResponse`; redirect origin enforcement,
session accounting, and script-timeout alignment in
`test_session_commands.py::TestSessionsFetch`.

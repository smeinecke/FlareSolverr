# Cloudflare detection review: custom Chromium

Reviewed 2026-09-21. FlareSolverr revision: `ad81349c583200a946ed0ab910df813cccb09386`.
Custom binary: Chromium `151.0.7922.112`. Local source:
`/media/stefan/data3/chromium/src`, revision
`6b03a2f2a6e84ae290fc0558db607cfd4ea2bb86`, with existing patches and dependency changes.
Installed Google Chrome reports `153.0.8010.52`; it is not a matched-version control.

## Assessment

**The strongest confirmed browser gap is our user-agent configuration.** The
`--user-agent` switch suppresses high-entropy UA client hints in this Chromium
version. Removing it restores those hints, but reveals `HeadlessChrome` because
Patch 6 changes the headless-shell implementation rather than the active unified
Chrome implementation. Both behaviors were reproduced locally and traced to the
matching Chromium source.

Fix that native UA path and remove the default UA switch as one change, then
measure Cloudflare again. This is a concrete identity correction, not a proven
solution to the reported Cloudflare loop. CDP attachment, graphics availability,
request context, and the target's policy still require controlled comparisons.

The current tests establish internal consistency for selected properties. They
do not establish that the browser resembles ordinary Chrome or that Cloudflare
accepts it. Cloudflare describes several detection engines using request,
session, and browser signals; a third-party detector's verdict cannot identify
the engine responsible for an individual rejection.
[Cloudflare detection engines](https://developers.cloudflare.com/bots/concepts/bot-detection-engines/)

## Reported failure and evidence boundaries

The user reproduced this locally:

```json
{
  "cmd": "request.post",
  "url": "https://tmailor.com/api",
  "postData": "action=newemail&curentToken=",
  "maxTimeout": 60000
}
```

| User-tested path | Reported result | Interpretation |
| --- | --- | --- |
| `postData`: form on a `data:` URL, top-level POST | Managed challenge loops; no clearance issued before 60-second timeout | This request context differs from the site's own API call. |
| `postDataRaw`: GET `/api`, then XHR | The initial GET is also challenged and the operation times out | The loop is not exclusive to POST bodies. |
| GET `/en/`, then in-page `fetch('/api', ...)` | `/en/` loads; fetch receives challenge HTML | Loading an unchallenged page does not establish clearance for `/api`. |
| GET `tempmailo.com` | Similar managed challenge loop without an interactive control | A second affected site supports investigating the common browser/environment. It does not identify a shared detection rule. |

These target results are **user-supplied observations**, not fresh live
reproductions by this review. Local experiments used a localhost HTTP origin;
no `newemail` operation was sent to the target. The exact active server
environment, target response headers/Ray IDs, challenge errors, and a successful
manual-browser comparison were not supplied.

The empty `curentToken` remains a separate application/request variable. A GET
challenge shows the endpoint is protected independently of that POST body, but
does not establish what happens with a valid application request. Preserve the
site's actual spelling and capture a successful browser request for comparison.

No visible checkbox does not establish that Cloudflare identified CDP: automatic
challenge failure, script/network errors, browser compatibility, or policy can
produce similar symptoms. Cloudflare documents several causes of challenge
loops, and treats automated production challenge solving as unsupported.
[Challenge troubleshooting](https://developers.cloudflare.com/cloudflare-challenges/troubleshooting/challenge-solve-issues/),
[Supported browsers](https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/)

## 1. Confirmed: UA override removes high-entropy client hints

[`_build_chrome_options()`](../src/flaresolverr/utils.py) always adds a handcrafted
full-version `--user-agent` for the custom binary, including when stealth mode is
off. `_maybe_normalize_user_agent()` then skips custom Chromium.

A fresh browser was launched for each variant, using the current custom binary,
`STEALTH_MODE=standard`, and the same localhost server. The server sent
`Accept-CH` for architecture, bitness, full-version list, and platform version.
JavaScript was queried on that trustworthy localhost origin; the server captured
the next request's headers.

| Measured property | Current launch | Remove only `--user-agent` | Keep switch, reduce version |
| --- | --- | --- | --- |
| Legacy UA product/version | `Chrome/151.0.7922.112` | `HeadlessChrome/151.0.0.0` | `Chrome/151.0.0.0` |
| `getHighEntropyValues().architecture` | `""` | `"x86"` | `""` |
| `bitness` | `""` | `"64"` | `""` |
| `uaFullVersion` | `""` | `"151.0.7922.112"` | `""` |
| `fullVersionList` | `[]` | Chromium full version and GREASE brand | `[]` |
| HTTP `sec-ch-ua-arch` after opt-in | `""` | `"x86"` | `""` |
| HTTP `sec-ch-ua-bitness` after opt-in | `""` | `"64"` | `""` |
| HTTP `sec-ch-ua-full-version-list` after opt-in | Empty | Populated | Empty |

Low-entropy brands, mobile, and platform remained populated in all variants.
Linux `platformVersion` was empty even without the switch; do not count that
field as an additional regression. Missing `Google Chrome` branding is expected
for an unbranded Chromium build and is not itself a contradiction.

The source explanation is explicit in
`components/embedder_support/user_agent_utils.cc`:

- `GetUserAgentMetadata()` populates low-entropy fields first.
- At lines 652–656, a valid command-line UA override returns before the
  high-entropy fields are populated.
- The architecture, bitness, full version, and full-version list are populated
  only after that return.

Changing `UACHOverrideBlank` alone does not restore the full metadata: the
override branch returns either blank metadata or low-entropy metadata.
[Matching Chromium source](https://chromium.googlesource.com/chromium/src/+/refs/tags/151.0.7922.112/components/embedder_support/user_agent_utils.cc#635)

**Proposed improvement:** let the custom browser produce its native reduced UA
and full metadata together. Avoid a default CLI UA override or a page-only CDP
metadata repair. User-requested custom UAs need an explicit, coherent design for
headers and all execution contexts; the existing `apply_user_agent_override()`
path should be included in that work.

Chromium normally reduces the legacy UA version to `major.0.0.0`. Our full-version
legacy UA is another departure from its defaults; the full version belongs in
the appropriate client hints. Reduction by itself does not fix the measured
metadata loss.
[Chromium UA reduction](https://www.chromium.org/updates/ua-reduction/)

## 2. Confirmed: Patch 6 misses unified Chrome's UA path

[`apply.py`, Patch 6](../chromium-patches/patches/apply.py) modifies
`headless/lib/browser/headless_browser_impl.cc`. That change is present in the
local source tree: `kHeadlessProductName` is `Chrome`.

However, the launched `chrome --headless=new` uses
`ChromeContentBrowserClient::GetUserAgent()`, which calls
`embedder_support::GetUserAgent()`. Its `GetUserAgentInternal()` still prepends
`Headless` when the headless switch is present. The relevant local source is
`components/embedder_support/user_agent_utils.cc:216`, unmodified in the working
tree. The no-UA-switch experiment exposed the token in both the main window and
DedicatedWorker, confirming that the old patch does not cover this path.
[Browser client source](https://chromium.googlesource.com/chromium/src/+/refs/tags/151.0.7922.112/chrome/browser/chrome_content_browser_client.cc#7776),
[UA generation source](https://chromium.googlesource.com/chromium/src/+/refs/tags/151.0.7922.112/components/embedder_support/user_agent_utils.cc#216)

**Proposed implementation scope:** update Patch 6 to cover the active native UA
generation path, then remove the default custom-build `--user-agent` argument.
Preserve normal UA reduction, platform generation, brand generation, and
high-entropy metadata. Apply changes through the repository's patch script so
they survive a rebuild; editing only the external checkout would be incomplete.

Acceptance must cover initial navigation headers, opted-in client hints, main
window, same-origin and cross-origin frames, DedicatedWorker, SharedWorker, and
ServiceWorker. A rebuild and target comparison are still required.

## 3. Confirmed CDP exposure; Cloudflare causation unproven

Manual Chromium startup avoids ChromeDriver's automatic launch arguments, but
[`get_webdriver()`](../src/flaresolverr/utils.py) subsequently attaches Selenium
ChromeDriver to its debugger port.

The matching local Chromium source confirms:

- `chrome/test/chromedriver/chrome/frame_tracker.cc:94` enables `Runtime` to
  receive execution-context events.
- `console_logger.cc:49` also enables `Runtime` when that logger is connected.
- Patch 12 replaces CDC alias setup with `(function () {})();`. The surrounding
  `Page.addScriptToEvaluateOnNewDocument` and `Runtime.evaluate` calls remain.

Thus, removing CDC globals does not eliminate debugger/runtime activity. The
historical `isAutomatedWithCDP` result from deviceandbrowserinfo is compatible
with this architecture, but is not a Cloudflare diagnostic.

**Next experiment:** compare the same binary, profile starting state, launch
configuration, target, and network with no debugger connection, with a debugger
port but no attachment, and with ChromeDriver attached. Use an otherwise
matching headed browser as the manually observed control. Close ordinary
DevTools during baseline trials: opening it also changes the condition being
measured. Run detailed instrumented captures separately from the primary outcome
comparison.

Only if attachment changes outcomes should we prototype a narrower automation
transport or lifecycle. Blindly deleting `Runtime.enable` can break frame and
execution-context tracking, especially after navigation and across origins.
Reintroducing console wrappers or `Error.prepareStackTrace` modifications would
add unrelated observable differences without establishing the cause.

## 4. Native patches can still make the browser distinctive

| Surface | Evidence | Improvement to evaluate |
| --- | --- | --- |
| `navigator.webdriver` | Patch 2 removes the property. Runtime probe: `'webdriver' in navigator` is false and the prototype descriptor is absent. | Compare with an ordinary, non-automated Window, where the native property exists and returns false. Preserve worker API differences. Native removal is still an observable API-shape change; test a false-valued native Window property as a separate ablation. |
| Graphics | Fresh GPU diagnostic reports `gl=disabled`, WebGL/WebGPU `disabled_off`, and no WebGL context. | Compare with a real display and the actual GPU backend. Disabled graphics are internally consistent, but consistency does not imply a common desktop configuration. |
| Viewport | Existing configuration forces a 1920×1080 viewport/screen; prior audit found `outer == inner`. Patch 7 returns layout dimensions for visual viewport dimensions. | Test without Patch 7's switch, then test zoom, scrollbars, resize, and frames. Visual and layout viewports need not always be equal. Preserve native relationships rather than forcing equality. |
| Media devices | Patch 11 returns an empty enumeration. | Compare with its switch omitted under the same permission/device conditions. Empty devices are a valid environment, not automatically a defect or a guaranteed stealth improvement. |
| Locale | Main/iframe/worker language equality passed the fresh integration diagnostic. | Retain the native propagation fix; extend coverage to ServiceWorkers, cross-origin frames, HTTP headers, and API-level locale overrides. |

The Window webdriver getter lives in
`third_party/blink/renderer/core/frame/navigator.cc:100`, while Patch 2 gates the
IDL binding. The current consistency test explicitly requires `undefined`, so
it would need a deliberate contract update if a false-valued native Window
property proves preferable. Do not demand the same property surface on
WorkerNavigator.

Our documentation's blanket claim that new headless mode always disables the
GPU is too broad. It describes the measured local configuration. Chrome
documents headless GPU operation under suitable hardware, drivers, and launch
configuration. `ozone_platform_headless=true` in GN arguments alone does not
prove hardware acceleration is impossible.
[Chrome headless GPU testing](https://developer.chrome.com/blog/supercharge-web-ai-testing)

The earlier removal of fake GPU identity, synthetic-event trust changes, timing
jitter, and the stack-trace guard remains sensible. This review found no evidence
to restore those patches. The fresh `Event.isTrusted` regression tests passed.

## 5. Request flow and challenge handling need independent fixes

### Form POST has a different origin and navigation context

[`_post_request()`](../src/flaresolverr/flaresolverr_service.py) submits from a
`data:` document. The localhost receiver measured:

```text
Origin: null
Sec-Fetch-Site: cross-site
Sec-Fetch-Mode: navigate
Sec-Fetch-Dest: document
Referer: [absent]
```

The raw XHR path instead produced a same-origin request, but first made a GET to
the API endpoint. Its Referer was the endpoint itself. These are not the same
request history as the site's application page calling its API.

**Proposed improvement:** provide an explicit request mode that operates from
an already loaded same-origin application page in a retained session. Preserve
the browser's real origin, cookies, and request metadata. Keep form navigation
semantics explicit for callers that need them. Do not fabricate browser-managed
headers to mask the different request context.

This cannot alone explain the reported loop: GET `/api` and a genuine in-page
fetch were also challenged. Loading `/en/` first is a useful control, not a
demonstrated workaround.

### XHR challenge HTML is not an API response or a normal navigation

`_post_request_raw()` GETs the target, sends XHR before the outer challenge
resolver runs, and writes the response into the current document. It does not
retain the complete navigation/response semantics of a real top-level challenge.
After a challenge redirects, the code has no explicit success/replay protocol
for the original POST. Its timeout loop can also finish without verifying the
XHR completed.

Cloudflare documents that full-page challenges are incompatible with ordinary
XHR/fetch response handling. Its pre-clearance facility is configured by the
site owner; a client cannot assume the target has enabled it.
[Challenge-page compatibility](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/)

**Proposed improvement:** retain status, headers, body, and request identity
separately; detect challenged API responses explicitly. Preserve the application
page. Any retry must establish the appropriate browser state and account for
whether the original operation may have executed. `action=newemail` can create
state, so an unbounded automatic replay loop is the wrong success criterion.

### Hidden template text suppresses checkbox attempts

The user-reported bug is supported by
[`_should_attempt_verify_click()`](../src/flaresolverr/services/cloudflare.py):

- Searching `page_source` finds hidden/template text as well as visible text.
- Any occurrence of the automatic-verification sentence returns false before
  checking interactive markers.
- The success branch queries a fixed ID, `ijUz0`. If it is missing, JavaScript
  returns false for `is_hidden`, and Python interprets that as visible success.
- This can prevent an attempt even when an interactive widget exists.

Use visible element state and actual interactive readiness instead of raw HTML
phrases or a fixed generated ID. Cover hidden templates, missing IDs, visible
success, visible controls, and a genuinely automatic challenge. Avoid counting a
Tab/Space dispatch as proof a control was activated. This is a separate fix;
there is nothing to click in the reported non-interactive failure.

## 6. Observability currently hides the distinction between failure modes

[`_build_challenge_result()`](../src/flaresolverr/flaresolverr_service.py) assigns
status `200` and usually empty headers. `_post_request_raw()` records
`window.__flaresolverr_raw_post_status`, but the result builder does not consume
it. A successful FlareSolverr command is therefore not proof of a successful
target HTTP response.

CloudflareService recognizes selected titles/selectors, but not the response
header `cf-mitigated: challenge`. That header identifies Challenge Page
responses, including challenges returned to XHR. It is not a universal detector
for inline Turnstile or every denial.
[Cloudflare response detection](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/)

`recordHar` is useful but incomplete: [`performance_logs_to_har()`](../src/flaresolverr/utils.py)
indexes by request ID, so redirect hops can overwrite one another; it ignores
the ExtraInfo events needed for some headers/cookie details and hardcodes the
request protocol to HTTP/1.1. The success path builds HAR only after resolution.
CloudflareService inherits a `get_debug_info()` that returns `None`, leaving the
most useful evidence missing on a timeout. Named sessions always enable
performance logging, which also makes them a different instrumentation condition
from default one-off requests.

**First diagnostic improvement:** capture a bounded failure record containing:

- Original request method/URL, final URL, actual response status, content type,
  `cf-mitigated`, Ray ID, and each redirect hop.
- Challenge type/state, iframe URLs, visible error codes, relevant failed
  resources, screenshot, and final page title.
- Browser/driver versions, selected binary and effective launch switches,
  effective stealth mode, headless/display state, and session reuse state.
- Whether clearance was issued and returned on the next relevant request,
  including cookie scope/expiry. Redact cookie values, tokens, and credentials.

Distinguish challenge responses, application errors, network failures, browser
crashes, and solver timeouts. A successful result must verify the expected API
response, not just disappearance of a title or presence of a clearance cookie.
Clearance has scope and levels; it does not guarantee every subsequent request
will be accepted.
[Cloudflare clearance](https://developers.cloudflare.com/cloudflare-challenges/concepts/clearance/)

## 7. Launch, session, and transport controls to audit

- **Effective stealth mode:** the supplied request omits `stealthMode`.
  `get_config_stealth_mode()` defaults to `off`; local Compose defaults to
  `standard`. Record the running server's actual setting. A standalone test
  process's environment does not change an already running API server.
- **Native modifications persist in off mode:** the custom binary and its UA
  override/automation flag remain active. `STEALTH_MODE=off` is not a stock
  Chromium baseline.
- **Profile lifetime:** one-off requests create and destroy a fresh profile.
  Use a named session for multi-step comparisons, retain the same identity and
  egress, and record whether clearance was actually obtained. Loading a passive
  homepage alone is not proof of clearance.
- **Launch flags:** one-byte caches, a one-renderer limit, disabled background
  networking, disabled QUIC/HTTP3, and unconditional certificate-ignore flags
  depart from ordinary browser configuration. Test a minimal supported launch
  separately; none is a confirmed Cloudflare trigger here.
- **Repeated switches:** several `--disable-features=` arguments are appended,
  including a final extension-related value. Consolidate intended feature
  lists and verify Chromium's effective configuration instead of assuming all
  repeated values are combined. `CHROME_DISABLE_OPTIMIZATIONS=true` does not
  remove every fixed flag, and extra flags alone are not a reliable ablation API.
- **Extension:** the proxy extension loads even without a proxy. Compare a
  no-extension browser as a separate control. Its presence is not proof the
  page can enumerate it or that it causes rejection.
- **Transport/network:** real Chromium supplies its own TLS stack for browser
  requests. There is no evidence here of a Python TLS fingerprint being used
  for `/api`. Local execution still leaves egress reputation, VPN/proxy effects,
  resource failures, and target rules open. Compare the same URL in an ordinary
  browser on the same network before proposing TLS modifications.
- **Build provenance:** `.stealth-patched` proves only the presence of a marker.
  Record Chromium revision, patch-script hash, GN arguments, ChromeDriver
  version, and binary hashes in a build manifest. Patch removal from `apply.py`
  does not automatically revert an already patched source checkout. The local
  checkout has additional dependency changes; inspect those before any rebuild
  or reset.

## Prioritized improvement plan

| Priority | Work | Acceptance evidence |
| --- | --- | --- |
| P0 | Preserve response/failure evidence and effective configuration | A timeout produces actual target status, challenge header, Ray ID, redirects, visible state, and browser configuration. |
| P0 | Fix unified native UA generation and remove default UA override together | Reduced legacy UA without `HeadlessChrome`; native high-entropy values restored in JS and opted-in headers across relevant contexts. |
| P1 | Compare no attachment, debugger port only, and ChromeDriver attachment | A repeatable change in target outcome under otherwise matching conditions before changing CDP behavior. |
| P1 | Compare headed real-display and headless configurations | Record actual graphics state and target outcomes; isolate display mode from browser version and profile history. |
| P1 | Fix visible-state click detection | Hidden templates cannot suppress a real interactive control; automatic challenges receive no blind clicks. |
| P1 | Preserve same-origin API request context and real responses | Local fixtures verify origin, cookies, redirect/body/status handling, challenge classification, and bounded retry behavior. |
| P2 | Reassess webdriver property shape, viewport and media patches individually | Native API/behavior comparisons and target results justify each retained patch. |
| P2 | Simplify launch configuration and record reproducible build provenance | Effective switches are unambiguous and every tested binary maps to a source/patch manifest. |

For target experiments, first record the same `/api` GET in ordinary Chrome,
custom headed Chrome without attachment, and the current attached browser on the
same network. Keep profile starting state comparable and record cold versus
retained sessions separately. A subsequent POST comparison must use the same
body, content type, application context, and valid token state. Alternate trial
order and use a small, spaced series rather than continuous retries. A single
successful or failed request is insufficient to attribute a change.

If ordinary Chrome also loops on GET `/api`, request the site's error/Ray-ID
diagnosis before interpreting the outcome as proof of a Chromium patch defect.
If a newer stock browser passes, compare versions separately: installed Chrome
153 and custom Chromium 151 differ in more than our patches.

## Verification performed

| Check | Result |
| --- | --- |
| `uv run make` | Formatting passed; stopped at pre-existing Ruff FURB188 in `flaresolverr_service.py:1495`. |
| Unit suite with `STEALTH_MODE=standard` | **421 passed** in 37.16 seconds. |
| Browser consistency, event trust, GPU integration diagnostics | **5 passed** in 14.96 seconds. |
| Separate complexity and Bandit targets | Completed; Bandit reported no issues in its configured scope. |
| Separate Pyright target | Two existing optional-value errors at `flaresolverr_service.py:1495`. |
| Separate Vulture target | Passed. |
| Local UA/headers/POST probe | Three fresh-browser variants; measurements recorded above. |
| Live Cloudflare comparison / rebuilt Chromium | Not performed. Target failures are attributed to the user's reproduction. |

The integration suite still passes with empty high-entropy client hints:
`test_browser_consistency.py` checks legacy navigator fields, but does not assert
high-entropy UA data or HTTP client hints. Its iframe is same-origin and its
workers are Blob workers. Extend this regression coverage to server-observed
headers, high-entropy hints, ServiceWorkers, cross-origin frames, and dynamic
viewport behavior. Keep ordinary-browser semantics as the reference where
appropriate; equality between several altered contexts is not sufficient.

Review artifacts on this machine:

```text
/tmp/cloudflare-review-probe.py
/tmp/cloudflare-review-probe.json
/tmp/cloudflare-review-probe.log
/tmp/cloudflare-review-integration.log
/tmp/gpu_architecture_custom.json
```

The temporary probe changes only the in-process launch-options builder and
restores it afterward; no production source or Chromium source was changed.
The tables above preserve its significant results without depending on `/tmp`
retention. Existing integration diagnostics can be rerun with:

```bash
PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard uv run python -m pytest \
  tests/integration/test_browser_consistency.py \
  tests/integration/test_event_istrusted.py \
  tests/integration/test_gpu_architecture.py -m integration -s
```

Update the UA, webdriver, and GPU claims in `STEALTH_DESIGN.md` and the project
notes when implementing the selected changes; those documents currently
overstate what the native UA patch and headless configuration guarantee.

# Cloudflare detection review: custom Chromium

Reviewed 2026-09-21. FlareSolverr revision: `ad81349c583200a946ed0ab910df813cccb09386`.
Custom binary at review time: Chromium `151.0.7922.112`. Local source:
`/media/stefan/data3/chromium/src`, revision
`6b03a2f2a6e84ae290fc0558db607cfd4ea2bb86`, with existing patches and dependency changes.
Installed Google Chrome reports `153.0.8010.52`; it is not a matched-version control.

**Follow-up (2026-09-21, same day):** all P0–P2 items were implemented on
`feature/cloudflare-detection-review` and the custom binary was rebuilt as
Chromium `154.0.8037.49` (manifest `native-ua` present). The controlled
attachment/display matrix was executed against the reported targets; results
are in [§8](#8-follow-up-measurements-2026-09-21). Sections below keep the
original review findings; an *implemented* note marks what changed.

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

*Follow-up:* the native UA path is fixed and shipped in `154.0.8037.49`, and the
controlled comparisons now exist (§8): with identical launch flags, the
attach mechanism (manual-CDP vs chromedriver-owned) does not change outcomes —
but the UA identity itself is confirmed detection-relevant (a `HeadlessChrome`
UA flipped tmailor to a managed challenge). tempmailo rejects every arm —
consistent with a per-target policy or reputation rather than a browser defect.

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

These target results were initially **user-supplied observations**. They were
subsequently reproduced live: `postData` and `postDataRaw` to `/api` both loop
on the managed challenge, a bare `GET /api` is also challenged, `/en/` passes
passively, and an in-page `fetch('/api')` from the passed page receives
challenge HTML — the endpoint-level managed challenge is method-independent.
The matrix runs in §8 supply the missing response metadata (Ray IDs,
`cType: managed`, marker sets) and the attachment/display controls. A valid
`curentToken` has still never been exercised.

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

*Implemented:* the custom binary exposes `--stealth-native-ua` (Patch 6b) and
`_build_chrome_options()` drops `--user-agent` when the binary's
`.stealth-manifest.json` advertises `native-ua`; older binaries keep the
override as a fallback. `apply_user_agent_override()` now also sets
`userAgentMetadata` on custom builds so an explicit user UA still carries
coherent client hints. Verified at runtime: the rebuilt binary receives
`--stealth-native-ua` and no `--user-agent` launch argument.

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

*Implemented:* `apply.py` gained Patch 6b, which gates the `Headless` product
token in `GetUserAgentInternal()` (`user_agent_utils.cc:216`) on the new
`--stealth-native-ua` switch; Patch 9 forwards the switch to renderer processes.
The rebuilt `154.0.8037.49` image reports `native-ua` in its manifest. The
cross-context UA/UA-CH acceptance sweep (frames, Dedicated/SharedWorker,
server-observed `sec-ch-ua-*` headers) is still pending against this build.

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

**Experiment performed:** `tests/integration/test_cf_challenge_matrix.py`
compares four arms — manual launch + debugger attach (headless and headed),
ChromeDriver-owned launch, and no-external-attach `--dump-dom` — with
identical launch flags, on direct and SOCKS egress. Results in
[§8](#8-follow-up-measurements-2026-09-21): with flags held constant,
**attachment does not change the outcome** on either target — an apparent
earlier effect was a flag confound (`HeadlessChrome` UA). The UC-vs-manual
difference now reduces to chromedriver's own injected launch switches
(`--enable-automation` etc.), which did not flip either target in these runs.

Since attachment did not change outcomes, a narrower automation transport is
**not currently justified** by this measurement — keep it as a candidate only
if a future isolated comparison shows one. Blindly deleting `Runtime.enable`
can break frame and execution-context tracking, especially after navigation
and across origins. Reintroducing console wrappers or
`Error.prepareStackTrace` modifications would add unrelated observable
differences without establishing the cause.

## 4. Native patches can still make the browser distinctive

| Surface | Evidence | Improvement to evaluate |
| --- | --- | --- |
| `navigator.webdriver` | Patch 2 removes the property. Runtime probe: `'webdriver' in navigator` is false and the prototype descriptor is absent. | Compare with an ordinary, non-automated Window, where the native property exists and returns false. Preserve worker API differences. Native removal is still an observable API-shape change; test a false-valued native Window property as a separate ablation. *Variant available:* building with `FLARESOLVERR_WEBDRIVER_FALSE_PROPERTY=1` keeps the property present-but-false (manifest `webdriver-false`); the runtime then also omits `--disable-blink-features=AutomationControlled`. |
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

*Implemented (ablation control):* `STEALTH_OMIT_FLAGS` suppresses selected
`--stealth-*` switches at launch (`stealth-native-ua`,
`stealth-navigator-languages`, `stealth-viewport-size`,
`stealth-no-media-devices`), so switch-gated patches can be ablated per process
without a rebuild.

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

*Implemented:* `sessions.fetch` issues `fetch()` inside a named session's
loaded page (`credentials: "include"`, same-origin enforced, relative URLs
resolved). It returns status, headers, body, final URL, and a `challenged`
flag derived from `cf-mitigated: challenge` or challenge HTML. It honestly
cannot execute a returned challenge interstitial — see API.md.

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

*Implemented:* `_post_request_raw()` now stores status, response headers, and
body in `window.__flaresolverr_raw_post_*` globals instead of overwriting the
document, and `_build_challenge_result()` surfaces the real status/headers/body.
Challenge HTML or `cf-mitigated` responses are classified as challenged rather
than silent successes.

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

*Implemented:* `_should_attempt_verify_click()` now runs a single
visibility-aware JS probe — a rendered Turnstile iframe/checkbox or verify
button triggers a click, visible success text suppresses it, and hidden
template text no longer counts as either. The `ijUz0` lookup is gone; the
click is verified by a post-click state change in `resolve()`.

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

*Implemented:* performance logging is enabled for all drivers (removing the
session-vs-one-off instrumentation confound), `utils.get_last_document_response()`
returns final status, `cf-mitigated`, `cf-ray`, and the redirect chain,
`CloudflareService.get_debug_info()` produces a bounded failure record
(challenge metadata from `_cf_chl_opt`, iframes, cookie names, versions, launch
arguments, screenshot) surfaced through `ChallengeError.details`, and failures
are classified as `challenge_timeout`, `challenge_denied`, `nav_error`,
`browser_crash`, or `solver_timeout`.

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
- **Repeated switches:** *fixed.* All `--disable-features` values are now
  consolidated into a single switch; Chromium treats repeated instances as
  replace-not-merge, so the previous code silently discarded all but the last.
  `CHROME_DISABLE_OPTIMIZATIONS=true` still does not remove every fixed flag,
  and extra flags alone are not a reliable ablation API — use
  `STEALTH_OMIT_FLAGS` for the stealth switches instead.
- **Extension:** *fixed.* The proxy extension now loads only when a proxy is
  configured for the driver, or when the driver is session-scoped and may
  receive a dynamic proxy later. A no-proxy launch is now extension-free.
- **Transport/network:** real Chromium supplies its own TLS stack for browser
  requests. There is no evidence here of a Python TLS fingerprint being used
  for `/api`. Local execution still leaves egress reputation, VPN/proxy effects,
  resource failures, and target rules open. Compare the same URL in an ordinary
  browser on the same network before proposing TLS modifications.
- **Build provenance:** *implemented.* The self-hosted build writes
  `/opt/chromium/.stealth-manifest.json` (via `apply.py --write-manifest`)
  recording Chromium version/revision, applied patch IDs, `apply.py` and
  GN-args hashes, binary hashes, and build timestamp; the runtime reads the
  manifest beside the binary to gate manifest-dependent behavior. Patch removal
  from `apply.py` still does not automatically revert an already patched source
  checkout. The local checkout has additional dependency changes; inspect those
  before any rebuild or reset.

## Prioritized improvement plan

| Priority | Work | Status | Acceptance evidence |
| --- | --- | --- | --- |
| P0 | Preserve response/failure evidence and effective configuration | **Done** | Timeouts now carry status, `cf-mitigated`, Ray ID, redirect chain, `_cf_chl_opt` metadata, screenshot, and launch configuration via `ChallengeError.details`; failure kinds are classified. |
| P0 | Fix unified native UA generation and remove default UA override together | **Done** (rebuilt binary `154.0.8037.49`) | `--stealth-native-ua` active, `--user-agent` dropped; reduced UA has no `Headless` token. Cross-context UA-CH sweep still pending. |
| P1 | Compare no attachment, debugger port only, and ChromeDriver attachment | **Done** — matrix executed | With identical flags, attachment does not change outcomes on either target; an earlier apparent effect was a flag confound (§8). |
| P1 | Compare headed real-display and headless configurations | **Done** — matrix arms | Identical verdicts headed vs headless on both targets and both egresses (§8). |
| P1 | Fix visible-state click detection | **Done** | Visibility-aware probe; hidden template text cannot suppress a rendered control; unit-tested. |
| P1 | Preserve same-origin API request context and real responses | **Done** | `sessions.fetch` command; raw-post responses keep real status/headers/body and classify challenges. |
| P2 | Reassess webdriver property shape, viewport and media patches individually | **Partially** | `webdriver-false` build variant + `STEALTH_OMIT_FLAGS` runtime ablation exist; per-patch target ablations not yet run. |
| P2 | Simplify launch configuration and record reproducible build provenance | **Done** | Single `--disable-features` switch; proxy extension only when needed; `.stealth-manifest.json` per build. |

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

## 8. Follow-up measurements (2026-09-21)

Measured with the rebuilt custom binary `154.0.8037.49` (`native-ua` manifest;
`--stealth-native-ua` active, no `--user-agent`). Harness:
`tests/integration/test_cf_challenge_matrix.py`. Four arms, all sharing the
production launch flags so only the launch/attach mechanism differs:

- `manual-headless` / `manual-headed` — `get_webdriver()` path: Chromium
  launched manually, Selenium attaches over the debugger port.
- `uc-chromedriver` — same flags, but ChromeDriver owns the browser launch
  (`--enable-automation`, CDC injection surface) as the detection control.
- `dump-dom` — `chrome --headless=new --dump-dom` subprocess: no external
  attachment, but **not a zero-CDP control** — Chromium implements `--dump-dom`
  via internal DevTools machinery and exits at page load + virtual-time budget,
  so a managed challenge gets little real time to resolve. Weak signal only.

Isolated-flags run (`/tmp/cf_matrix_isolated.json`, direct egress — every arm
receives the identical production flag set, so only the launch/attach
mechanism differs):

| Arm | tmailor.com/en | tempmailo.com |
| --- | --- | --- |
| manual-headless | **passed** | challenged (managed) |
| manual-headed | **passed** | challenged (managed) |
| uc-chromedriver | **passed** | challenged (managed) |
| dump-dom (no external attach) | timeout* | challenged (managed) |

\* `dump-dom` waits for load quiescence; tmailor's real page embeds a Turnstile
widget whose network activity exceeds the timeout — a harness artifact, not a
challenge signal.

An earlier run with the UC arm missing the stealth flags (notably
`--stealth-native-ua`, i.e. a `HeadlessChrome` UA) had shown it challenged on
tmailor — that difference was the flags, not the attachment.

### Conclusions

1. **ChromeDriver attachment is NOT a confirmed detection signal.** With the
   identical production flag set, the chromedriver-launched arm passes
   tmailor exactly like the manual-launch arms. The earlier pass→challenge
   flip was a configuration confound (missing `--stealth-native-ua` — a
   `HeadlessChrome` UA), which also demonstrates that the UA identity is
   itself a live detection input on this target.
2. **tempmailo rejects every arm**, including the no-external-attach
   `dump-dom` run. Since `dump-dom` is only a weak control (internal CDP
   machinery, exits at load), this cannot rule out attachment — but the
   consistent rejection across all launch/attach/display variants points to
   egress reputation, passive fingerprinting, or target policy rather than
   anything fixable client-side.
3. **Egress does not change outcomes** between direct and SOCKS routes in
   these runs — two egresses agreeing does not rule out reputation effects
   (both share the same operator/network history), but neither shows a
   proxy-specific penalty.
4. **Headed vs headless does not change outcomes** on this build.
5. **A `cf_clearance` cookie alone is not a pass.** tempmailo issued clearance
   mid-challenge in two runs while the interstitial stayed up — clearance is
   recorded as metadata, never as success without positive page evidence.
6. The `/api` POST path remains untested by this matrix (all arms GET `/en/`
   or `/`). Its endpoint-level managed challenge stands as previously
   measured.

### Harness corrections made along the way

- Challenge titles are localized (`Nur einen Moment…`), so verdicts key on
  locale-independent DOM markers (`_cf_chl_opt`, `challenge-stage`,
  `cf-challenge-running`).
- `cf-turnstile`, `challenges.cloudflare.com`, and `cdn-cgi/challenge-platform`
  are **weak** markers — real pages embed Turnstile widgets and JS-Detections
  scripts, so they never force a "challenged" verdict alone.
- "passed" now requires positive evidence: `chrome-error://` URLs classify as
  `nav_error`, navigation exceptions and sub-256-byte documents are never
  passes, and a stale `cf_clearance` cannot override a challenge title.
- `cRay`/`cType` regexes accept unquoted JS keys; matched markers and DOM
  length are recorded per result.
- All arms share `_build_chrome_options()` output so comparisons isolate the
  attach mechanism, and `dump-dom` gains `--virtual-time-budget` so the
  challenge JS gets virtual time to run before the dump.

Run it with:

```bash
PYTHONDONTWRITEBYTECODE=1 STEALTH_MODE=standard \
  CF_MATRIX_PROXY=socks5://127.0.0.1:1080 \
  FLARESOLVERR_CF_MATRIX=/tmp/cf_matrix.json \
  uv run python -m pytest tests/integration/test_cf_challenge_matrix.py -m integration -s
```

## Verification performed

| Check | Result |
| --- | --- |
| `uv run make` | **Fully green** after implementation (the FURB188/pyright findings were fixed in `11e1c02`). |
| Unit suite with `STEALTH_MODE=standard` | **465 passed** (includes new failure-evidence, verify-click, `sessions.fetch`, launch-option, and proxy-credential tests). |
| Browser consistency, event trust, GPU integration diagnostics | **5 passed** in 14.96 seconds (pre-rebuild). |
| Separate complexity and Bandit targets | Completed; Bandit reported no issues in its configured scope. |
| Separate Pyright target | Clean — 0 errors. |
| Separate Vulture target | Passed. |
| Local UA/headers/POST probe | Three fresh-browser variants; measurements recorded above. |
| Self-hosted Chromium rebuild | **Succeeded** — `ghcr.io/smeinecke/chromium-stealth:154.0.8037.49`, manifest lists `native-ua` among 9 patch IDs. |
| Live Cloudflare comparison (matrix harness) | **Performed** — see §8; two egresses, four arms. |
| Cross-context UA/UA-CH sweep on rebuilt binary | Not yet performed. |

The pre-rebuild integration suite passed with empty high-entropy client hints:
`test_browser_consistency.py` checks legacy navigator fields, but does not assert
high-entropy UA data or HTTP client hints. Its iframe is same-origin and its
workers are Blob workers. With `native-ua` now active on the rebuilt binary,
those hints should be populated — the pending sweep must re-verify this and
extend coverage to server-observed headers, high-entropy hints, ServiceWorkers,
cross-origin frames, and dynamic viewport behavior. Keep ordinary-browser
semantics as the reference where appropriate; equality between several altered
contexts is not sufficient.

Review artifacts on this machine:

```text
/tmp/cloudflare-review-probe.py
/tmp/cloudflare-review-probe.json
/tmp/cloudflare-review-probe.log
/tmp/cloudflare-review-integration.log
/tmp/gpu_architecture_custom.json
/tmp/cf_matrix_direct3.json
/tmp/cf_matrix_sonar.json
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

*Done:* the UA, webdriver, and GPU claims in `STEALTH_DESIGN.md` and `AGENTS.md`
were corrected as part of the implementation branch — the native-UA ownership
table, the softened headless-GPU claim, the `webdriver-false` variant, and
`STEALTH_OMIT_FLAGS` are documented there.

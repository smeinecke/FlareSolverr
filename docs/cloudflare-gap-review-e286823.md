# Review of b9d5eb1 and e286823

Reviewed 2026-09-23. Range: `40b084b..e286823`.

**Result: five reproduced issues remain; G1–G8 should not all be marked closed.**
The response fixes work for ordinary GET 404 and empty raw POST 204. The full
`uv run make` validation passed, including 477 tests. These tests do not cover
the remaining cases below.

Scope: source review of both commits, two localhost HTTP servers with the local
custom Chromium, and deterministic inputs to the evidence/matrix classifiers.
No external mail-site requests or Chromium rebuild were performed. Local probe
results are preserved in
[the evidence JSON](evidence/cloudflare-gap-review-e286823.json).
Production code was not changed during this review.

## R1 — P1: sessions.fetch checks redirects after sending the request

Related gap: G8. Location:
`src/flaresolverr/flaresolverr_service.py:868–875`.

The new final-origin check runs after `fetch()` follows redirects and reads the
response body. Fetch still uses its default CORS mode. A same-origin endpoint
can return a 307/308 to another origin, forwarding the POST body and permitted
custom headers before Python rejects the result. Rejecting the response does
not enforce the advertised same-origin request boundary.

**Reproduced:** a POST to localhost server A returned a 307 to server B on a
different port. B allowed the CORS exchange and received both
`review=redirect` and `X-Review-Marker: local-test`. Only afterward did
`sessions.fetch` raise its different-origin error. Both servers were controlled
by the probe; the payload was synthetic.

**Fix:** enforce the origin restriction in the browser request, for example
with `mode: 'same-origin'`, or reject redirects before following them. Keep the
final URL check as an additional assertion.

**Acceptance:** a cross-origin 307/308 must not deliver the body/custom header to
the second server. Same-origin redirects must retain the documented behavior.

## R2 — P2: raw POST abort does not cover maxTimeout

Related gap: G2. Location:
`src/flaresolverr/flaresolverr_service.py:1771–1778`.

The new abort runs only when `_post_request_raw` reaches its own hardcoded
60-second deadline. `_resolve_challenge` wraps the entire request in
`func_timeout(maxTimeout / 1000, ...)`. That deadline interrupts the polling
loop first for shorter limits, and normally for the default 60-second limit
because navigation precedes the inner timer. The outer timeout handler does
not abort the XHR, and retained sessions are not closed.

**Reproduced:** with a retained driver, `maxTimeout: 1000`, and a POST whose
response was delayed five seconds, the API raised its timeout after about
1.02 seconds. At that point the XHR had `readyState: 1`, `done: false`, and no
abort error. Later it reached `readyState: 4`, `done: true`, still without an
abort error. The probe used the real request path and timeout wrapper; only
session lookup and failure-evidence collection were replaced with local test
fixtures.

The outstanding XHR can still change session state after the request lock is
released. The new branch therefore does not fulfill the claimed timeout
cleanup contract.

**Fix:** perform XHR cleanup for outer request cancellation before releasing
the session lock, and align the inner deadline with the remaining request
budget. Preserve the normal successful completion path.

**Acceptance:** exercise retained-session timeouts both below and at the default
limit, and verify that the browser XHR is aborted before the handler returns.

## R3 — P2: response metadata is captured before navigation actions

Related gap: G1. Location:
`src/flaresolverr/flaresolverr_service.py:1649–1656`.

The shared performance-log drain now supplies status and headers before
`_build_challenge_result` executes request actions or `waitInSeconds`. The
response body is read afterward. If an action or delayed page script navigates,
the API combines metadata from the previous document with the final body.

**Reproduced:** request GET `/start` (200), followed by an eval action setting
`window.location.href='/missing'` and a 0.5-second wait. `/missing` returned 404.
The result contained the `/missing` body, but reported status 200 and URL
`/start`; the actual browser URL was `/missing`.

**Fix:** finish actions/waits before capturing the final URL, document evidence,
and body. If logs must be drained earlier, accumulate subsequent entries and
select the final document while retaining all relevant entries for HAR.
Keep raw POST metadata tied to its stored XHR result.

**Acceptance:** a navigation action and a navigation during `waitInSeconds`
must each produce consistent URL/status/headers/body, including with `recordHar`.

## R4 — P2: uncertain iframe evidence still becomes solution.status

Related gaps: G1/G7. Location:
`src/flaresolverr/flaresolverr_service.py:1421–1424`.

`get_document_response_evidence` now explicitly marks its last-resort Document
selection with `mainFrameIdentified: false`. `_build_challenge_result` ignores
that flag and copies the selected status and headers into the API result.
An iframe response can still become an authoritative top-level response when
the main document is missing from the available log.

**Reproduced with deterministic entries:** the driver identified frame `main`
and URL `/main`; the supplied log contained only child-frame `/frame` with
status 200. Evidence correctly returned `mainFrameIdentified: false`, but
`solution.status` was still 200. This was a synthetic partial-log test, not a
claim that the localhost browser spontaneously lost its main-frame events.

**Fix:** retain uncertain evidence for diagnostics, but return unknown status
and no attributed document headers when the selected exchange cannot be tied
to the top-level document.

**Acceptance:** add a child-only performance-log case alongside the existing
empty-log and identifiable-main-frame cases.

## R5 — P2: titled error documents still count as matrix passes

Related gap: G5. Location:
`tests/integration/test_cf_challenge_matrix.py:125–131`.

The new title requirement prevents untitled large documents from passing, but
any nonempty title plus enough HTML still counts as `passed` unless one of the
known challenge/browser-error markers matches. Server error pages and unrelated
documents remain false positives. This can still distort comparisons between
browser arms and egress paths.

**Reproduced with deterministic input:** an HTML document titled
`503 Service Unavailable`, with a repeated service-unavailable body longer than
256 characters, was classified as `passed`. This did not require a live server
because the classifier has no HTTP-status input.

**Fix:** require target-specific positive application evidence, incorporate
document HTTP status when available, and report `unknown` when success cannot
be established. Give the dump-DOM arm the same application-level success rule.

**Acceptance:** cover long titled 403/429/503 documents, unexpected redirects,
localized challenge pages, and known successful target content.

## Verified improvements and limits

| Change | Verification |
| --- | --- |
| `b9d5eb1` copies `/opt/chromium/.` | Source review confirms dotfiles are included in staging. No finding on this commit. |
| Ordinary document status and headers | Local GET 404 returned 404 and actual response headers. |
| Empty raw POST response | Local POST 204 returned 204, an empty string body, and the XHR response headers. |
| Full local validation | `uv run make` exited 0; 477 tests passed. |
| Source changes for provenance, alternate build, and resolver backoff | Reviewed; a successful Docker build and live challenge behavior were not established by these local tests. |

The matrix's attachment/display/egress conclusions still require controlled
trials and retained per-run evidence. These commits and the local tests do not
identify which Cloudflare signal causes the reported managed-challenge loops.

## Resolution status (implemented in follow-up commit)

All five findings were confirmed against the source and fixed:

- **R1** — `sessions.fetch` now passes `mode: 'same-origin'` to `fetch()`, so a
  cross-origin 307/308 becomes a network error and is never followed — the
  POST body and custom headers cannot reach another origin. The Python-side
  final-URL check remains as a second assertion.
- **R2** — `_resolve_challenge` now calls `_abort_pending_raw_post(driver)` on
  both `FunctionTimedOut` and generic error paths, aborting any in-flight
  raw-POST XHR before the session lock is released. The inner 60s deadline
  uses the same helper.
- **R3** — `_build_challenge_result` runs `actions`/`waitInSeconds` *before*
  capturing `url`, `userAgent`, the perf-log drain, document evidence, and the
  body — so an action-triggered navigation yields consistent
  URL/status/headers/body. The perf-log drain moved inside the function; HAR
  uses the same captured entries.
- **R4** — when `mainFrameIdentified` is false, the selected exchange is kept
  for diagnostics but `solution.status` reports `null` and no document headers
  are attributed. The raw-POST XHR stash is unaffected (it is the answer, not
  document evidence).
- **R5** — `_verdict_from_page` now takes `http_status` (from the perf log in
  driver arms) and `expected_host`: HTTP >= 400 → `unknown`, error-titled
  documents (503/forbidden/access denied/…) → `unknown`, off-host final URL →
  `unknown` with `redirectedTo` recorded. Deterministic classifier tests cover
  titled 503, 403/429/500/503 statuses, off-host redirect, challenge pages,
  and a normal pass.

Unit coverage: `TestChallengeResultResponse` gains the uncertain-frame and
abort tests; `TestSessionsFetch` asserts `mode: 'same-origin'` in the executed
script; `TestVerdictClassifier` covers the matrix rules deterministically.

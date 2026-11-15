"""POWBlock proof-of-work challenge service.

POWBlock (https://github.com/8Protons/POWBlock) is a self-hosted anti-bot
gate: the proxy 302s the request to a challenge page (e.g. MangaDex mounts
it at https://mangadex.org/edge/challenge) carrying three hidden <pre>
elements - #c (challenge token), #d (difficulty, leading-zero bits), #h
(hash algorithm, 256 or 512). The page JS mines a nonce n such that
SHA-<h>(token + n) has >= d leading zero bits, then resubmits the same URL
with ?powblock=<n>&pbchal=<token>; the server verifies, sets the POW_TOKEN
cookie and redirects to the original URL.

The stock challenge JS refuses to hand out a solution to automation
(`navigator.webdriver` or a HeadlessChrome UA sends it into an endless
solve loop), so this service mines the nonce itself instead of waiting on
the page. At ~1.5M SHA-256/s in CPython a difficulty-20 challenge solves
in about a second.
"""

import hashlib
import logging
import re
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flaresolverr.backends.browser_context import BrowserContext
from flaresolverr.services.base import ChallengeService
from flaresolverr.utils import collect_failure_evidence, wait_for_page_stable

logger = logging.getLogger(__name__)

# Single round-trip DOM probe for the POWBlock markup contract. Defaults
# mirror the stock challenge JS (difficulty 17, SHA-256) so odd custom
# pages still parse.
CHALLENGE_PROBE_SCRIPT = """
var c = document.getElementById('c');
var d = document.getElementById('d');
var h = document.getElementById('h');
if (!c || !d || !h) { return null; }
var token = (c.textContent || '').trim();
if (token.length < 60) { return null; }
var diff = parseInt((d.textContent || '').trim(), 10);
if (!isFinite(diff) || diff < 1) { diff = 17; }
var algo = parseInt((h.textContent || '').trim(), 10);
return { token: token, difficulty: diff, algo: algo === 512 ? 512 : 256 };
"""

_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=\-_]+$")

# Rejected submissions mean an expired token; each retry gets a fresh
# challenge, so bound the attempts instead of looping forever.
MAX_SOLVE_ATTEMPTS = 4
# The outer request timeout bounds total work, but func_timeout cannot kill
# a Python-side mining loop in the orphaned thread - cap it so an expired
# token does not burn CPU after the API call already returned.
MINE_TIMEOUT_SECONDS = 120
# Above this the expected hash count is unreasonable for an interactive
# proxy (2^31 hashes).
MAX_DIFFICULTY = 31
# While mining, periodically check whether the page already solved the
# challenge itself (untrapped browsers auto-redirect) or the driver died.
MINE_POLL_HASHES = 1 << 20

# Submission navigations get superseded on real-browser backends: the
# challenge page's own JS mines the nonce too (Camoufox reports
# navigator.webdriver=false, so the stock solve JS actually runs) and its
# auto-redirect cancels our goto mid-flight - Firefox reports
# NS_BINDING_ABORTED, Chromium net::ERR_ABORTED. The abort means a
# concurrent navigation won, not that the solve failed.
_NAV_ABORT_MARKERS = (
    "ns_binding_aborted",
    "net::err_aborted",
)


def _is_navigation_aborted(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _NAV_ABORT_MARKERS)


class PowBlockService(ChallengeService):
    name = "powblock"

    def detect(self, driver: BrowserContext) -> bool:
        return self._read_challenge(driver) is not None

    def resolve(self, driver: BrowserContext) -> None:
        for attempt in range(1, MAX_SOLVE_ATTEMPTS + 1):
            challenge = self._read_challenge(driver)
            if challenge is None:
                return
            difficulty = challenge["difficulty"]
            if difficulty > MAX_DIFFICULTY:
                raise RuntimeError(f"POWBlock difficulty {difficulty} exceeds supported maximum {MAX_DIFFICULTY}")
            token = challenge["token"]
            logger.info(
                "Solving POWBlock challenge (attempt %d/%d): difficulty=%d algo=SHA-%d",
                attempt,
                MAX_SOLVE_ATTEMPTS,
                difficulty,
                challenge["algo"],
            )
            nonce = self._mine(driver, token, difficulty, challenge["algo"])
            if nonce is None:
                # Mining stopped because the challenge is gone (the page
                # solved itself and navigated away, or the driver died).
                return
            verify_url = self._build_verify_url(driver.current_url, nonce, token)
            logger.debug("Submitting POWBlock solution: %s", verify_url)
            try:
                driver.get(verify_url)
            except Exception as exc:
                if not _is_navigation_aborted(exc):
                    raise
                # A concurrent navigation superseded our submission (page JS
                # solved at the same time, or the verify redirect raced the
                # load wait). Let the page settle, then the next probe decides
                # whether the challenge is actually gone.
                logger.debug("POWBlock submission navigation aborted: %s", exc)
                wait_for_page_stable(driver, timeout=5)
                continue
        if self._read_challenge(driver) is not None:
            raise RuntimeError(f"POWBlock challenge still present after {MAX_SOLVE_ATTEMPTS} solve attempts")

    def get_debug_info(self, driver: BrowserContext, stealth_mode: str | None = None) -> dict[str, Any] | None:
        info = collect_failure_evidence(driver, stealth_mode=stealth_mode)
        challenge = self._read_challenge(driver)
        if challenge is not None:
            info["powblockChallenge"] = {
                "difficulty": challenge["difficulty"],
                "algo": challenge["algo"],
                "tokenLength": len(challenge["token"]),
            }
        info["challengePresent"] = challenge is not None
        return info

    def _read_challenge(self, driver: BrowserContext) -> dict[str, Any] | None:
        try:
            challenge = driver.execute_script(CHALLENGE_PROBE_SCRIPT)
        except Exception:  # noqa: BLE001
            logger.debug("POWBlock probe failed (navigation in progress?)")
            return None
        if not isinstance(challenge, dict):
            return None
        token = challenge.get("token")
        if not isinstance(token, str) or not _TOKEN_RE.match(token):
            return None
        return challenge

    def _mine(self, driver: BrowserContext, token: str, difficulty: int, algo: int) -> int | None:
        """Find n with SHA-<algo>(token + n) >= difficulty leading zero bits.

        Returns the nonce, or None when mining aborted because the challenge
        disappeared (page self-solved, navigation in progress, dead driver).
        Raises TimeoutError when the time budget ran out.
        """
        hasher = hashlib.sha256 if algo == 256 else hashlib.sha512
        prefix = token.encode("ascii")
        full_zero_bytes, rem_bits = divmod(difficulty, 8)
        rem_limit = 1 << (8 - rem_bits)
        zeroes = b"\x00" * full_zero_bytes
        deadline = time.monotonic() + MINE_TIMEOUT_SECONDS
        started = time.monotonic()
        n = 0
        while True:
            digest = hasher(prefix + str(n).encode("ascii")).digest()
            if digest[:full_zero_bytes] == zeroes and (rem_bits == 0 or digest[full_zero_bytes] < rem_limit):
                logger.debug("POWBlock nonce %d found after %.1fs", n, time.monotonic() - started)
                return n
            n += 1
            if n % MINE_POLL_HASHES == 0:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"POWBlock mining exceeded {MINE_TIMEOUT_SECONDS}s at nonce {n}")
                if self._read_challenge(driver) is None:
                    logger.info("POWBlock challenge resolved by the page itself while mining")
                    return None

    @staticmethod
    def _build_verify_url(current_url: str, nonce: int, token: str) -> str:
        """Rebuild the current URL like the challenge JS does: keep every
        query param except powblock/pbchal, then append the solution.

        pbchal goes in raw - POWBlock reads the raw query string and rejects
        a percent-encoded token.
        """
        parts = urlsplit(current_url)
        pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("powblock", "pbchal")]
        query = urlencode(pairs)
        if query:
            query += "&"
        query += f"powblock={nonce}&pbchal={token}"
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

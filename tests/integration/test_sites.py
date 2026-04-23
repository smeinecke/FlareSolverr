import unittest
import re
from urllib.parse import urlparse

import pytest
pytest.importorskip("webtest")
from webtest import TestApp

from flaresolverr.dtos import V1ResponseBase, STATUS_OK
from flaresolverr.flaresolverr import app
from flaresolverr import utils

pytestmark = pytest.mark.integration

def asset_cloudflare_solution(self, res, site_url, site_text, site_url_pattern: str | None = None):
    self.assertEqual(res.status_code, 200)

    body = V1ResponseBase(res.json)
    self.assertEqual(STATUS_OK, body.status)
    self.assertIn(body.message, {"Challenge solved!", "Challenge not detected!"})
    self.assertGreater(body.startTimestamp, 10000)
    self.assertGreaterEqual(body.endTimestamp, body.startTimestamp)
    self.assertEqual(utils.get_flaresolverr_version(), body.version)

    solution = body.solution
    if site_url_pattern is not None:
        self.assertRegex(solution.url, re.compile(site_url_pattern))
    else:
        requested_host = urlparse(site_url).netloc
        final_host = urlparse(solution.url).netloc
        self.assertTrue(
            final_host == requested_host or final_host.endswith(f".{requested_host}"),
            f"Final host '{final_host}' does not match requested host '{requested_host}'",
        )
    self.assertEqual(solution.status, 200)
    self.assertIs(len(solution.headers), 0)
    if isinstance(site_text, tuple):
        self.assertTrue(any(candidate in solution.response for candidate in site_text))
    else:
        self.assertIn(site_text, solution.response)
    self.assertIn("Chrome/", solution.userAgent)


class TestFlareSolverr(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = TestApp(app)
        # wait until the server is ready
        cls.app.get("/")

    def test_v1_endpoint_request_get_cloudflare(self):
        sites_get = [
            ("nowsecure", "https://nowsecure.nl", "<title", None),
            # ("0magnet", "https://0magnet.com/search?q=2022", "Torrent Search - ØMagnet", None),  # Site is unstable/broken (returns internal server error content).
            # ("1337x", "https://1337x.unblockit.cat/cat/Movies/time/desc/1/", "", None),  # Mirror appears parked/unstable (redirects to ww16 host/parking flow).
            # ("avistaz", "https://avistaz.to/api/v1/jackett/torrents?in=1&type=0&search=", ("<title>Access denied</title>", "<title>Unauthorized</title>"), None),  # Target behavior changed (auth-gated response without stable anti-bot artifacts).
            # ("badasstorrents", "https://badasstorrents.com/torrents/search/720p/date/desc", "<title>Latest Torrents - BadassTorrents</title>", None),  # Domain appears parked/redirected to ad/parking domain.
            ("bt4g", "https://bt4gprx.com/search?q=2022", "<title>Download 2022 Torrents - BT4G</title>", r"https://bt4gprx\.com/search\?q=2022"),
            # ("cinemaz", "https://cinemaz.to/api/v1/jackett/torrents?in=1&type=0&search=", ("<title>Access denied</title>", "<title>Unauthorized</title>"), None),  # Target behavior changed (auth-gated response without stable anti-bot artifacts).
            # ("epublibre", "https://epublibre.unblockit.cat/catalogo/index/0/nuevo/todos/sin/todos/--/ajax", "<title>epublibre - catálogo</title>", None),  # Mirror appears parked/redirect flow changed.
            # ("ext", "https://ext.to/browse/?sort=age&order=desc&age=4", "<title>Download Latest Torrents - EXT Torrents</title>", r"https://ext\.to/browse/\?sort=age&order=desc&age=4"),  # Target content/flow changed and no longer returns stable expected page marker.
            ("extratorrent", "https://extratorrent.st/search/?srt=added&order=desc&search=720p&new=1&x=0&y=0", "Page 1 - ExtraTorrent", None),
            # ("idope", "https://idope.pics/torrent-list/harry/", "<title>iDope Torrent Page</title>", None),  # Replacement domain is too unstable in automation flow (intermittent new-tab-page result).
            # ("limetorrents", "https://limetorrents.unblockninja.com/latest100", "<title>Latest 100 torrents - LimeTorrents</title>", None),  # Domain no longer resolves: limetorrents.unblockninja.com
            # ("privatehd", "https://privatehd.to/api/v1/jackett/torrents?in=1&type=0&search=", ("<title>Access denied</title>", "<title>Unauthorized</title>"), None),  # Target behavior changed (auth-gated response without stable anti-bot artifacts).
            # ("torrentcore", "https://torrentcore.xyz/index", "<title>Torrent[CORE] - Torrent community.</title>", None),  # Site appears dead/unusable (returns service unavailable challenge page).
            # ("torrentqq223", "https://torrentqq223.com/torrent/newest.html", "https://torrentqq223.com/ads/", None),  # Domain no longer resolves: torrentqq223.com
            # ("36dm", "https://www.36dm.club/1.html", "https://www.36dm.club/yesterday-1.html", None),  # Domain no longer resolves: www.36dm.club,
            ("erai-raws", "https://www.erai-raws.info/feed/?type=magnet", ("403 Forbidden", "Authentication Required", "<status>403</status>"), None),
            ("teamos", "https://www.teamos.xyz/torrents/?filename=&freeleech=", "<title>Log in | Team OS : Your Only Destination To Custom OS !!</title>", None),
            # ("yts", "https://yts.unblockninja.com/api/v2/list_movies.json?query_term=&limit=50&sort=date_added", '{"movie_count":', None),  # Domain no longer resolves: yts.unblockninja.com,
        ]
        for site_name, site_url, site_text, site_url_pattern in sites_get:
            with self.subTest(msg=site_name):
                res = self.app.post_json("/v1", {"cmd": "request.get", "url": site_url})
                asset_cloudflare_solution(self, res, site_url, site_text, site_url_pattern)

    def test_v1_endpoint_request_post_cloudflare(self):
        sites_post = [
            (
                "nnmclub",
                "https://nnmclub.to/forum/tracker.php",
                "<title>Трекер :: NNM-Club</title>",
                "prev_sd=0&prev_a=0&prev_my=0&prev_n=0&prev_shc=0&prev_shf=1&prev_sha=1&prev_shs=0&prev_shr=0&prev_sht=0&f%5B%5D=-1&o=1&s=2&tm=-1&shf=1&sha=1&ta=-1&sns=-1&sds=-1&nm=&pn=&submit=%CF%EE%E8%F1%EA",
            )
        ]

        for site_name, site_url, site_text, post_data in sites_post:
            with self.subTest(msg=site_name):
                res = self.app.post_json("/v1", {"cmd": "request.post", "url": site_url, "postData": post_data})
                asset_cloudflare_solution(self, res, site_url, site_text)

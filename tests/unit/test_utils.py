import pytest

from flaresolverr import utils


def test_sanitize_user_agent_removes_headless_token():
    ua = "Mozilla/5.0 (...) HeadlessChrome/147.0.0.0 Safari/537.36"
    assert "HeadlessChrome/" not in utils.sanitize_user_agent(ua)
    assert "Chrome/147.0.0.0" in utils.sanitize_user_agent(ua)


def test_sanitize_user_agent_keeps_regular_user_agent():
    ua = "Mozilla/5.0 (...) Chrome/147.0.0.0 Safari/537.36"
    assert utils.sanitize_user_agent(ua) == ua


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/html", False),
        ("text/plain", False),
        ("application/json", False),
        ("application/javascript", False),
        ("application/xml", False),
        ("application/xhtml+xml", False),
        ("application/ld+json", False),
        ("image/jpeg", True),
        ("image/png", True),
        ("application/pdf", True),
        ("application/octet-stream", True),
        ("audio/mpeg", True),
        ("video/mp4", True),
        ("", True),
        (None, True),
    ],
)
def test_is_binary_content_type(content_type, expected):
    assert utils.is_binary_content_type(content_type) is expected

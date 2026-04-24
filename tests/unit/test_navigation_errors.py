import pytest


class _DummyDriver:
    def __init__(self, current_url: str, title: str, page_source: str):
        self.current_url = current_url
        self.title = title
        self.page_source = page_source


def test_raise_if_navigation_error_detects_chrome_net_error():
    from flaresolverr import flaresolverr_service as svc

    driver = _DummyDriver(
        "chrome-error://chromewebdata/",
        "This site can't be reached",
        "<html><body><div id=\"main-frame-error\">ERR_NAME_NOT_RESOLVED</div></body></html>",
    )

    with pytest.raises(Exception, match=r"net::ERR_NAME_NOT_RESOLVED"):
        svc._raise_if_navigation_error(driver)


def test_raise_if_navigation_error_detects_by_page_title():
    from flaresolverr import flaresolverr_service as svc

    for title in ("This site can't be reached", "This page can't be reached"):
        driver = _DummyDriver(
            "https://example.com",
            title,
            '<div class="neterror">ERR_CONNECTION_REFUSED</div>',
        )
        with pytest.raises(Exception, match=r"net::ERR_CONNECTION_REFUSED"):
            svc._raise_if_navigation_error(driver)


def test_raise_if_navigation_error_ignores_regular_pages():
    from flaresolverr import flaresolverr_service as svc

    driver = _DummyDriver(
        "https://example.com",
        "Example Domain",
        "<html><body>Some text mentioning ERR_NOT_A_NETWORK_ERROR.</body></html>",
    )

    svc._raise_if_navigation_error(driver)

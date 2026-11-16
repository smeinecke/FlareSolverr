"""Unit tests for the embedded-Turnstile CDP click solver."""

from unittest.mock import MagicMock

from flaresolverr import turnstile_click as tc


def _iframe_node(backend_id: int, src: str) -> dict:
    return {"nodeName": "IFRAME", "backendNodeId": backend_id, "attributes": ["src", src], "children": []}


def test_find_turnstile_iframes_finds_widget_in_shadow_root():
    doc = {
        "nodeName": "#document",
        "children": [
            {
                "nodeName": "DIV",
                "children": [],
                "shadowRoots": [
                    {
                        "nodeName": "#shadow-root",
                        "children": [
                            _iframe_node(7, "https://challenges.cloudflare.com/turnstile/x"),
                        ],
                    },
                ],
            },
            _iframe_node(9, "https://example.com/embed"),
        ],
    }
    found = []
    tc._find_turnstile_iframes(doc, found)
    assert found == [7]


def test_find_turnstile_iframes_descends_into_content_document():
    doc = {
        "nodeName": "#document",
        "children": [
            {
                "nodeName": "IFRAME",
                "backendNodeId": 3,
                "attributes": ["src", "https://x"],
                "children": [],
                "contentDocument": {
                    "nodeName": "#document",
                    "children": [
                        _iframe_node(11, "https://challenges.cloudflare.com/cdn-cgi/x"),
                    ],
                },
            },
        ],
    }
    found = []
    tc._find_turnstile_iframes(doc, found)
    assert found == [11]


def test_checkbox_position_normal_widget():
    x, y = tc._checkbox_position((10, 20, 310, 85))
    assert 40 - 3 <= x <= 40 + 3  # x0+30 +- jitter
    assert 52.5 - 3 <= y <= 52.5 + 3


def test_checkbox_position_compact_widget():
    x, y = tc._checkbox_position((10, 20, 160, 160))
    assert 40 - 3 <= x <= 40 + 3
    assert 55 - 3 <= y <= 55 + 3


def test_iframe_rect_rejects_tiny_or_missing(monkeypatch):
    driver = MagicMock()
    driver.execute_cdp_cmd.return_value = {"quads": [[0, 0, 50, 0, 50, 20, 0, 20]]}
    assert tc._iframe_rect(driver, 1) is None
    driver.execute_cdp_cmd.return_value = {"quads": []}
    assert tc._iframe_rect(driver, 1) is None
    driver.execute_cdp_cmd.side_effect = Exception("no cdp")
    assert tc._iframe_rect(driver, 1) is None


def test_get_turnstile_response_returns_token_from_js():
    driver = MagicMock()
    driver.execute_script.return_value = "tok123"
    assert tc.get_turnstile_response(driver) == "tok123"
    driver.execute_script.side_effect = Exception("dead")
    assert tc.get_turnstile_response(driver) is None


def test_reset_turnstile_true_when_api_present():
    driver = MagicMock()
    driver.execute_script.return_value = True
    assert tc.reset_turnstile(driver) is True
    driver.execute_script.side_effect = Exception("dead")
    assert tc.reset_turnstile(driver) is False


def test_wait_for_turnstile_times_out_without_widget(monkeypatch):
    monkeypatch.setattr(tc, "_turnstile_iframes", lambda d: [])
    monkeypatch.setattr(tc.time, "sleep", lambda s: None)
    driver = MagicMock()
    assert tc.wait_for_turnstile(driver, timeout=0.01) is False


def test_wait_for_turnstile_finds_widget(monkeypatch):
    monkeypatch.setattr(tc, "_turnstile_iframes", lambda d: [5])
    driver = MagicMock()
    assert tc.wait_for_turnstile(driver, timeout=1) is True


def test_click_turnstile_returns_false_without_cdp():
    driver = MagicMock()
    driver.execute_cdp_cmd.side_effect = NotImplementedError("no cdp")
    assert tc.click_turnstile(driver, ready_timeout=0.1) is False


def test_click_turnstile_clicks_stable_widget(monkeypatch):
    driver = MagicMock()
    rect = (10, 20, 310, 85)
    monkeypatch.setattr(tc, "_visible_turnstile_rect", lambda d: (7, rect))
    monkeypatch.setattr(tc, "_iframe_rect", lambda d, i: rect)
    fake_rng = MagicMock()
    fake_rng.uniform = lambda a, b: (a + b) / 2
    fake_rng.randint = lambda a, b: a
    monkeypatch.setattr(tc, "_rng", fake_rng)
    monkeypatch.setattr(tc.time, "sleep", lambda s: None)
    ticks = iter(range(100))
    monkeypatch.setattr(tc.time, "time", lambda: next(ticks))
    assert tc.click_turnstile(driver, ready_timeout=10) is True
    calls = [c[0][0] for c in driver.execute_cdp_cmd.call_args_list]
    assert "Input.dispatchMouseEvent" in calls

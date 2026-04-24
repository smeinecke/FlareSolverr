from flaresolverr.dtos import ChallengeResolutionT, HealthResponse, IndexResponse, STATUS_OK, V1RequestBase, V1ResponseBase


def test_index_response_maps_fields() -> None:
    response = IndexResponse({"msg": "ready", "version": "1.2.3", "userAgent": "Chrome/123"})

    assert response.msg == "ready"
    assert response.version == "1.2.3"
    assert response.userAgent == "Chrome/123"


def test_health_response_maps_status() -> None:
    response = HealthResponse({"status": STATUS_OK})

    assert response.status == STATUS_OK


def test_v1_response_wraps_solution_dict() -> None:
    response = V1ResponseBase(
        {
            "status": STATUS_OK,
            "message": "Challenge not detected!",
            "solution": {
                "url": "https://example.com",
                "status": 200,
                "headers": [],
                "response": "<html></html>",
                "cookies": [{"name": "cookie", "value": "value"}],
                "userAgent": "Chrome/123",
            },
        }
    )

    assert response.status == STATUS_OK
    assert response.solution is not None
    assert response.solution.url == "https://example.com"
    assert response.solution.status == 200
    assert response.solution.cookies[0]["name"] == "cookie"


def test_v1_request_base_captcha_solver_defaults_to_none() -> None:
    req = V1RequestBase({"cmd": "request.get", "url": "https://example.com"})

    assert req.captchaSolver is None


def test_v1_request_base_captcha_solver_accepts_string() -> None:
    req = V1RequestBase({"cmd": "request.get", "url": "https://example.com", "captchaSolver": "hcaptcha-challenger"})

    assert req.captchaSolver == "hcaptcha-challenger"


def test_v1_request_base_captcha_solver_accepts_default() -> None:
    req = V1RequestBase({"cmd": "request.get", "url": "https://example.com", "captchaSolver": "default"})

    assert req.captchaSolver == "default"


def test_v1_request_base_captcha_solver_not_present_in_empty_request() -> None:
    req = V1RequestBase({})

    assert req.captchaSolver is None


def test_v1_request_base_stealth_accepts_bool() -> None:
    req = V1RequestBase({"cmd": "request.get", "url": "https://example.com", "stealth": True})

    assert req.stealth is True


def test_v1_request_base_stealth_mode_accepts_string() -> None:
    req = V1RequestBase({"cmd": "request.get", "url": "https://example.com", "stealthMode": "csp-safe"})

    assert req.stealthMode == "csp-safe"


def test_v1_request_base_user_agent_accepts_string() -> None:
    req = V1RequestBase({"cmd": "request.get", "url": "https://example.com", "userAgent": "Mozilla/5.0 Test UA"})

    assert req.userAgent == "Mozilla/5.0 Test UA"


def test_challenge_resolution_wraps_nested_result() -> None:
    resolution = ChallengeResolutionT(
        {
            "status": STATUS_OK,
            "message": "Challenge solved!",
            "result": {
                "url": "https://example.com",
                "status": 200,
                "headers": [],
                "response": "ok",
                "cookies": [],
                "userAgent": "Chrome/123",
            },
        }
    )

    assert resolution.status == STATUS_OK
    assert resolution.result is not None
    assert resolution.result.url == "https://example.com"
    assert resolution.result.userAgent == "Chrome/123"

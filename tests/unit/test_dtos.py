from dtos import ChallengeResolutionT, HealthResponse, IndexResponse, STATUS_OK, V1ResponseBase


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

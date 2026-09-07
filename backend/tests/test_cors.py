from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_allowed_origin_is_returned_for_simple_request() -> None:
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


def test_disallowed_origin_is_not_allowed() -> None:
    response = client.get(
        "/health",
        headers={"Origin": "https://malicious.example"},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_solution_post_preflight_is_allowed() -> None:
    response = client.options(
        "/api/solutions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_disallowed_origin_is_rejected_for_solution_preflight() -> None:
    response = client.options(
        "/api/solutions",
        headers={
            "Origin": "https://malicious.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
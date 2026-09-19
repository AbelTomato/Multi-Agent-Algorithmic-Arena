"""匿名评测历史会话 Cookie 与哈希边界测试。"""

import base64
import re

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.middleware.evaluation_session import EvaluationSessionMiddleware
from app.services.evaluation_sessions import (
    EVALUATION_SESSION_COOKIE_NAME,
    EvaluationSession,
    hash_evaluation_session_token,
)


def build_client(*, secure: bool = False) -> TestClient:
    settings = Settings(
        _env_file=None,
        evaluation_history_cookie_secure=secure,
        evaluation_history_retention_days=30,
    )
    application = FastAPI()
    application.add_middleware(EvaluationSessionMiddleware, settings=settings)

    @application.get("/api/evaluations")
    async def evaluations(request: Request) -> dict[str, object]:
        session: EvaluationSession = request.state.evaluation_session
        return {
            "key_hash": session.key_hash,
            "is_new": session.is_new,
            "representation": repr(session),
        }

    @application.get("/api/evaluations/error")
    async def evaluation_error() -> None:
        raise HTTPException(status_code=409, detail="busy")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(application)


def extract_cookie_token(response) -> str:
    cookie = response.cookies.get(EVALUATION_SESSION_COOKIE_NAME)
    assert cookie is not None
    return cookie


def test_new_session_uses_high_entropy_token_stable_sha256_and_redacted_repr() -> None:
    client = build_client()
    response = client.get("/api/evaluations")

    assert response.status_code == 200
    token = extract_cookie_token(response)
    decoded = base64.urlsafe_b64decode(token + "=")
    assert len(decoded) >= 32
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert response.json()["key_hash"] == hash_evaluation_session_token(token)
    assert re.fullmatch(r"[0-9a-f]{64}", response.json()["key_hash"])
    assert token not in response.json()["representation"]
    assert "token=<redacted>" in response.json()["representation"]


@pytest.mark.parametrize(
    "invalid_token",
    ["short", "x" * 44, "invalid+token/with=symbols"],
)
def test_invalid_cookie_is_replaced(invalid_token: str) -> None:
    client = build_client()
    client.cookies.set(EVALUATION_SESSION_COOKIE_NAME, invalid_token)

    response = client.get("/api/evaluations")

    replacement = extract_cookie_token(response)
    assert replacement != invalid_token
    assert response.json()["is_new"] is True
    assert response.json()["key_hash"] == hash_evaluation_session_token(replacement)


def test_cookie_attributes_are_applied_to_success_and_http_exception() -> None:
    for path, expected_status in (("/api/evaluations", 200), ("/api/evaluations/error", 409)):
        response = build_client().get(path)
        header = response.headers["set-cookie"]

        assert response.status_code == expected_status
        assert f"{EVALUATION_SESSION_COOKIE_NAME}=" in header
        assert "HttpOnly" in header
        assert "SameSite=lax" in header
        assert "Path=/api/evaluations" in header
        assert "Max-Age=2592000" in header
        assert "Secure" not in header


def test_secure_cookie_is_configurable_and_valid_cookie_is_not_refreshed() -> None:
    client = build_client(secure=True)
    first = client.get("/api/evaluations")
    token = extract_cookie_token(first)

    assert "Secure" in first.headers["set-cookie"]
    second = client.get(
        "/api/evaluations",
        headers={"Cookie": f"{EVALUATION_SESSION_COOKIE_NAME}={token}"},
    )
    assert second.status_code == 200
    assert second.json()["is_new"] is False
    assert second.json()["key_hash"] == hash_evaluation_session_token(token)
    assert "set-cookie" not in second.headers


def test_non_evaluation_path_does_not_create_session_cookie() -> None:
    response = build_client().get("/health")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
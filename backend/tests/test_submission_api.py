from collections.abc import AsyncGenerator, Iterator
from datetime import datetime, timezone

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, SubjectType
from app.database import Base, get_db
from app.main import app
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.services.submission_evaluations import SubmissionEvaluationService
from app.services.submissions import SubmissionService
from app.auth.dependencies import get_current_subject
from app.api.submissions import get_submission_evaluation_service, get_submission_service


@pytest.fixture
def submission_client(tmp_path) -> Iterator[tuple[TestClient, Account, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'submission-api.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    owner = Account(subject_type=SubjectType.HUMAN, name="api-owner")

    async def setup_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            problem = Problem(
                slug="two-sum",
                title="Two Sum",
                description="description",
                allowed_languages=["python"],
            )
            session.add_all([owner, problem])
            await session.flush()
            session.add(ProblemSubmissionPermission(account_id=owner.id, problem_id=problem.id))
            await session.commit()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    import asyncio

    asyncio.run(setup_database())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_subject] = lambda: owner

    async def override_submission_service(
        session: AsyncSession = Depends(get_db),
    ) -> SubmissionService:
        return SubmissionService(session)

    async def override_submission_evaluation_service(
        session: AsyncSession = Depends(get_db),
    ) -> SubmissionEvaluationService:
        return SubmissionEvaluationService(session)

    app.dependency_overrides[get_submission_service] = override_submission_service
    app.dependency_overrides[get_submission_evaluation_service] = override_submission_evaluation_service
    try:
        yield TestClient(app), owner, session_factory
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_new_submission_api_requires_bearer_auth() -> None:
    response = TestClient(app).post(
        "/api/submissions",
        json={"problem_id": 1, "language": "python", "source": "print(1)"},
    )

    assert response.status_code == 401


def test_submission_api_creates_reads_revises_and_evaluates(submission_client) -> None:
    client, _, _ = submission_client

    created = client.post(
        "/api/submissions",
        json={"problem_id": 1, "language": "python", "source": "print(1)"},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["language"] == "python"
    assert payload["runtime_id"] == "python-3.11-v1"
    assert payload["source_sha256"]
    assert payload["replayable"] is True
    submission_id = payload["submission_id"]

    detail = client.get(f"/api/submissions/{submission_id}")
    assert detail.status_code == 200
    assert detail.json()["source"] == "print(1)"

    revised = client.post(
        f"/api/submissions/{submission_id}/revisions",
        json={"problem_id": 1, "language": "python", "source": "print(2)"},
    )
    assert revised.status_code == 201
    assert revised.json()["supersedes_submission_id"] == submission_id

    evaluation = client.post(f"/api/submissions/{submission_id}/evaluations")
    assert evaluation.status_code == 503


def test_legacy_anonymous_evaluation_creation_is_removed(submission_client) -> None:
    client, _, _ = submission_client

    response = client.post("/api/evaluations", json={"problem_id": 1})

    assert response.status_code == 405
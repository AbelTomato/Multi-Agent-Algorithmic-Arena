"""阶段 3 FastAPI → Judge → Go 控制器真实评测集成测试。"""

import asyncio
import os
from collections.abc import AsyncGenerator, Iterator

from fastapi import Depends
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.submissions import get_submission_evaluation_service
from app.auth.dependencies import get_current_subject
from app.auth.models import Account, SubjectType
from app.config import Settings
from app.database import Base, get_db
from app.main import app
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.services.submission_evaluations import SubmissionEvaluationService


controller_required = pytest.mark.skipif(
    os.getenv("ARENA_SANDBOX_INTEGRATION") != "1",
    reason="需要设置 ARENA_SANDBOX_INTEGRATION=1 并启动 Go 执行控制器",
)


CORRECT_TWO_SUM_CODE = '''import json
import sys

data = json.loads(sys.stdin.read())
seen = {}
for index, number in enumerate(data["nums"]):
    complement = data["target"] - number
    if complement in seen:
        print(json.dumps({"indices": [seen[complement], index]}))
        break
    seen[number] = index
'''


@pytest.fixture
def database_client(tmp_path) -> Iterator[tuple[TestClient, Account, async_sessionmaker]]:
    database_path = tmp_path / "evaluation_flow.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    subject = Account(subject_type=SubjectType.AGENT, name="real-evaluation-agent")

    async def setup_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            problem = Problem(
                slug="two-sum",
                title="Two Sum",
                description="# Two Sum\nFind two numbers whose sum equals target.",
                allowed_languages=["python"],
                active_case_version="v1",
            )
            session.add_all([subject, problem])
            await session.flush()
            session.add(ProblemSubmissionPermission(account_id=subject.id, problem_id=problem.id))
            await session.commit()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    asyncio.run(setup_database())
    app.dependency_overrides[get_db] = override_get_db

    async def override_submission_evaluation_service(
        session: AsyncSession = Depends(get_db),
    ) -> SubmissionEvaluationService:
        return SubmissionEvaluationService(
            session,
            settings=Settings(
                _env_file=None,
                sandbox_controller_url="http://127.0.0.1:8001",
                sandbox_controller_timeout_seconds=10,
            ),
        )

    app.dependency_overrides[get_current_subject] = lambda: subject
    app.dependency_overrides[get_submission_evaluation_service] = override_submission_evaluation_service
    try:
        yield TestClient(app), subject, session_factory
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@controller_required
def test_submission_evaluation_api_runs_real_candidate_through_go_controller(
    database_client,
) -> None:
    client, _, _ = database_client

    submission_response = client.post(
        "/api/submissions",
        json={"problem_id": 1, "language": "python", "source": CORRECT_TWO_SUM_CODE},
    )

    assert submission_response.status_code == 201
    submission_id = submission_response.json()["submission_id"]

    response = client.post(f"/api/submissions/{submission_id}/evaluations")

    assert response.status_code == 200
    payload = response.json()
    assert {key: payload[key] for key in (
        "submission_id", "language", "runtime_id", "case_version", "judge_status",
        "case_count", "executed_count", "passed_count", "failed_case_index", "summary",
    )} == {
        "submission_id": submission_id,
        "language": "python",
        "runtime_id": "python-3.11-v1",
        "case_version": "v1",
        "judge_status": "AC",
        "case_count": 9,
        "executed_count": 9,
        "passed_count": 9,
        "failed_case_index": None,
        "summary": "通过当前版本评测用例",
    }
    assert "CORRECT_TWO_SUM_CODE" not in response.text


def test_legacy_anonymous_creation_is_removed_from_isolated_evaluation_flow(database_client) -> None:
    client, _, _ = database_client

    response = client.post("/api/evaluations", json={"problem_id": 1})
    assert response.status_code == 405

    listing = client.get("/api/evaluations?problem_id=1").json()
    assert listing["total"] == 0
    other = TestClient(app)
    assert other.get("/api/evaluations").json()["items"] == []
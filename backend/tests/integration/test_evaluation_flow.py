"""阶段 3 FastAPI → Judge → Go 控制器真实评测集成测试。"""

import asyncio
import json
import os
from collections.abc import AsyncGenerator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.factory import get_agent
from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models.problem import Problem
from app.models.evaluation_run import EvaluationRun
from app.judges.base import JudgeResult
from app.services.evaluations import EvaluationService


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


class FixedEvaluationAgent:
    """测试专用固定 Agent，不访问 Provider。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(
            {
                "language": "python",
                "code": CORRECT_TWO_SUM_CODE,
                "explanation": "哈希表记录已遍历元素。",
            }
        )


@pytest.fixture
def database_client(tmp_path) -> Iterator[tuple[TestClient, FixedEvaluationAgent, async_sessionmaker]]:
    database_path = tmp_path / "evaluation_flow.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    agent = FixedEvaluationAgent()

    async def setup_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(
                Problem(
                    slug="two-sum",
                    title="Two Sum",
                    description="# Two Sum\nFind two numbers whose sum equals target.",
                )
            )
            await session.commit()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    asyncio.run(setup_database())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_agent] = lambda: agent
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        evaluation_enabled=True,
        sandbox_controller_url="http://127.0.0.1:8001",
        sandbox_controller_timeout_seconds=10,
        evaluation_total_timeout_seconds=210,
    )
    try:
        yield TestClient(app), agent, session_factory
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@controller_required
def test_evaluation_api_runs_fixed_agent_through_go_controller_without_hidden_data_leaks(
    database_client,
) -> None:
    client, agent, _ = database_client

    response = client.post("/api/evaluations", json={"problem_id": 1})

    assert response.status_code == 200
    payload = response.json()
    assert {key: payload[key] for key in (
        "problem_id", "problem_slug", "language", "status", "case_version",
        "case_count", "executed_count", "passed_count", "failed_case_index", "summary",
    )} == {
        "problem_id": 1,
        "problem_slug": "two-sum",
        "language": "python",
        "status": "AC",
        "case_version": "v1",
        "case_count": 9,
        "executed_count": 9,
        "passed_count": 9,
        "failed_case_index": None,
        "summary": "通过当前版本评测用例",
    }
    assert len(agent.prompts) == 1
    assert "-1000000000" not in agent.prompts[0]
    assert "hidden_cases" not in agent.prompts[0]
    assert "CORRECT_TWO_SUM_CODE" not in response.text
    assert payload["run_status"] == "SUCCEEDED"
    assert client.get("/api/evaluations").json()["total"] == 1
    assert client.get(f"/api/evaluations/{payload['evaluation_id']}").json()["judge_status"] == "AC"


def test_legacy_anonymous_creation_is_removed_from_isolated_evaluation_flow(database_client) -> None:
    client, _, _ = database_client

    response = client.post("/api/evaluations", json={"problem_id": 1})
    assert response.status_code == 405

    listing = client.get("/api/evaluations?problem_id=1").json()
    assert listing["total"] == 0
    other = TestClient(app)
    assert other.get("/api/evaluations").json()["items"] == []
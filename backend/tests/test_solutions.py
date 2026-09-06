from collections.abc import AsyncGenerator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.factory import get_agent
from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models.problem import Problem


class RecordingAgent:
    def __init__(self, results: list[str] | None = None, error: Exception | None = None) -> None:
        self.prompts: list[str] = []
        self.results = results or ["## 解题思路\nmock result"]
        self.error = error

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.results.pop(0)


@pytest.fixture
def database_client(tmp_path) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    database_path = tmp_path / "solutions_api.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def setup_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(
                Problem(
                    slug="two-sum",
                    title="Two Sum",
                    description="# Two Sum\nFind two numbers.",
                )
            )
            await session.commit()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    import asyncio

    asyncio.run(setup_database())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def use_agent(agent: RecordingAgent) -> None:
    app.dependency_overrides[get_agent] = lambda: agent


def test_create_solution_returns_agent_result(
    database_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = database_client
    agent = RecordingAgent(results=["## 解题思路\nanswer"])
    use_agent(agent)

    response = client.post("/api/solutions", json={"problem_id": 1})

    assert response.status_code == 200
    assert response.json() == {
        "problem_id": 1,
        "result": "## 解题思路\nanswer",
        "language": "python",
    }
    assert len(agent.prompts) == 1
    assert "Two Sum" in agent.prompts[0]
    assert "固定使用 Python" in agent.prompts[0]


def test_create_solution_returns_404_without_calling_agent(
    database_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = database_client
    agent = RecordingAgent()
    use_agent(agent)

    response = client.post("/api/solutions", json={"problem_id": 999})

    assert response.status_code == 404
    assert response.json() == {"detail": "Problem not found"}
    assert agent.prompts == []


def test_create_solution_retries_once_after_agent_failure(
    database_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = database_client

    class FailOnceAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, prompt: str) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary provider failure")
            return "successful result"

    agent = FailOnceAgent()
    use_agent(agent)

    response = client.post("/api/solutions", json={"problem_id": 1})

    assert response.status_code == 200
    assert response.json()["result"] == "successful result"
    assert agent.calls == 2


def test_create_solution_uses_configured_retry_count(
    database_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = database_client

    class FailTwiceAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, prompt: str) -> str:
            self.calls += 1
            if self.calls <= 2:
                raise RuntimeError("temporary provider failure")
            return "successful result"

    agent = FailTwiceAgent()
    use_agent(agent)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, agent_retry_count=2)

    response = client.post("/api/solutions", json={"problem_id": 1})

    assert response.status_code == 200
    assert response.json()["result"] == "successful result"
    assert agent.calls == 3


def test_create_solution_returns_sanitized_error_after_two_failures(
    database_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = database_client
    agent = RecordingAgent(error=RuntimeError("secret provider details"))
    use_agent(agent)

    response = client.post("/api/solutions", json={"problem_id": 1})

    assert response.status_code == 502
    assert response.json() == {"detail": "Agent failed to generate a solution"}
    assert "secret provider details" not in response.text
    assert len(agent.prompts) == 2


def test_create_solution_rejects_client_prompt_and_invalid_problem_id(
    database_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = database_client

    extra_field_response = client.post(
        "/api/solutions",
        json={"problem_id": 1, "prompt": "client controlled prompt"},
    )
    invalid_id_response = client.post("/api/solutions", json={"problem_id": 0})

    assert extra_field_response.status_code == 422
    assert invalid_id_response.status_code == 422
from collections.abc import AsyncGenerator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models.problem import Problem


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    database_path = tmp_path / "problems_api.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def setup_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add_all(
                [
                    Problem(slug="two-sum", title="Two Sum", description="# Two Sum"),
                    Problem(
                        slug="valid-parentheses",
                        title="Valid Parentheses",
                        description="# Valid Parentheses",
                    ),
                ]
            )
            await session.commit()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    import asyncio

    asyncio.run(setup_database())
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_api_get_problems_returns_summaries(client: TestClient) -> None:
    response = client.get("/api/problems")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "slug": "two-sum", "title": "Two Sum"},
        {"id": 2, "slug": "valid-parentheses", "title": "Valid Parentheses"},
    ]


def test_api_get_problem_returns_detail(client: TestClient) -> None:
    response = client.get("/api/problems/1")

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "slug": "two-sum",
        "title": "Two Sum",
        "description": "# Two Sum",
    }


def test_api_get_problem_returns_404_for_unknown_problem(client: TestClient) -> None:
    response = client.get("/api/problems/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Problem not found"}
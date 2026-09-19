import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run PostgreSQL migration/seed integration tests",
)
async def test_postgres_connection_has_problems_table_after_migration() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )
        assert "problems" in table_names
        assert "evaluation_runs" in table_names
        columns = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_columns("evaluation_runs")
        )
        names = {column["name"] for column in columns}
        assert {"id", "session_key_hash", "run_status", "created_at"} <= names
        assert not {"code", "prompt", "stdout", "stderr", "hidden_cases"} & names
        result = await connection.execute(text("select count(*) from problems"))
        assert result.scalar_one() >= 0
    await engine.dispose()
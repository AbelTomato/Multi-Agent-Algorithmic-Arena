"""评测运行记录 ORM 的字段、约束与索引契约测试。"""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.evaluation_run import EvaluationRun, EvaluationRunStatus
from app.models.problem import Problem


SESSION_HASH = "a" * 64
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 9, 19, 2, 30, tzinfo=timezone.utc)


@pytest.fixture
async def session(tmp_path) -> AsyncSession:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evaluation-run.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as database_session:
        database_session.add(
            Problem(id=1, slug="two-sum", title="Two Sum", description="Find two numbers")
        )
        await database_session.commit()
        yield database_session
    await engine.dispose()


def running_record(**overrides: object) -> EvaluationRun:
    values: dict[str, object] = {
        "id": RUN_ID,
        "session_key_hash": SESSION_HASH,
        "problem_id": 1,
        "problem_slug": "two-sum",
        "language": "python",
        "run_status": EvaluationRunStatus.RUNNING.value,
        "judge_status": None,
        "case_version": "v1",
        "case_count": 9,
        "executed_count": None,
        "passed_count": None,
        "failed_case_index": None,
        "summary": None,
        "error_category": None,
        "created_at": NOW,
        "started_at": NOW,
        "finished_at": None,
        "duration_ms": None,
    }
    values.update(overrides)
    return EvaluationRun(**values)


async def assert_integrity_error(session: AsyncSession, record: EvaluationRun) -> None:
    session.add(record)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_saves_running_and_complete_succeeded_records(session: AsyncSession) -> None:
    running = running_record()
    session.add(running)
    await session.commit()

    saved = await session.get(EvaluationRun, RUN_ID)
    assert saved is not None
    assert saved.run_status == EvaluationRunStatus.RUNNING.value
    assert saved.created_at.tzinfo is not None
    assert saved.finished_at is None

    succeeded_id = UUID("22222222-2222-4222-8222-222222222222")
    succeeded = running_record(
        id=succeeded_id,
        run_status=EvaluationRunStatus.SUCCEEDED.value,
        judge_status="AC",
        executed_count=9,
        passed_count=9,
        summary="通过当前版本评测用例",
        finished_at=NOW,
        duration_ms=1234,
    )
    session.add(succeeded)
    await session.commit()

    result = (await session.execute(select(EvaluationRun).where(EvaluationRun.id == succeeded_id))).scalar_one()
    assert result.judge_status == "AC"
    assert result.duration_ms == 1234


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_status": "AC"},
        {"case_count": -1},
        {"executed_count": -1},
        {"passed_count": -1},
        {"failed_case_index": -1},
        {"duration_ms": -1},
        {
            "run_status": EvaluationRunStatus.SUCCEEDED.value,
            "judge_status": None,
            "executed_count": 9,
            "passed_count": 9,
            "summary": "通过当前版本评测用例",
            "finished_at": NOW,
            "duration_ms": 1,
        },
    ],
)
async def test_rejects_invalid_states_counts_and_incomplete_success(
    session: AsyncSession,
    overrides: dict[str, object],
) -> None:
    await assert_integrity_error(session, running_record(**overrides))


async def test_declares_expected_indexes_and_no_sensitive_columns(session: AsyncSession) -> None:
    bind = session.get_bind()
    indexes = await session.run_sync(lambda sync_session: inspect(sync_session.bind).get_indexes("evaluation_runs"))
    indexed_columns = {tuple(index["column_names"]) for index in indexes}

    assert ("session_key_hash",) in indexed_columns
    assert ("session_key_hash", "created_at", "id") in indexed_columns
    assert ("session_key_hash", "problem_id", "created_at", "id") in indexed_columns

    columns = set(EvaluationRun.__table__.columns.keys())
    assert not columns.intersection(
        {
            "code",
            "candidate_code",
            "prompt",
            "provider_response",
            "api_key",
            "stdin",
            "stdout",
            "stderr",
            "hidden_cases",
            "container_id",
            "controller_task_id",
            "internal_error",
        }
    )
    assert bind is not None
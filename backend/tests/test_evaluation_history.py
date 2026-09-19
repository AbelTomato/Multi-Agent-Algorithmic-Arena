"""评测运行 repository 的状态机、隔离、保留和恢复测试。"""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.judges.base import EvaluationStatus, JudgeResult
from app.models.evaluation_run import (
    EvaluationErrorCategory,
    EvaluationRun,
    EvaluationRunStatus,
)
from app.models.problem import Problem
from app.services.evaluation_sessions import hash_evaluation_session_token
from app.services.evaluation_runs import EvaluationRunRepository, SAFE_ERROR_SUMMARIES
from app.api.evaluations import get_evaluation_run_repository
from app.config import Settings, get_settings
from app.database import get_db
from app.main import app, recover_stale_evaluation_runs
from app.maintenance.evaluation_history import cleanup_expired_runs


NOW = datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc)
SESSION_A = "a" * 64
SESSION_B = "b" * 64


@pytest.fixture
async def session_factory(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                Problem(id=1, slug="two-sum", title="Two Sum", description="Two Sum"),
                Problem(id=2, slug="valid-parentheses", title="Valid", description="Valid"),
            ]
        )
        await session.commit()
    yield factory
    await engine.dispose()


def result(status: EvaluationStatus = EvaluationStatus.AC) -> JudgeResult:
    return JudgeResult(
        problem_id=1,
        problem_slug="two-sum",
        language="python",
        status=status,
        case_version="v1",
        case_count=2,
        executed_count=2,
        passed_count=2 if status == EvaluationStatus.AC else 1,
        failed_case_index=None if status == EvaluationStatus.AC else 1,
        summary="通过当前版本评测用例" if status == EvaluationStatus.AC else "第 2 个用例答案错误",
    )


async def create_run(
    factory: async_sessionmaker[AsyncSession],
    *,
    session_hash: str = SESSION_A,
    problem_id: int = 1,
    created_at: datetime = NOW,
) -> EvaluationRun:
    async with factory() as session:
        problem = await session.get(Problem, problem_id)
        assert problem is not None
        repository = EvaluationRunRepository(session, clock=lambda: created_at)
        return await repository.create_running(
            session_hash,
            problem,
            "v1",
            2,
        )


async def test_create_running_commits_before_external_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run = await create_run(session_factory)

    async with session_factory() as new_session:
        saved = await new_session.get(EvaluationRun, run.id)
        assert saved is not None
        assert saved.run_status == EvaluationRunStatus.RUNNING.value
        assert saved.created_at == NOW


async def test_success_transition_is_atomic_and_terminal_is_immutable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run = await create_run(session_factory)
    async with session_factory() as session:
        repository = EvaluationRunRepository(session)
        assert await repository.mark_succeeded(run.id, result(), NOW + timedelta(seconds=2), 2000)
        assert not await repository.mark_failed(
            run.id,
            EvaluationRunStatus.FAILED,
            EvaluationErrorCategory.INTERNAL_ERROR,
            "raw secret exception",
            NOW + timedelta(seconds=3),
            3000,
        )
        await session.commit()

    async with session_factory() as session:
        saved = await session.get(EvaluationRun, run.id)
        assert saved is not None
        assert saved.run_status == EvaluationRunStatus.SUCCEEDED.value
        assert saved.judge_status == EvaluationStatus.AC.value
        assert saved.summary == "通过当前版本评测用例"
        assert saved.duration_ms == 2000
        assert saved.error_category is None


@pytest.mark.parametrize(
    ("run_status", "category"),
    [
        (EvaluationRunStatus.FAILED, EvaluationErrorCategory.AGENT_ERROR),
        (EvaluationRunStatus.REJECTED, EvaluationErrorCategory.CONTROLLER_BUSY),
        (EvaluationRunStatus.FAILED, EvaluationErrorCategory.CONTROLLER_UNAVAILABLE),
        (EvaluationRunStatus.TIMED_OUT, EvaluationErrorCategory.CONTROLLER_TIMEOUT),
        (EvaluationRunStatus.FAILED, EvaluationErrorCategory.CONTROLLER_RESPONSE_ERROR),
        (EvaluationRunStatus.TIMED_OUT, EvaluationErrorCategory.EVALUATION_TIMEOUT),
        (EvaluationRunStatus.FAILED, EvaluationErrorCategory.INTERNAL_ERROR),
    ],
)
async def test_failure_categories_use_fixed_safe_summaries(
    session_factory: async_sessionmaker[AsyncSession],
    run_status: EvaluationRunStatus,
    category: EvaluationErrorCategory,
) -> None:
    run = await create_run(session_factory)
    async with session_factory() as session:
        changed = await EvaluationRunRepository(session).mark_failed(
            run.id,
            run_status,
            category,
            "provider raw exception with secret candidate source",
            NOW + timedelta(seconds=1),
            1000,
        )
        assert changed
        await session.commit()
    async with session_factory() as session:
        saved = await session.get(EvaluationRun, run.id)
        assert saved is not None
        assert saved.summary == SAFE_ERROR_SUMMARIES[category]
        assert "secret" not in saved.summary
        assert saved.judge_status is None


async def test_list_and_detail_are_session_scoped_filtered_paginated_and_retained(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old = await create_run(session_factory, created_at=NOW - timedelta(days=31))
    first = await create_run(session_factory, problem_id=1, created_at=NOW - timedelta(minutes=2))
    second = await create_run(session_factory, problem_id=2, created_at=NOW - timedelta(minutes=1))
    foreign = await create_run(session_factory, session_hash=SESSION_B, created_at=NOW)
    cutoff = NOW - timedelta(days=30)

    async with session_factory() as session:
        repository = EvaluationRunRepository(session)
        items, total = await repository.list_for_session(SESSION_A, cutoff, None, 1, 0)
        filtered, filtered_total = await repository.list_for_session(SESSION_A, cutoff, 1, 20, 0)

        assert total == 2
        assert [item.id for item in items] == [second.id]
        assert filtered_total == 1
        assert [item.id for item in filtered] == [first.id]
        assert await repository.get_for_session(first.id, SESSION_A, cutoff) is not None
        assert await repository.get_for_session(foreign.id, SESSION_A, cutoff) is None
        assert await repository.get_for_session(old.id, SESSION_A, cutoff) is None


async def test_interrupts_only_stale_running_and_cleanup_deletes_only_old_terminal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stale = await create_run(session_factory, created_at=NOW - timedelta(minutes=20))
    fresh = await create_run(session_factory, created_at=NOW - timedelta(minutes=2))
    terminal = await create_run(session_factory, created_at=NOW - timedelta(days=40))
    old_running = await create_run(session_factory, created_at=NOW - timedelta(days=40))
    async with session_factory() as session:
        repository = EvaluationRunRepository(session)
        await repository.mark_failed(
            terminal.id,
            EvaluationRunStatus.FAILED,
            EvaluationErrorCategory.INTERNAL_ERROR,
            "ignored",
            NOW - timedelta(days=39),
            100,
        )
        await session.commit()

    async with session_factory() as session:
        repository = EvaluationRunRepository(session, clock=lambda: NOW)
        assert await repository.interrupt_stale_runs(NOW - timedelta(minutes=10)) == 2
        await session.commit()

    async with session_factory() as session:
        stale_saved = await session.get(EvaluationRun, stale.id)
        fresh_saved = await session.get(EvaluationRun, fresh.id)
        assert stale_saved is not None and stale_saved.run_status == EvaluationRunStatus.INTERRUPTED.value
        assert stale_saved.summary == "评测服务重启，运行已中断"
        assert fresh_saved is not None and fresh_saved.run_status == EvaluationRunStatus.RUNNING.value

        deleted = await EvaluationRunRepository(session).delete_expired_runs(NOW - timedelta(days=30))
        assert deleted == 2
        await session.commit()
        remaining = await session.scalar(select(func.count()).select_from(EvaluationRun))
        assert remaining == 2
        assert await session.get(EvaluationRun, old_running.id) is None
        assert await session.get(EvaluationRun, terminal.id) is None
        assert await session.get(EvaluationRun, fresh.id) is not None


@pytest.fixture
def history_api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[tuple[TestClient, async_sessionmaker[AsyncSession]], None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        evaluation_history_retention_days=30,
    )
    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()


def test_history_api_is_cookie_scoped_filtered_paginated_and_returns_uniform_404(
    history_api_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = history_api_client
    first_response = client.get("/api/evaluations?problem_id=1&limit=1&offset=0")
    assert first_response.status_code == 200
    assert "arena_evaluation_session=" in first_response.headers["set-cookie"]
    token = first_response.cookies["arena_evaluation_session"]

    async def seed() -> EvaluationRun:
        async with factory() as session:
            problem = await session.get(Problem, 1)
            assert problem is not None
            run = await EvaluationRunRepository(session).create_running(
                hash_evaluation_session_token(token),
                problem,
                "v1",
                2,
            )
            await EvaluationRunRepository(session).mark_succeeded(run.id, result(), NOW, 10)
            await session.commit()
            return run

    run = asyncio.run(seed())
    response = client.get("/api/evaluations?problem_id=1&limit=1&offset=0")
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["evaluation_id"] == str(run.id)
    assert response.json()["items"][0]["run_status"] == "SUCCEEDED"

    detail = client.get(f"/api/evaluations/{run.id}")
    assert detail.status_code == 200
    assert detail.json()["evaluation_id"] == str(run.id)

    other = TestClient(app)
    assert other.get("/api/evaluations").json()["items"] == []
    assert other.get(f"/api/evaluations/{run.id}").status_code == 404
    assert client.get(f"/api/evaluations/{uuid4()}").status_code == 404
    assert client.get("/api/evaluations/not-a-uuid").status_code == 422
    assert client.get("/api/evaluations?limit=51").status_code == 422
    assert client.get("/api/evaluations?offset=-1").status_code == 422
    assert client.get("/api/evaluations?problem_id=0").status_code == 422


async def test_startup_recovery_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stale = await create_run(session_factory, created_at=NOW - timedelta(minutes=20))
    settings = Settings(_env_file=None, evaluation_running_stale_minutes=10)

    assert await recover_stale_evaluation_runs(
        session_factory,
        settings,
        now=NOW,
    ) == 1
    assert await recover_stale_evaluation_runs(
        session_factory,
        settings,
        now=NOW,
    ) == 0
    async with session_factory() as session:
        saved = await session.get(EvaluationRun, stale.id)
        assert saved is not None
        assert saved.run_status == EvaluationRunStatus.INTERRUPTED.value


async def test_cleanup_defaults_to_dry_run_and_execute_only_deletes_old_terminal_runs(
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    old_terminal = await create_run(session_factory, created_at=NOW - timedelta(days=40))
    old_running = await create_run(session_factory, created_at=NOW - timedelta(days=40))
    fresh_terminal = await create_run(session_factory, created_at=NOW - timedelta(days=2))

    async with session_factory() as session:
        repository = EvaluationRunRepository(session)
        assert await repository.mark_succeeded(old_terminal.id, result(), NOW, 10)
        assert await repository.mark_succeeded(fresh_terminal.id, result(), NOW, 10)
        await session.commit()

    dry_run_count = await cleanup_expired_runs(
        session_factory,
        retention_days=30,
        execute=False,
        now=NOW,
    )
    assert dry_run_count == 1
    dry_run_output = capsys.readouterr().out
    assert "mode=dry-run" in dry_run_output
    assert "count=1" in dry_run_output
    assert "2026-08-20T04:00:00+00:00" in dry_run_output
    for sensitive_value in (str(old_terminal.id), SESSION_A, "two-sum", "通过当前版本评测用例"):
        assert sensitive_value not in dry_run_output

    async with session_factory() as session:
        assert await session.get(EvaluationRun, old_terminal.id) is not None
        assert await session.get(EvaluationRun, old_running.id) is not None
        assert await session.get(EvaluationRun, fresh_terminal.id) is not None

    execute_count = await cleanup_expired_runs(
        session_factory,
        retention_days=30,
        execute=True,
        now=NOW,
    )
    assert execute_count == 1
    execute_output = capsys.readouterr().out
    assert "mode=execute" in execute_output
    assert "count=1" in execute_output

    async with session_factory() as session:
        assert await session.get(EvaluationRun, old_terminal.id) is None
        assert await session.get(EvaluationRun, old_running.id) is not None
        assert await session.get(EvaluationRun, fresh_terminal.id) is not None


def test_cleanup_rejects_non_positive_retention_days() -> None:
    from app.maintenance.evaluation_history import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--retention-days", "0"])
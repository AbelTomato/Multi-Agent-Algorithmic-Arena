from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, SubjectType
from app.database import Base
from app.models.problem import Problem
from app.models.evaluation import Evaluation
from app.models.submission import Submission
from app.maintenance.submissions import cleanup_expired_submission_sources
from app.services.submissions import (
    SubmissionConflictError,
    SubmissionForbiddenError,
    SubmissionValidationError,
    SubmissionService,
)


@pytest.fixture
async def submission_database(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'submissions.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


async def _create_context(session: AsyncSession) -> tuple[Account, Account, Problem]:
    human = Account(subject_type=SubjectType.HUMAN, name="alice")
    agent = Account(subject_type=SubjectType.AGENT, name="solver")
    problem = Problem(
        slug="two-sum",
        title="Two Sum",
        description="description",
        allowed_languages=["python", "cpp"],
    )
    session.add_all([human, agent, problem])
    await session.flush()
    from app.models.permission import ProblemSubmissionPermission

    session.add_all(
        [
            ProblemSubmissionPermission(account_id=human.id, problem_id=problem.id),
            ProblemSubmissionPermission(account_id=agent.id, problem_id=problem.id),
        ]
    )
    await session.commit()
    return human, agent, problem


@pytest.mark.asyncio
async def test_human_and_agent_create_owned_submissions_with_fixed_runtime(submission_database) -> None:
    async with submission_database() as session:
        human, agent, problem = await _create_context(session)
        service = SubmissionService(session)

        human_submission = await service.create(
            human,
            problem_id=problem.id,
            language="python",
            source="print('human')\n",
        )
        agent_submission = await service.create(
            agent,
            problem_id=problem.id,
            language="cpp",
            source="#include <iostream>\n",
        )
        await session.commit()

        assert human_submission.author_subject_id == human.id
        assert agent_submission.author_subject_id == agent.id
        assert human_submission.runtime_id == "python-3.11-v1"
        assert agent_submission.runtime_id == "cpp-gcc-14-cpp20-v1"
        assert human_submission.source_sha256 == sha256(
            human_submission.source.encode("utf-8")
        ).hexdigest()
        assert human_submission.retention_expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_submission_rejects_missing_permission_and_client_runtime_fields(submission_database) -> None:
    async with submission_database() as session:
        owner, _, problem = await _create_context(session)
        unauthorized = Account(subject_type=SubjectType.HUMAN, name="unauthorized")
        session.add(unauthorized)
        await session.flush()
        service = SubmissionService(session)

        with pytest.raises(SubmissionForbiddenError):
            await service.create(unauthorized, problem_id=problem.id, language="python", source="x")
        with pytest.raises(SubmissionValidationError):
            await service.create(
                owner,
                problem_id=problem.id,
                language="python",
                source="x",
                runtime_id="attacker-runtime",
            )


@pytest.mark.asyncio
async def test_submission_rejects_invalid_source_language_and_revision(submission_database) -> None:
    async with submission_database() as session:
        owner, _, problem = await _create_context(session)
        service = SubmissionService(session)

        with pytest.raises(SubmissionValidationError):
            await service.create(owner, problem_id=problem.id, language="python", source="")
        with pytest.raises(SubmissionValidationError):
            await service.create(owner, problem_id=problem.id, language="python", source="😀" * 20000)
        with pytest.raises(SubmissionValidationError):
            await service.create(owner, problem_id=problem.id, language="javascript", source="x")

        submission = await service.create(
            owner,
            problem_id=problem.id,
            language="python",
            source="print(1)",
        )
        with pytest.raises(SubmissionConflictError):
            await service.revise(owner, submission.id, problem_id=999, language="python", source="print(2)")


@pytest.mark.asyncio
async def test_revision_creates_new_immutable_submission(submission_database) -> None:
    async with submission_database() as session:
        owner, _, problem = await _create_context(session)
        service = SubmissionService(session)
        original = await service.create(
            owner,
            problem_id=problem.id,
            language="python",
            source="print(1)",
        )
        revised = await service.revise(
            owner,
            original.id,
            problem_id=problem.id,
            language="python",
            source="print(2)",
        )
        await session.commit()

        assert revised.id != original.id
        assert revised.supersedes_submission_id == original.id
        assert original.source == "print(1)"
        assert original.source_sha256 == sha256(b"print(1)").hexdigest()
        assert revised.source == "print(2)"
        assert await session.scalar(select(func.count()).select_from(Submission)) == 2


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired_sources_and_keeps_evaluation_summary(submission_database) -> None:
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    async with submission_database() as session:
        owner, other, problem = await _create_context(session)
        service = SubmissionService(session, now=lambda: now - timedelta(days=100))
        expired = await service.create(
            owner,
            problem_id=problem.id,
            language="python",
            source="print('expired')",
        )
        fresh = await SubmissionService(session, now=lambda: now).create(
            owner,
            problem_id=problem.id,
            language="python",
            source="print('fresh')",
        )
        other_submission = await SubmissionService(session, now=lambda: now - timedelta(days=100)).create(
            other,
            problem_id=problem.id,
            language="python",
            source="print('other')",
        )
        evaluation = Evaluation(
            submission_id=expired.id,
            source_sha256=expired.source_sha256,
            language=expired.language,
            runtime_id=expired.runtime_id,
            case_version="v1",
            judge_status="AC",
            case_count=1,
            executed_count=1,
            passed_count=1,
            summary="passed",
            created_at=now - timedelta(days=90),
            finished_at=now - timedelta(days=90),
        )
        session.add(evaluation)
        await session.commit()

    assert await cleanup_expired_submission_sources(
        submission_database,
        now=now,
        execute=False,
    ) == 2
    async with submission_database() as session:
        assert (await session.get(Submission, expired.id)).source == "print('expired')"
        assert (await session.get(Submission, other_submission.id)).source == "print('other')"

    assert await cleanup_expired_submission_sources(
        submission_database,
        now=now,
        execute=True,
    ) == 2
    async with submission_database() as session:
        expired_saved = await session.get(Submission, expired.id)
        fresh_saved = await session.get(Submission, fresh.id)
        other_saved = await session.get(Submission, other_submission.id)
        saved_evaluation = await session.get(Evaluation, evaluation.id)

        assert expired_saved is not None
        assert expired_saved.source is None
        assert expired_saved.source_deleted_at.replace(tzinfo=timezone.utc) == now
        assert fresh_saved is not None and fresh_saved.source == "print('fresh')"
        assert other_saved is not None and other_saved.source is None
        assert saved_evaluation is not None and saved_evaluation.summary == "passed"

    assert await cleanup_expired_submission_sources(
        submission_database,
        now=now,
        execute=True,
    ) == 0
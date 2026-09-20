from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, SubjectType
from app.database import Base
from app.judges.base import EvaluationStatus, JudgeResult
from app.models.evaluation import Evaluation
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.models.submission import Submission
from app.services.submission_evaluations import (
    SubmissionEvaluationForbiddenError,
    SubmissionEvaluationService,
    SubmissionNotReplayableError,
)
from app.services.submissions import SubmissionService


class FakeCatalog:
    def __init__(self, cases=None):
        self.calls: list[tuple[str, str]] = []
        self.cases = cases or object()

    def load(self, problem_slug: str, version: str):
        self.calls.append((problem_slug, version))
        return self.cases


class FakeEvaluator:
    def __init__(self, result: JudgeResult):
        self.result = result
        self.calls: list[tuple[int, str, str, object]] = []

    async def evaluate(self, problem_id: int, problem_slug: str, source: str, cases):
        self.calls.append((problem_id, problem_slug, source, cases))
        return self.result


@pytest.fixture
async def evaluation_database(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'submission-evaluations.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


async def _create_submission(session: AsyncSession, *, source: str = "print(1)"):
    owner = Account(subject_type=SubjectType.HUMAN, name="owner")
    problem = Problem(
        slug="two-sum",
        title="Two Sum",
        description="description",
        allowed_languages=["python"],
        active_case_version="v2",
    )
    session.add_all([owner, problem])
    await session.flush()
    session.add(ProblemSubmissionPermission(account_id=owner.id, problem_id=problem.id))
    await session.commit()
    submission = await SubmissionService(session).create(
        owner,
        problem_id=problem.id,
        language="python",
        source=source,
    )
    await session.commit()
    return owner, problem, submission


def _judge_result() -> JudgeResult:
    return JudgeResult(
        problem_id=1,
        problem_slug="two-sum",
        language="python",
        status=EvaluationStatus.AC,
        case_version="v2",
        case_count=1,
        executed_count=1,
        passed_count=1,
        failed_case_index=None,
        summary="passed",
    )


@pytest.mark.asyncio
async def test_evaluation_uses_problem_active_case_version_and_persists_submission_snapshot(
    evaluation_database,
) -> None:
    async with evaluation_database() as session:
        owner, problem, submission = await _create_submission(session)
        catalog = FakeCatalog()
        evaluator = FakeEvaluator(_judge_result())
        service = SubmissionEvaluationService(
            session,
            case_catalog=catalog,
            evaluator_factory=lambda runtime_id: evaluator,
        )

        saved = await service.evaluate(owner, submission.id)
        await session.commit()

        assert catalog.calls == [(problem.slug, "v2")]
        assert evaluator.calls[0][2] == "print(1)"
        assert saved.submission_id == submission.id
        assert saved.source_sha256 == sha256(b"print(1)").hexdigest()
        assert saved.runtime_id == "python-3.11-v1"
        assert saved.case_version == "v2"
        assert saved.judge_status == "AC"

        persisted = await session.get(Evaluation, saved.id)
        assert persisted is not None
        assert persisted.submission_id == submission.id


@pytest.mark.asyncio
async def test_evaluation_rejects_cross_subject_and_cleaned_source_without_fake_result(
    evaluation_database,
) -> None:
    async with evaluation_database() as session:
        owner, _, submission = await _create_submission(session)
        other = Account(subject_type=SubjectType.AGENT, name="other")
        session.add(other)
        await session.flush()
        service = SubmissionEvaluationService(
            session,
            case_catalog=FakeCatalog(),
            evaluator_factory=lambda runtime_id: pytest.fail("evaluator must not be called"),
        )

        with pytest.raises(SubmissionEvaluationForbiddenError):
            await service.evaluate(other, submission.id)

        submission.source = None
        submission.source_deleted_at = datetime.now(timezone.utc)
        with pytest.raises(SubmissionNotReplayableError):
            await service.evaluate(owner, submission.id)

        assert await session.scalar(select(Evaluation)) is None
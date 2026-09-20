from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, SubjectType
from app.database import Base
from app.judges.base import EvaluationStatus, JudgeResult
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.services.candidate_generation import CandidateGeneration
from app.services.submission_evaluations import SubmissionEvaluationService
from app.services.submissions import SubmissionService


class IntegrationCatalog:
    def __init__(self, cases: object) -> None:
        self.cases = cases
        self.calls: list[tuple[str, str]] = []

    def load(self, problem_slug: str, version: str):
        self.calls.append((problem_slug, version))
        return self.cases


class IntegrationEvaluator:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str, object]] = []

    async def evaluate(self, problem_id: int, problem_slug: str, source: str, cases) -> JudgeResult:
        self.calls.append((problem_id, problem_slug, source, cases))
        return JudgeResult(
            problem_id=problem_id,
            problem_slug=problem_slug,
            language="python",
            status=EvaluationStatus.AC,
            case_version="v1",
            case_count=1,
            executed_count=1,
            passed_count=1,
            failed_case_index=None,
            summary="passed",
        )


@pytest.fixture
async def integration_database(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'submission-flow.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_candidate_generation_submission_and_pure_evaluation_flow(integration_database) -> None:
    async with integration_database() as session:
        subject = Account(subject_type=SubjectType.AGENT, name="generated-agent")
        problem = Problem(
            slug="two-sum",
            title="Two Sum",
            description="description",
            allowed_languages=["python"],
            active_case_version="v1",
        )
        session.add_all([subject, problem])
        await session.flush()
        session.add(ProblemSubmissionPermission(account_id=subject.id, problem_id=problem.id))
        await session.commit()

        candidate = CandidateGeneration.from_payload(
            {"language": "python", "source": "print(1)"}
        )
        submission = await SubmissionService(session).create(
            subject,
            problem_id=problem.id,
            language=candidate.language,
            source=candidate.source,
        )
        await session.commit()

        evaluator = IntegrationEvaluator()
        catalog = IntegrationCatalog(cases=object())
        saved = await SubmissionEvaluationService(
            session,
            case_catalog=catalog,
            evaluator_factory=lambda runtime_id: evaluator,
        ).evaluate(subject, submission.id)
        await session.commit()

        assert catalog.calls == [("two-sum", "v1")]
        assert evaluator.calls == [(problem.id, "two-sum", "print(1)", catalog.cases)]
        assert saved.submission_id == submission.id
        assert saved.judge_status == "AC"
        assert saved.source_sha256 == submission.source_sha256
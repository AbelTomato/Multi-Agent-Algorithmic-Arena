from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account
from app.config import Settings, get_settings
from app.judges.catalog import CaseCatalog
from app.judges.client import SandboxClient
from app.judges.evaluator import Evaluator
from app.models.evaluation import Evaluation
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.models.submission import Submission


class SubmissionEvaluationError(Exception):
    """Submission 评测服务的受控错误基类。"""


class SubmissionEvaluationForbiddenError(SubmissionEvaluationError):
    """当前主体没有访问或评测该 Submission 的权限。"""


class SubmissionNotReplayableError(SubmissionEvaluationError):
    """源码已清理，Submission 不再支持重放评测。"""


class SubmissionEvaluationNotFoundError(SubmissionEvaluationError):
    """Submission 或其题目不存在。"""


class SubmissionEvaluationService:
    """只消费已持久化 Submission 的同步评测服务。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        case_catalog: CaseCatalog | None = None,
        evaluator_factory: Callable[[str], Evaluator] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.case_catalog = case_catalog or CaseCatalog()
        self.evaluator_factory = evaluator_factory or self._default_evaluator_factory
        self.now = now or (lambda: datetime.now(timezone.utc))

    async def evaluate(self, subject: Account, submission_id: UUID) -> Evaluation:
        if not subject.is_active:
            raise SubmissionEvaluationForbiddenError("inactive subject")

        submission = await self.session.get(Submission, submission_id)
        if submission is None:
            raise SubmissionEvaluationNotFoundError("submission not found")
        if submission.author_subject_id != subject.id:
            raise SubmissionEvaluationForbiddenError("submission access is forbidden")

        permission = await self.session.scalar(
            select(ProblemSubmissionPermission).where(
                ProblemSubmissionPermission.account_id == subject.id,
                ProblemSubmissionPermission.problem_id == submission.problem_id,
                ProblemSubmissionPermission.permission == "submit",
            )
        )
        if permission is None:
            raise SubmissionEvaluationForbiddenError("submit permission is required")
        if submission.source is None or submission.source_deleted_at is not None:
            raise SubmissionNotReplayableError("submission source has been deleted")

        problem = await self.session.get(Problem, submission.problem_id)
        if problem is None:
            raise SubmissionEvaluationNotFoundError("problem not found")

        case_version = problem.active_case_version
        cases = self.case_catalog.load(problem.slug, case_version)
        evaluator = self.evaluator_factory(submission.runtime_id)
        result = await evaluator.evaluate(problem.id, problem.slug, submission.source, cases)
        close = getattr(getattr(evaluator, "client", None), "aclose", None)
        if close is not None:
            await close()

        evaluation = Evaluation(
            submission_id=submission.id,
            source_sha256=submission.source_sha256,
            language=submission.language,
            runtime_id=submission.runtime_id,
            case_version=result.case_version,
            judge_status=result.status.value,
            case_count=result.case_count,
            executed_count=result.executed_count,
            passed_count=result.passed_count,
            failed_case_index=result.failed_case_index,
            summary=result.summary,
            created_at=self.now(),
            finished_at=self.now(),
            duration_ms=None,
        )
        self.session.add(evaluation)
        await self.session.flush()
        return evaluation

    def _default_evaluator_factory(self, runtime_id: str) -> Evaluator:
        client = SandboxClient(
            base_url=self.settings.sandbox_controller_url,
            timeout=self.settings.sandbox_controller_timeout_seconds,
            runtime_id=runtime_id,
        )
        return Evaluator(client, runtime_id=runtime_id)
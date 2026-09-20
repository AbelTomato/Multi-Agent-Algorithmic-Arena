from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.models.submission import LANGUAGE_RUNTIME_IDS, Submission


MAX_SOURCE_BYTES = 64 * 1024
SOURCE_RETENTION_DAYS = 90


class SubmissionError(Exception):
    """Submission 服务边界的受控错误基类。"""


class SubmissionForbiddenError(SubmissionError):
    """主体没有题目提交权限或不是 Submission 作者。"""


class SubmissionValidationError(SubmissionError):
    """提交参数不符合固定业务契约。"""


class SubmissionConflictError(SubmissionError):
    """修订链不符合相同作者、相同题目的不可变版本规则。"""


class SubmissionNotFoundError(SubmissionError):
    """Submission 或题目不存在。"""


class SubmissionService:
    def __init__(self, session: AsyncSession, *, now=None) -> None:
        self.session = session
        self.now = now or (lambda: datetime.now(timezone.utc))

    async def create(
        self,
        subject: Account,
        *,
        problem_id: int,
        language: str,
        source: str,
        supersedes_submission_id: UUID | None = None,
        runtime_id: str | None = None,
        **client_execution_fields: object,
    ) -> Submission:
        if runtime_id is not None or client_execution_fields:
            raise SubmissionValidationError("runtime and execution settings are server controlled")
        if not subject.is_active:
            raise SubmissionForbiddenError("inactive subject")

        problem = await self.session.get(Problem, problem_id)
        if problem is None:
            raise SubmissionNotFoundError("problem not found")
        if not await self._has_submit_permission(subject.id, problem_id):
            raise SubmissionForbiddenError("submit permission is required")

        self._validate_source(source)
        if language not in LANGUAGE_RUNTIME_IDS:
            raise SubmissionValidationError("unsupported language")
        if language not in problem.allowed_languages:
            raise SubmissionValidationError("language is not allowed for this problem")

        if supersedes_submission_id is not None:
            previous = await self._get_owned_submission(subject.id, supersedes_submission_id)
            if previous.problem_id != problem_id:
                raise SubmissionConflictError("revision must keep the same problem")

        created_at = self.now()
        submission = Submission(
            problem_id=problem_id,
            author_subject_id=subject.id,
            language=language,
            runtime_id=LANGUAGE_RUNTIME_IDS[language],
            source=source,
            source_sha256=sha256(source.encode("utf-8")).hexdigest(),
            supersedes_submission_id=supersedes_submission_id,
            retention_expires_at=created_at + timedelta(days=SOURCE_RETENTION_DAYS),
            created_at=created_at,
        )
        self.session.add(submission)
        await self.session.flush()
        return submission

    async def get(self, subject: Account, submission_id: UUID) -> Submission:
        return await self._get_owned_submission(subject.id, submission_id)

    async def revise(
        self,
        subject: Account,
        submission_id: UUID,
        *,
        problem_id: int,
        language: str,
        source: str,
    ) -> Submission:
        original = await self._get_owned_submission(subject.id, submission_id)
        if original.problem_id != problem_id:
            raise SubmissionConflictError("revision must keep the same problem")
        return await self.create(
            subject,
            problem_id=problem_id,
            language=language,
            source=source,
            supersedes_submission_id=original.id,
        )

    async def _has_submit_permission(self, account_id: UUID, problem_id: int) -> bool:
        permission = await self.session.scalar(
            select(ProblemSubmissionPermission).where(
                ProblemSubmissionPermission.account_id == account_id,
                ProblemSubmissionPermission.problem_id == problem_id,
                ProblemSubmissionPermission.permission == "submit",
            )
        )
        return permission is not None

    async def _get_owned_submission(self, account_id: UUID, submission_id: UUID) -> Submission:
        submission = await self.session.get(Submission, submission_id)
        if submission is None:
            raise SubmissionNotFoundError("submission not found")
        if submission.author_subject_id != account_id:
            raise SubmissionForbiddenError("submission access is forbidden")
        return submission

    @staticmethod
    def _validate_source(source: str) -> None:
        if not source:
            raise SubmissionValidationError("source must not be empty")
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise SubmissionValidationError("source exceeds 64 KiB")
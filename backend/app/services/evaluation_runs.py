"""评测运行记录 repository、受控状态机和会话隔离查询。"""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.judges.base import JudgeResult
from app.models.evaluation_run import (
    EvaluationErrorCategory,
    EvaluationRun,
    EvaluationRunStatus,
)
from app.models.problem import Problem


SAFE_ERROR_SUMMARIES: dict[EvaluationErrorCategory, str] = {
    EvaluationErrorCategory.AGENT_ERROR: "Agent 未能生成可执行候选程序",
    EvaluationErrorCategory.CONTROLLER_BUSY: "评测服务繁忙，请稍后重试",
    EvaluationErrorCategory.CONTROLLER_UNAVAILABLE: "评测执行服务暂不可用",
    EvaluationErrorCategory.CONTROLLER_TIMEOUT: "评测执行服务响应超时",
    EvaluationErrorCategory.CONTROLLER_RESPONSE_ERROR: "评测执行服务返回无效响应",
    EvaluationErrorCategory.EVALUATION_TIMEOUT: "评测超过总时限",
    EvaluationErrorCategory.INTERNAL_ERROR: "评测未能完成",
}

TERMINAL_RUN_STATUSES = (
    EvaluationRunStatus.SUCCEEDED.value,
    EvaluationRunStatus.FAILED.value,
    EvaluationRunStatus.TIMED_OUT.value,
    EvaluationRunStatus.REJECTED.value,
    EvaluationRunStatus.INTERRUPTED.value,
)

FAILURE_RUN_STATUSES = {
    EvaluationRunStatus.FAILED,
    EvaluationRunStatus.TIMED_OUT,
    EvaluationRunStatus.REJECTED,
    EvaluationRunStatus.INTERRUPTED,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationRunRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session = session
        self.clock = clock

    async def create_running(
        self,
        session_key_hash: str,
        problem: Problem,
        case_version: str,
        case_count: int,
    ) -> EvaluationRun:
        now = self.clock()
        run = EvaluationRun(
            session_key_hash=session_key_hash,
            problem_id=problem.id,
            problem_slug=problem.slug,
            language="python",
            run_status=EvaluationRunStatus.RUNNING.value,
            judge_status=None,
            case_version=case_version,
            case_count=case_count,
            executed_count=None,
            passed_count=None,
            failed_case_index=None,
            summary=None,
            error_category=None,
            created_at=now,
            started_at=now,
            finished_at=None,
            duration_ms=None,
        )
        self.session.add(run)
        await self.session.commit()
        return run

    async def mark_succeeded(
        self,
        run_id: UUID,
        result: JudgeResult,
        finished_at: datetime,
        duration_ms: int,
    ) -> bool:
        statement = (
            update(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.run_status == EvaluationRunStatus.RUNNING.value,
            )
            .values(
                run_status=EvaluationRunStatus.SUCCEEDED.value,
                judge_status=result.status.value,
                executed_count=result.executed_count,
                passed_count=result.passed_count,
                failed_case_index=result.failed_case_index,
                summary=result.summary,
                error_category=None,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
        )
        execution = await self.session.execute(statement)
        return execution.rowcount == 1

    async def mark_failed(
        self,
        run_id: UUID,
        run_status: EvaluationRunStatus,
        error_category: EvaluationErrorCategory,
        summary: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> bool:
        del summary  # 调用方异常文本绝不进入持久化记录。
        if run_status not in FAILURE_RUN_STATUSES:
            raise ValueError("mark_failed only accepts non-success terminal statuses")
        statement = (
            update(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.run_status == EvaluationRunStatus.RUNNING.value,
            )
            .values(
                run_status=run_status.value,
                judge_status=None,
                summary=SAFE_ERROR_SUMMARIES[error_category],
                error_category=error_category.value,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
        )
        execution = await self.session.execute(statement)
        return execution.rowcount == 1

    async def list_for_session(
        self,
        session_key_hash: str,
        cutoff: datetime,
        problem_id: int | None,
        limit: int,
        offset: int,
    ) -> tuple[list[EvaluationRun], int]:
        filters = [
            EvaluationRun.session_key_hash == session_key_hash,
            EvaluationRun.created_at >= cutoff,
        ]
        if problem_id is not None:
            filters.append(EvaluationRun.problem_id == problem_id)

        total = await self.session.scalar(
            select(func.count()).select_from(EvaluationRun).where(*filters)
        )
        rows = await self.session.scalars(
            select(EvaluationRun)
            .where(*filters)
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def get_for_session(
        self,
        run_id: UUID,
        session_key_hash: str,
        cutoff: datetime,
    ) -> EvaluationRun | None:
        return await self.session.scalar(
            select(EvaluationRun).where(
                EvaluationRun.id == run_id,
                EvaluationRun.session_key_hash == session_key_hash,
                EvaluationRun.created_at >= cutoff,
            )
        )

    async def interrupt_stale_runs(self, cutoff: datetime) -> int:
        statement = (
            update(EvaluationRun)
            .where(
                EvaluationRun.run_status == EvaluationRunStatus.RUNNING.value,
                EvaluationRun.started_at < cutoff,
            )
            .values(
                run_status=EvaluationRunStatus.INTERRUPTED.value,
                judge_status=None,
                summary="评测服务重启，运行已中断",
                error_category=EvaluationErrorCategory.INTERNAL_ERROR.value,
                finished_at=self.clock(),
                duration_ms=0,
            )
        )
        execution = await self.session.execute(statement)
        return execution.rowcount

    async def delete_expired_runs(self, cutoff: datetime) -> int:
        statement = delete(EvaluationRun).where(
            EvaluationRun.created_at < cutoff,
            EvaluationRun.run_status.in_(TERMINAL_RUN_STATUSES),
        )
        execution = await self.session.execute(statement)
        return execution.rowcount
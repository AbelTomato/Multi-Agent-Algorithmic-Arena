from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, SubjectType
from app.contests.contracts import (
    ContestActionRequest,
    ContestAgentContext,
    ContestLeaseGrant,
)
from app.contests.rules import ContestSeatStatus, ContestStatus
from app.contests.service import ContestService
from app.models.contest import (
    Contest,
    ContestAgentAttempt,
    ContestAgentLease,
    ContestSeat,
)
from app.models.submission import Submission


class ContestAgentDriver(Protocol):
    async def generate_action(self, context: ContestAgentContext) -> ContestActionRequest: ...


class ContestWorkerError(Exception):
    """Agent Worker 领域错误。"""


class ContestLeaseConflictError(ContestWorkerError):
    """目标席位已有未过期租约。"""


class ContestLeaseForbiddenError(ContestWorkerError):
    """租约凭据或席位状态不允许当前操作。"""


class ContestAttemptNotFoundError(ContestWorkerError):
    """租约或尝试记录不存在。"""


class ContestAgentWorker:
    """只负责 Agent 租约、尝试记录和受限上下文，不调用真实 Provider。"""

    def __init__(self, session: AsyncSession, *, lease_seconds: int = 30) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.session = session
        self.lease_seconds = lease_seconds

    async def acquire_lease(
        self,
        contest_id: UUID,
        seat_id: UUID,
        worker_id: str,
        *,
        now: datetime,
    ) -> ContestLeaseGrant:
        now = self._require_aware(now)
        worker_id = worker_id.strip()
        if not worker_id or len(worker_id) > 100:
            raise ValueError("worker_id must be between 1 and 100 characters")

        contest, seat = await self._get_contest_and_seat(contest_id, seat_id)
        if contest.status != ContestStatus.SOLVING.value:
            raise ContestLeaseForbiddenError("agent leases require a solving contest")
        if seat.status != ContestSeatStatus.ACTIVE.value:
            raise ContestLeaseForbiddenError("agent lease requires an active seat")
        account = await self.session.get(Account, seat.account_id)
        if account is None or account.subject_type != SubjectType.AGENT.value:
            raise ContestLeaseForbiddenError("only agent seats can acquire agent leases")

        active_lease = await self.session.scalar(
            select(ContestAgentLease)
            .where(
                ContestAgentLease.contest_id == contest.id,
                ContestAgentLease.seat_id == seat.id,
                ContestAgentLease.released_at.is_(None),
                ContestAgentLease.expires_at > now,
            )
            .order_by(ContestAgentLease.created_at.desc())
        )
        if active_lease is not None:
            raise ContestLeaseConflictError("agent seat already has an active lease")

        previous_attempt_number = await self.session.scalar(
            select(func.max(ContestAgentLease.attempt_number)).where(
                ContestAgentLease.contest_id == contest.id,
                ContestAgentLease.seat_id == seat.id,
            )
        )
        attempt_number = (previous_attempt_number or 0) + 1
        lease_token = secrets.token_urlsafe(32)
        lease = ContestAgentLease(
            contest_id=contest.id,
            seat_id=seat.id,
            worker_id=worker_id,
            lease_token_hash=self._hash_token(lease_token),
            attempt_number=attempt_number,
            expires_at=now + timedelta(seconds=self.lease_seconds),
        )
        self.session.add(lease)
        await self.session.flush()
        return ContestLeaseGrant(
            lease_id=lease.id,
            contest_id=lease.contest_id,
            seat_id=lease.seat_id,
            worker_id=lease.worker_id,
            attempt_number=lease.attempt_number,
            expires_at=lease.expires_at,
            lease_token=lease_token,
        )

    async def start_attempt(
        self,
        lease_id: UUID,
        client_action_id: str,
        *,
        lease_token: str,
        now: datetime,
    ) -> ContestAgentAttempt:
        now = self._require_aware(now)
        lease = await self._get_valid_lease(lease_id, lease_token, now)
        existing = await self.session.scalar(
            select(ContestAgentAttempt).where(
                ContestAgentAttempt.lease_id == lease.id,
                ContestAgentAttempt.client_action_id == client_action_id,
            )
        )
        if existing is not None:
            return existing
        attempt = ContestAgentAttempt(
            contest_id=lease.contest_id,
            seat_id=lease.seat_id,
            lease_id=lease.id,
            attempt_number=lease.attempt_number,
            client_action_id=client_action_id,
            status="RUNNING",
            started_at=now,
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def complete_attempt(
        self,
        lease_id: UUID,
        *,
        client_action_id: str,
        lease_token: str,
        action: ContestActionRequest,
        now: datetime,
    ) -> ContestAgentAttempt:
        now = self._require_aware(now)
        lease = await self._get_valid_lease(lease_id, lease_token, now, allow_released=True)
        attempt = await self._get_attempt(lease.id, client_action_id)
        if attempt.status == "SUCCEEDED":
            return attempt
        if attempt.status != "RUNNING":
            raise ContestLeaseForbiddenError("only a running attempt can complete")

        account = await self.session.get(Account, (await self._get_seat(lease.seat_id)).account_id)
        if account is None:
            raise ContestAttemptNotFoundError("agent account not found")
        await ContestService(self.session).apply_action(account, lease.contest_id, action, now=now)
        attempt.status = "SUCCEEDED"
        attempt.finished_at = now
        lease.released_at = now
        await self.session.flush()
        return attempt

    async def fail_attempt(
        self,
        lease_id: UUID,
        *,
        client_action_id: str,
        lease_token: str,
        failure_code: str,
        failure_summary: str,
        now: datetime,
    ) -> ContestAgentAttempt:
        now = self._require_aware(now)
        lease = await self._get_valid_lease(lease_id, lease_token, now, allow_released=True)
        attempt = await self._get_attempt(lease.id, client_action_id)
        if attempt.status == "FAILED":
            return attempt
        if attempt.status != "RUNNING":
            raise ContestLeaseForbiddenError("only a running attempt can fail")
        attempt.status = "FAILED"
        attempt.failure_code = failure_code.strip()[:60]
        attempt.failure_summary = failure_summary.strip()[:500]
        attempt.finished_at = now
        lease.released_at = now
        await self.session.flush()
        return attempt

    async def recover_expired_leases(self, *, now: datetime) -> int:
        now = self._require_aware(now)
        leases = (
            await self.session.scalars(
                select(ContestAgentLease).where(
                    ContestAgentLease.released_at.is_(None),
                    ContestAgentLease.expires_at <= now,
                )
            )
        ).all()
        for lease in leases:
            lease.released_at = now
            running_attempts = (
                await self.session.scalars(
                    select(ContestAgentAttempt).where(
                        ContestAgentAttempt.lease_id == lease.id,
                        ContestAgentAttempt.status == "RUNNING",
                    )
                )
            ).all()
            for attempt in running_attempts:
                attempt.status = "EXPIRED"
                attempt.failure_code = "lease_expired"
                attempt.failure_summary = "worker lease expired before the attempt completed"
                attempt.finished_at = now
        await self.session.flush()
        return len(leases)

    async def build_context(self, contest_id: UUID, seat_id: UUID) -> ContestAgentContext:
        contest, seat = await self._get_contest_and_seat(contest_id, seat_id)
        account = await self.session.get(Account, seat.account_id)
        if account is None or account.subject_type != SubjectType.AGENT.value:
            raise ContestLeaseForbiddenError("only agent seats can build agent context")
        submission = None
        if seat.current_submission_id is not None:
            submission = await self.session.get(Submission, seat.current_submission_id)
        return ContestAgentContext(
            contest_id=contest.id,
            seat_id=seat.id,
            seat_key=seat.seat_key,
            problem_id=contest.problem_id,
            rule_version=contest.rule_version,
            status=contest.status,
            state_version=contest.state_version,
            event_sequence=contest.event_sequence,
            current_submission_id=seat.current_submission_id,
            submission_count=seat.submission_count,
            source=submission.source if submission is not None else None,
            language=submission.language if submission is not None else None,
            runtime_id=submission.runtime_id if submission is not None else None,
            evaluation_status=seat.evaluation_status,
            final_fact_type=seat.final_fact_type,
            fact_summary=seat.fact_summary,
        )

    async def _get_valid_lease(
        self,
        lease_id: UUID,
        lease_token: str,
        now: datetime,
        *,
        allow_released: bool = False,
    ) -> ContestAgentLease:
        lease = await self.session.get(ContestAgentLease, lease_id)
        if lease is None:
            raise ContestAttemptNotFoundError("lease not found")
        if self._hash_token(lease_token) != lease.lease_token_hash:
            raise ContestLeaseForbiddenError("invalid lease token")
        if not allow_released and lease.released_at is not None:
            raise ContestLeaseForbiddenError("lease is no longer active")
        if (
            lease.released_at is None
            and self._as_utc(lease.expires_at) <= now
        ):
            raise ContestLeaseForbiddenError("lease has expired")
        return lease

    async def _get_attempt(self, lease_id: UUID, client_action_id: str) -> ContestAgentAttempt:
        attempt = await self.session.scalar(
            select(ContestAgentAttempt).where(
                ContestAgentAttempt.lease_id == lease_id,
                ContestAgentAttempt.client_action_id == client_action_id,
            )
        )
        if attempt is None:
            raise ContestAttemptNotFoundError("attempt not found")
        return attempt

    async def _get_contest_and_seat(
        self,
        contest_id: UUID,
        seat_id: UUID,
    ) -> tuple[Contest, ContestSeat]:
        contest = await self.session.get(Contest, contest_id)
        seat = await self.session.scalar(
            select(ContestSeat).where(
                ContestSeat.id == seat_id,
                ContestSeat.contest_id == contest_id,
            )
        )
        if contest is None or seat is None:
            raise ContestAttemptNotFoundError("contest seat not found")
        return contest, seat

    async def _get_seat(self, seat_id: UUID) -> ContestSeat:
        seat = await self.session.get(ContestSeat, seat_id)
        if seat is None:
            raise ContestAttemptNotFoundError("contest seat not found")
        return seat

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("time must include a timezone")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
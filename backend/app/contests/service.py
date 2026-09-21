from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account
from app.contests.contracts import (
    ContestActionRequest,
    ContestActionResponse,
    ContestSeatView,
    ContestView,
)
from app.contests.rules import (
    ContestActionType,
    ContestFinalFactType,
    ContestSeatStatus,
    ContestStatus,
    RULE_VERSION,
)
from app.models.contest import Contest, ContestAction, ContestEvent, ContestSeat
from app.models.evaluation import Evaluation
from app.models.problem import Problem
from app.models.submission import Submission


class ContestError(Exception):
    """比赛领域错误基类。"""


class ContestNotFoundError(ContestError):
    """比赛、题目或参与账户不存在。"""


class ContestForbiddenError(ContestError):
    """当前主体不能执行该比赛操作。"""


class ContestValidationError(ContestError):
    """比赛创建或动作输入不满足规则。"""


class ContestStateError(ContestError):
    """当前比赛状态不允许该操作。"""


class ContestVersionConflictError(ContestError):
    """客户端携带的状态版本已经过期。"""


class ContestActionConflictError(ContestError):
    """幂等键已经被不同动作或主体使用。"""


class ContestService:
    """阶段 E 比赛状态和统一动作的事务内编排服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_draft(
        self,
        owner: Account,
        *,
        problem_id: int,
        first_account_id: UUID,
        second_account_id: UUID,
        starts_at: datetime,
        solving_deadline: datetime,
        now: datetime | None = None,
    ) -> Contest:
        del now
        if first_account_id == second_account_id:
            raise ContestValidationError("contest seats must belong to different accounts")
        if starts_at.tzinfo is None or solving_deadline.tzinfo is None:
            raise ContestValidationError("contest times must include a timezone")
        if solving_deadline <= starts_at:
            raise ContestValidationError("solving_deadline must be after starts_at")

        problem = await self.session.get(Problem, problem_id)
        if problem is None:
            raise ContestNotFoundError("problem not found")

        account_ids = {owner.id, first_account_id, second_account_id}
        accounts = (
            await self.session.scalars(select(Account).where(Account.id.in_(account_ids)))
        ).all()
        accounts_by_id = {account.id: account for account in accounts}
        if first_account_id not in accounts_by_id or second_account_id not in accounts_by_id:
            raise ContestNotFoundError("contest seat account not found")
        if not accounts_by_id[first_account_id].is_active or not accounts_by_id[second_account_id].is_active:
            raise ContestValidationError("contest seat account is disabled")

        contest = Contest(
            owner_account_id=owner.id,
            problem_id=problem_id,
            rule_version=RULE_VERSION,
            status=ContestStatus.DRAFT.value,
            starts_at=starts_at,
            solving_deadline=solving_deadline,
            state_version=0,
            event_sequence=0,
        )
        self.session.add(contest)
        await self.session.flush()

        first_seat = ContestSeat(
            contest_id=contest.id,
            seat_key="A",
            account_id=first_account_id,
            status=ContestSeatStatus.ASSIGNED.value,
            submission_count=0,
        )
        second_seat = ContestSeat(
            contest_id=contest.id,
            seat_key="B",
            account_id=second_account_id,
            status=ContestSeatStatus.ASSIGNED.value,
            submission_count=0,
        )
        self.session.add_all([first_seat, second_seat])
        await self._append_event(
            contest,
            event_type="contest_created",
            actor_account_id=owner.id,
            payload={"status": ContestStatus.DRAFT.value},
        )
        await self.session.flush()
        return contest

    async def get_view(self, subject: Account, contest_id: UUID) -> ContestView:
        contest = await self._get_contest(contest_id)
        await self._ensure_visible(subject, contest)
        return await self._build_view(contest, viewer=subject)

    async def apply_action(
        self,
        subject: Account,
        contest_id: UUID,
        request: ContestActionRequest,
        *,
        now: datetime | None = None,
    ) -> ContestActionResponse:
        contest = await self._get_contest(contest_id)
        payload_hash = self._payload_hash(request)
        existing = await self.session.scalar(
            select(ContestAction).where(
                ContestAction.contest_id == contest.id,
                ContestAction.client_action_id == request.client_action_id,
            )
        )
        if existing is not None:
            if (
                existing.actor_account_id != subject.id
                or existing.action_type != request.action_type.value
                or existing.payload_hash != payload_hash
            ):
                raise ContestActionConflictError("client_action_id is already used by another action")
            return ContestActionResponse.model_validate(existing.result_payload)

        if request.expected_version != contest.state_version:
            raise ContestVersionConflictError(
                f"expected contest version {request.expected_version}, current is {contest.state_version}"
            )

        await self._ensure_visible(subject, contest)
        current_time = now or datetime.now(timezone.utc)
        action_type = request.action_type
        if action_type in {
            ContestActionType.PUBLISH,
            ContestActionType.CANCEL,
            ContestActionType.RESUME,
        } and subject.id != contest.owner_account_id:
            raise ContestForbiddenError("only contest owner can perform this action")

        if action_type is ContestActionType.PUBLISH:
            if contest.status != ContestStatus.DRAFT.value:
                raise ContestStateError("only draft contests can be published")
            contest.status = ContestStatus.OPEN.value
            await self._append_event(
                contest,
                event_type="contest_opened",
                actor_account_id=subject.id,
                payload={"status": ContestStatus.OPEN.value},
            )
        elif action_type is ContestActionType.CANCEL:
            if contest.status not in {
                ContestStatus.DRAFT.value,
                ContestStatus.OPEN.value,
                ContestStatus.SOLVING.value,
                ContestStatus.PAUSED_INFRASTRUCTURE.value,
            }:
                raise ContestStateError("contest cannot be cancelled in its current state")
            contest.status = ContestStatus.CANCELLED.value
            await self._append_event(
                contest,
                event_type="contest_cancelled",
                actor_account_id=subject.id,
                payload={"status": ContestStatus.CANCELLED.value},
            )
        elif action_type is ContestActionType.SUBMIT_SUBMISSION:
            seat = await self._get_subject_seat(contest, subject)
            if contest.status != ContestStatus.SOLVING.value:
                raise ContestStateError("submissions are only accepted while solving")
            if seat.status != ContestSeatStatus.ACTIVE.value:
                raise ContestStateError("withdrawn seat cannot submit")
            submission = await self._get_submission_from_request(request)
            if submission.author_subject_id != seat.account_id:
                raise ContestForbiddenError("submission author does not own this contest seat")
            if submission.problem_id != contest.problem_id:
                raise ContestValidationError("submission must target the contest problem")
            if submission.source is None or submission.source_deleted_at is not None:
                raise ContestValidationError("submission source is not replayable")
            if seat.submission_count >= 3:
                raise ContestValidationError("contest seat submission limit reached")
            if seat.current_submission_id is None:
                if submission.supersedes_submission_id is not None:
                    raise ContestValidationError("first contest submission cannot be a revision")
            elif submission.supersedes_submission_id != seat.current_submission_id:
                raise ContestValidationError("contest revisions must be linear")

            seat.current_submission_id = submission.id
            seat.submission_count += 1
            await self._append_event(
                contest,
                event_type="submission_accepted",
                actor_account_id=subject.id,
                seat_id=seat.id,
                payload={
                    "seat_key": seat.seat_key,
                    "submission_id": str(submission.id),
                    "submission_count": seat.submission_count,
                },
            )
        elif action_type is ContestActionType.WITHDRAW:
            seat = await self._get_subject_seat(contest, subject)
            if contest.status not in {
                ContestStatus.OPEN.value,
                ContestStatus.SOLVING.value,
            }:
                raise ContestStateError("withdrawal is only available before the contest is locked")
            if seat.status == ContestSeatStatus.WITHDRAWN.value:
                raise ContestStateError("withdrawn seat cannot withdraw again")

            seat.status = ContestSeatStatus.WITHDRAWN.value
            seat.withdrawn_at = current_time
            await self._append_event(
                contest,
                event_type="seat_withdrawn",
                actor_account_id=subject.id,
                seat_id=seat.id,
                payload={"seat_key": seat.seat_key, "status": seat.status},
            )
            seats = await self._get_seats(contest.id)
            if all(candidate.status == ContestSeatStatus.WITHDRAWN.value for candidate in seats):
                contest.status = ContestStatus.CANCELLED.value
                await self._append_event(
                    contest,
                    event_type="contest_cancelled",
                    actor_account_id=subject.id,
                    payload={"status": ContestStatus.CANCELLED.value, "reason": "all_seats_withdrawn"},
                )
        elif action_type is ContestActionType.RESUME:
            if contest.status != ContestStatus.PAUSED_INFRASTRUCTURE.value:
                raise ContestStateError("resume is only available for infrastructure-paused contests")
            if (
                contest.paused_previous_status != ContestStatus.SOLVING.value
                or contest.paused_remaining_seconds is None
            ):
                raise ContestStateError("paused contest does not have resumable solving state")
            if current_time.tzinfo is None:
                raise ContestValidationError("now must include a timezone")
            contest.solving_deadline = current_time + timedelta(
                seconds=contest.paused_remaining_seconds
            )
            contest.status = contest.paused_previous_status
            contest.paused_previous_status = None
            contest.paused_remaining_seconds = None
            await self._append_event(
                contest,
                event_type="contest_resumed",
                actor_account_id=subject.id,
                payload={
                    "status": ContestStatus.SOLVING.value,
                    "solving_deadline": contest.solving_deadline.isoformat(),
                },
            )
        else:
            raise ContestStateError(f"action {action_type.value} is not implemented in this slice")

        contest.state_version += 1
        await self.session.flush()
        view = await self._build_view(contest, viewer=subject)
        action = ContestAction(
            contest_id=contest.id,
            client_action_id=request.client_action_id,
            actor_account_id=subject.id,
            action_type=action_type.value,
            payload_hash=payload_hash,
            result_payload={},
            result_state_version=contest.state_version,
            result_event_sequence=contest.event_sequence,
        )
        self.session.add(action)
        await self.session.flush()
        response = ContestActionResponse(
            **view.model_dump(),
            action_id=action.id,
            client_action_id=request.client_action_id,
        )
        action.result_payload = response.model_dump(mode="json")
        await self.session.flush()
        return response

    async def advance_time(self, contest_id: UUID, *, now: datetime) -> ContestView:
        now = self._require_aware(now)
        contest = await self._get_contest(contest_id)
        starts_at = self._as_utc(contest.starts_at)
        solving_deadline = self._as_utc(contest.solving_deadline)

        if contest.status == ContestStatus.OPEN.value and now >= starts_at:
            contest.status = ContestStatus.SOLVING.value
            contest.state_version += 1
            seats = await self._get_seats(contest.id)
            for seat in seats:
                if seat.status == ContestSeatStatus.ASSIGNED.value:
                    seat.status = ContestSeatStatus.ACTIVE.value
            await self._append_event(
                contest,
                event_type="contest_started",
                actor_account_id=None,
                payload={"status": ContestStatus.SOLVING.value},
            )

        if contest.status == ContestStatus.SOLVING.value and now >= solving_deadline:
            contest.status = ContestStatus.LOCKED.value
            contest.state_version += 1
            await self._append_event(
                contest,
                event_type="contest_locked",
                actor_account_id=None,
                payload={"status": ContestStatus.LOCKED.value},
            )

        await self.session.flush()
        return await self._build_view(contest)

    async def pause_for_infrastructure(
        self,
        contest_id: UUID,
        *,
        reason_code: str,
        now: datetime,
    ) -> ContestView:
        now = self._require_aware(now)
        reason_code = reason_code.strip()
        if not reason_code or len(reason_code) > 60:
            raise ContestValidationError("reason_code must be between 1 and 60 characters")

        contest = await self._get_contest(contest_id)
        if contest.status != ContestStatus.SOLVING.value:
            raise ContestStateError("only solving contests can be paused")

        deadline = self._as_utc(contest.solving_deadline)
        if now >= deadline:
            raise ContestStateError("contest deadline has already been reached")
        remaining_seconds = max(0, int((deadline - now).total_seconds()))
        contest.paused_previous_status = contest.status
        contest.paused_remaining_seconds = remaining_seconds
        contest.status = ContestStatus.PAUSED_INFRASTRUCTURE.value
        await self._append_event(
            contest,
            event_type="contest_paused_infrastructure",
            actor_account_id=None,
            payload={
                "status": ContestStatus.PAUSED_INFRASTRUCTURE.value,
                "previous_status": ContestStatus.SOLVING.value,
                "reason_code": reason_code,
                "remaining_seconds": remaining_seconds,
            },
        )
        contest.state_version += 1
        await self.session.flush()
        return await self._build_view(contest)

    async def record_evaluation(
        self,
        contest_id: UUID,
        seat_id: UUID,
        evaluation_id: UUID,
        *,
        now: datetime,
    ) -> ContestView:
        self._require_aware(now)
        contest = await self._get_contest(contest_id)
        if contest.status != ContestStatus.LOCKED.value:
            raise ContestStateError("final evaluations can only be recorded for locked contests")

        seat = await self._get_contest_seat(contest.id, seat_id)
        if seat.final_fact_type is not None:
            raise ContestValidationError("contest seat already has a final fact")
        if seat.status == ContestSeatStatus.WITHDRAWN.value:
            raise ContestStateError("withdrawn seat does not require an evaluation")
        if seat.current_submission_id is None:
            raise ContestValidationError("contest seat has no submission to evaluate")

        evaluation = await self.session.get(Evaluation, evaluation_id)
        if evaluation is None:
            raise ContestNotFoundError("evaluation not found")
        submission = await self.session.get(Submission, seat.current_submission_id)
        if submission is None:
            raise ContestNotFoundError("current contest submission not found")
        if evaluation.submission_id != submission.id:
            raise ContestValidationError("evaluation must belong to the current contest submission")
        if submission.problem_id != contest.problem_id:
            raise ContestValidationError("evaluation submission must target the contest problem")
        if submission.author_subject_id != seat.account_id:
            raise ContestValidationError("evaluation submission author must own the contest seat")
        if evaluation.source_sha256 != submission.source_sha256:
            raise ContestValidationError("evaluation source does not match the current submission")
        if evaluation.language != submission.language or evaluation.runtime_id != submission.runtime_id:
            raise ContestValidationError("evaluation runtime does not match the current submission")
        if evaluation.judge_status is None:
            raise ContestValidationError("evaluation must contain a judge status")

        seat.final_fact_type = ContestFinalFactType.EVALUATION.value
        seat.evaluation_status = evaluation.judge_status
        seat.evaluation_id = evaluation.id
        seat.fact_summary = (evaluation.summary or "").strip()[:500]
        await self._append_event(
            contest,
            event_type="evaluation_recorded",
            actor_account_id=None,
            seat_id=seat.id,
            payload={
                "fact_type": ContestFinalFactType.EVALUATION.value,
                "submission_id": str(submission.id),
                "evaluation_id": str(evaluation.id),
                "evaluation_status": evaluation.judge_status,
            },
        )
        await self._maybe_mark_ready(contest)
        contest.state_version += 1
        await self.session.flush()
        return await self._build_view(contest)

    async def record_infrastructure_failure(
        self,
        contest_id: UUID,
        seat_id: UUID,
        *,
        reason_code: str,
        summary: str,
        now: datetime,
    ) -> ContestView:
        self._require_aware(now)
        reason_code = reason_code.strip()
        summary = summary.strip()
        if not reason_code or len(reason_code) > 60:
            raise ContestValidationError("reason_code must be between 1 and 60 characters")
        if not summary or len(summary) > 500:
            raise ContestValidationError("summary must be between 1 and 500 characters")

        contest = await self._get_contest(contest_id)
        if contest.status != ContestStatus.LOCKED.value:
            raise ContestStateError("infrastructure failures can only be recorded for locked contests")

        seat = await self._get_contest_seat(contest.id, seat_id)
        if seat.final_fact_type is not None:
            raise ContestValidationError("contest seat already has a final fact")
        if seat.status == ContestSeatStatus.WITHDRAWN.value:
            raise ContestStateError("withdrawn seat does not require an infrastructure failure")
        if seat.current_submission_id is None:
            raise ContestValidationError("contest seat has no submission requiring infrastructure evaluation")

        seat.final_fact_type = ContestFinalFactType.INFRASTRUCTURE_FAILURE.value
        seat.evaluation_status = ContestFinalFactType.INFRASTRUCTURE_FAILURE.value
        seat.evaluation_id = None
        seat.fact_summary = summary
        await self._append_event(
            contest,
            event_type="infrastructure_failure",
            actor_account_id=None,
            seat_id=seat.id,
            payload={
                "fact_type": ContestFinalFactType.INFRASTRUCTURE_FAILURE.value,
                "reason_code": reason_code,
            },
        )
        await self._maybe_mark_ready(contest)
        contest.state_version += 1
        await self.session.flush()
        return await self._build_view(contest)

    async def _maybe_mark_ready(self, contest: Contest) -> None:
        if contest.status != ContestStatus.LOCKED.value:
            return

        seats = await self._get_seats(contest.id)
        for seat in seats:
            if seat.final_fact_type is not None:
                continue
            if seat.status == ContestSeatStatus.WITHDRAWN.value:
                seat.final_fact_type = ContestFinalFactType.WITHDRAWN.value
                seat.evaluation_status = ContestFinalFactType.WITHDRAWN.value
                seat.fact_summary = "participant withdrew"
                await self._append_event(
                    contest,
                    event_type="seat_fact_recorded",
                    actor_account_id=None,
                    seat_id=seat.id,
                    payload={"fact_type": ContestFinalFactType.WITHDRAWN.value},
                )
            elif seat.current_submission_id is None:
                seat.final_fact_type = ContestFinalFactType.NO_SUBMISSION.value
                seat.evaluation_status = ContestFinalFactType.NO_SUBMISSION.value
                seat.fact_summary = "no submission accepted"
                await self._append_event(
                    contest,
                    event_type="seat_fact_recorded",
                    actor_account_id=None,
                    seat_id=seat.id,
                    payload={"fact_type": ContestFinalFactType.NO_SUBMISSION.value},
                )

        if seats and all(seat.final_fact_type is not None for seat in seats):
            contest.status = ContestStatus.READY_FOR_ADJUDICATION.value
            await self._append_event(
                contest,
                event_type="contest_ready_for_adjudication",
                actor_account_id=None,
                payload={"status": ContestStatus.READY_FOR_ADJUDICATION.value},
            )

    async def _get_contest(self, contest_id: UUID) -> Contest:
        contest = await self.session.get(Contest, contest_id)
        if contest is None:
            raise ContestNotFoundError("contest not found")
        return contest

    async def _get_seats(self, contest_id: UUID) -> list[ContestSeat]:
        return list(
            (
                await self.session.scalars(
                    select(ContestSeat)
                    .where(ContestSeat.contest_id == contest_id)
                    .order_by(ContestSeat.seat_key)
                )
            ).all()
        )

    async def _get_contest_seat(self, contest_id: UUID, seat_id: UUID) -> ContestSeat:
        seat = await self.session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest_id,
                ContestSeat.id == seat_id,
            )
        )
        if seat is None:
            raise ContestNotFoundError("contest seat not found")
        return seat

    @staticmethod
    def _require_aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ContestValidationError("time must include a timezone")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    async def _build_view(
        self,
        contest: Contest,
        *,
        viewer: Account | None = None,
    ) -> ContestView:
        seats = await self._get_seats(contest.id)
        visible_submission_ids = {
            seat.current_submission_id
            for seat in seats
            if seat.current_submission_id is not None
            and viewer is not None
            and (
                viewer.id == seat.account_id
                or viewer.id == contest.owner_account_id
            )
        }
        submissions = {}
        if visible_submission_ids:
            submissions = {
                submission.id: submission
                for submission in (
                    await self.session.scalars(
                        select(Submission).where(Submission.id.in_(visible_submission_ids))
                    )
                ).all()
            }

        def seat_is_visible(seat: ContestSeat) -> bool:
            return viewer is not None and (
                viewer.id == seat.account_id or viewer.id == contest.owner_account_id
            )

        return ContestView(
            contest_id=contest.id,
            owner_account_id=contest.owner_account_id,
            problem_id=contest.problem_id,
            rule_version=contest.rule_version,
            status=contest.status,
            starts_at=contest.starts_at,
            solving_deadline=contest.solving_deadline,
            paused_previous_status=contest.paused_previous_status,
            paused_remaining_seconds=contest.paused_remaining_seconds,
            state_version=contest.state_version,
            event_sequence=contest.event_sequence,
            seats=[
                ContestSeatView(
                    seat_id=seat.id,
                    seat_key=seat.seat_key,
                    account_id=seat.account_id,
                    status=seat.status,
                    source=(
                        submissions[seat.current_submission_id].source
                        if seat_is_visible(seat)
                        and seat.current_submission_id in submissions
                        else None
                    ),
                    current_submission_id=(
                        seat.current_submission_id
                        if seat_is_visible(seat)
                        or contest.status
                        in {
                            ContestStatus.LOCKED.value,
                            ContestStatus.READY_FOR_ADJUDICATION.value,
                        }
                        else None
                    ),
                    submission_count=(seat.submission_count if seat_is_visible(seat) else 0),
                    evaluation_status=(seat.evaluation_status if seat_is_visible(seat) else None),
                    final_fact_type=(seat.final_fact_type if seat_is_visible(seat) else None),
                    evaluation_id=(seat.evaluation_id if seat_is_visible(seat) else None),
                    fact_summary=(seat.fact_summary if seat_is_visible(seat) else None),
                )
                for seat in seats
            ],
        )

    async def _get_subject_seat(self, contest: Contest, subject: Account) -> ContestSeat:
        seat = await self.session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == subject.id,
            )
        )
        if seat is None:
            raise ContestForbiddenError("contest seat access is forbidden")
        return seat

    async def _get_submission_from_request(self, request: ContestActionRequest) -> Submission:
        submission_id = UUID(str(request.payload["submission_id"]))
        submission = await self.session.get(Submission, submission_id)
        if submission is None:
            raise ContestNotFoundError("submission not found")
        return submission

    async def _ensure_visible(self, subject: Account, contest: Contest) -> None:
        if subject.id == contest.owner_account_id:
            return
        seat = await self.session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == subject.id,
            )
        )
        if seat is None:
            raise ContestForbiddenError("contest access is forbidden")

    async def _append_event(
        self,
        contest: Contest,
        *,
        event_type: str,
        actor_account_id: UUID | None,
        payload: dict[str, Any],
        seat_id: UUID | None = None,
    ) -> ContestEvent:
        contest.event_sequence += 1
        event = ContestEvent(
            contest_id=contest.id,
            sequence=contest.event_sequence,
            event_type=event_type,
            actor_account_id=actor_account_id,
            seat_id=seat_id,
            payload=payload,
        )
        self.session.add(event)
        return event

    @staticmethod
    def _payload_hash(request: ContestActionRequest) -> str:
        encoded = json.dumps(
            {"action_type": request.action_type.value, "payload": request.payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
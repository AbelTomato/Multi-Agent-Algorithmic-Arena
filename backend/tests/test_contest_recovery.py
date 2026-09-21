from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, SubjectType
from app.contests.contracts import ContestActionRequest
from app.contests.rules import ContestActionType, ContestSeatStatus, ContestStatus
from app.contests.service import (
    ContestStateError,
    ContestValidationError,
    ContestService,
)
from app.contests.worker import ContestAgentWorker, ContestLeaseConflictError
from app.database import Base
from app.models.contest import (
    Contest,
    ContestAction,
    ContestAgentAttempt,
    ContestAgentLease,
    ContestEvent,
    ContestSeat,
)
from app.models.evaluation import Evaluation
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.models.submission import Submission
from app.services.submissions import SubmissionService


@pytest.fixture
async def recovery_database(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'contest-recovery.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


def _window() -> tuple[datetime, datetime]:
    starts_at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    return starts_at, starts_at + timedelta(minutes=30)


async def _create_context(session: AsyncSession) -> tuple[Account, Account, Account, Problem]:
    owner = Account(subject_type=SubjectType.HUMAN, name="recovery-owner")
    first = Account(subject_type=SubjectType.HUMAN, name="recovery-human")
    second = Account(subject_type=SubjectType.AGENT, name="recovery-agent")
    problem = Problem(
        slug="recovery-problem",
        title="Recovery Problem",
        description="description",
        allowed_languages=["python"],
        active_case_version="v1",
    )
    session.add_all([owner, first, second, problem])
    await session.flush()
    session.add_all(
        [
            ProblemSubmissionPermission(account_id=first.id, problem_id=problem.id),
            ProblemSubmissionPermission(account_id=second.id, problem_id=problem.id),
        ]
    )
    await session.flush()
    return owner, first, second, problem


async def _start_solving(
    session: AsyncSession,
) -> tuple[ContestService, Account, Account, Account, Problem, Contest]:
    owner, first, second, problem = await _create_context(session)
    starts_at, deadline = _window()
    service = ContestService(session)
    contest = await service.create_draft(
        owner,
        problem_id=problem.id,
        first_account_id=first.id,
        second_account_id=second.id,
        starts_at=starts_at,
        solving_deadline=deadline,
    )
    await service.apply_action(
        owner,
        contest.id,
        ContestActionRequest(
            client_action_id="recovery-publish",
            expected_version=0,
            action_type=ContestActionType.PUBLISH,
            payload={},
        ),
    )
    await service.advance_time(contest.id, now=starts_at)
    await session.commit()
    return service, owner, first, second, problem, contest


async def _create_submission(
    session: AsyncSession,
    subject: Account,
    problem_id: int,
    *,
    source: str,
    supersedes_submission_id: UUID | None = None,
) -> Submission:
    submission = await SubmissionService(session).create(
        subject,
        problem_id=problem_id,
        language="python",
        source=source,
        supersedes_submission_id=supersedes_submission_id,
    )
    await session.flush()
    return submission


async def _submit(
    service: ContestService,
    session: AsyncSession,
    subject: Account,
    contest: Contest,
    submission: Submission,
    *,
    action_id: str,
    expected_version: int,
) -> None:
    await service.apply_action(
        subject,
        contest.id,
        ContestActionRequest(
            client_action_id=action_id,
            expected_version=expected_version,
            action_type=ContestActionType.SUBMIT_SUBMISSION,
            payload={"submission_id": str(submission.id)},
        ),
    )
    await session.commit()


def _evaluation(submission: Submission, *, status: str = "AC") -> Evaluation:
    return Evaluation(
        submission_id=submission.id,
        source_sha256=submission.source_sha256,
        language=submission.language,
        runtime_id=submission.runtime_id,
        case_version="v1",
        judge_status=status,
        case_count=1,
        executed_count=1,
        passed_count=1 if status == "AC" else 0,
        summary="objective evaluation summary",
        created_at=datetime(2026, 9, 21, 12, 31, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 21, 12, 31, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_pause_freezes_remaining_time_and_owner_resume_rebuilds_deadline(
    recovery_database,
) -> None:
    async with recovery_database() as session:
        service, owner, _, _, _, contest = await _start_solving(session)
        starts_at, original_deadline = _window()
        pause_at = starts_at + timedelta(minutes=10)

        paused = await service.pause_for_infrastructure(
            contest.id,
            reason_code="sandbox_unavailable",
            now=pause_at,
        )
        await session.commit()
        assert paused.status == ContestStatus.PAUSED_INFRASTRUCTURE.value
        assert paused.paused_previous_status == ContestStatus.SOLVING.value
        assert paused.paused_remaining_seconds == 20 * 60
        assert paused.solving_deadline == original_deadline

        frozen = await service.advance_time(
            contest.id,
            now=original_deadline + timedelta(hours=1),
        )
        assert frozen.status == ContestStatus.PAUSED_INFRASTRUCTURE.value
        assert frozen.state_version == paused.state_version
        assert frozen.paused_remaining_seconds == paused.paused_remaining_seconds

        resumed_at = pause_at + timedelta(minutes=5)
        resumed = await service.apply_action(
            owner,
            contest.id,
            ContestActionRequest(
                client_action_id="recovery-resume",
                expected_version=paused.state_version,
                action_type=ContestActionType.RESUME,
                payload={},
            ),
            now=resumed_at,
        )
        await session.commit()
        assert resumed.status == ContestStatus.SOLVING.value
        assert resumed.solving_deadline == resumed_at + timedelta(seconds=20 * 60)
        assert resumed.paused_previous_status is None
        assert resumed.paused_remaining_seconds is None

        with pytest.raises(ContestStateError):
            await service.apply_action(
                owner,
                contest.id,
                ContestActionRequest(
                    client_action_id="recovery-resume-again",
                    expected_version=resumed.state_version,
                    action_type=ContestActionType.RESUME,
                    payload={},
                ),
            )


@pytest.mark.asyncio
async def test_record_evaluation_requires_locked_current_submission_and_is_idempotently_rejected(
    recovery_database,
) -> None:
    async with recovery_database() as session:
        service, _, first, second, problem, contest = await _start_solving(session)
        first_submission = await _create_submission(
            session,
            first,
            problem.id,
            source="print('old')",
        )
        first_revision = await _create_submission(
            session,
            first,
            problem.id,
            source="print('current')",
            supersedes_submission_id=first_submission.id,
        )
        second_submission = await _create_submission(
            session,
            second,
            problem.id,
            source="print('agent')",
        )
        await session.commit()

        await _submit(
            service,
            session,
            first,
            contest,
            first_submission,
            action_id="recovery-submit-first-base",
            expected_version=2,
        )
        await _submit(
            service,
            session,
            first,
            contest,
            first_revision,
            action_id="recovery-submit-first",
            expected_version=3,
        )
        await _submit(
            service,
            session,
            second,
            contest,
            second_submission,
            action_id="recovery-submit-second",
            expected_version=4,
        )
        starts_at, deadline = _window()
        await service.advance_time(contest.id, now=deadline)
        await session.commit()

        stale_evaluation = _evaluation(first_submission)
        wrong_author_evaluation = _evaluation(second_submission)
        current_evaluation = _evaluation(first_revision)
        session.add_all([stale_evaluation, wrong_author_evaluation, current_evaluation])
        await session.flush()

        with pytest.raises(ContestValidationError):
            await service.record_evaluation(
                contest.id,
                (await session.scalar(
                    select(ContestSeat).where(
                        ContestSeat.contest_id == contest.id,
                        ContestSeat.account_id == first.id,
                    )
                )).id,
                stale_evaluation.id,
                now=deadline + timedelta(seconds=1),
            )

        first_seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == first.id,
            )
        )
        second_seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == second.id,
            )
        )
        assert first_seat is not None
        assert second_seat is not None

        with pytest.raises(ContestValidationError):
            await service.record_evaluation(
                contest.id,
                first_seat.id,
                wrong_author_evaluation.id,
                now=deadline + timedelta(seconds=1),
            )

        recorded = await service.record_evaluation(
            contest.id,
            first_seat.id,
            current_evaluation.id,
            now=deadline + timedelta(seconds=1),
        )
        await session.commit()
        assert recorded.status == ContestStatus.LOCKED.value
        assert first_seat.final_fact_type == "EVALUATION"
        assert first_seat.evaluation_status == "AC"
        assert first_seat.evaluation_id == current_evaluation.id
        assert first_seat.fact_summary == "objective evaluation summary"

        version_after_record = contest.state_version
        with pytest.raises(ContestValidationError):
            await service.record_evaluation(
                contest.id,
                first_seat.id,
                current_evaluation.id,
                now=deadline + timedelta(seconds=2),
            )
        assert contest.state_version == version_after_record

        second_evaluation = _evaluation(second_submission, status="WA")
        session.add(second_evaluation)
        await session.flush()
        ready = await service.record_evaluation(
            contest.id,
            second_seat.id,
            second_evaluation.id,
            now=deadline + timedelta(seconds=3),
        )
        await session.commit()
        assert ready.status == ContestStatus.READY_FOR_ADJUDICATION.value
        assert all(
            seat.final_fact_type == "EVALUATION"
            for seat in (first_seat, second_seat)
        )


@pytest.mark.asyncio
async def test_infrastructure_failure_and_no_submission_are_facts_not_results_and_can_ready_contest(
    recovery_database,
) -> None:
    async with recovery_database() as session:
        service, _, first, second, problem, contest = await _start_solving(session)
        first_submission = await _create_submission(
            session,
            first,
            problem.id,
            source="print('first')",
        )
        await session.commit()
        await _submit(
            service,
            session,
            first,
            contest,
            first_submission,
            action_id="failure-submit-first",
            expected_version=2,
        )
        withdrawn = await service.apply_action(
            second,
            contest.id,
            ContestActionRequest(
                client_action_id="failure-withdraw-second",
                expected_version=3,
                action_type=ContestActionType.WITHDRAW,
                payload={},
            ),
        )
        await session.commit()
        assert withdrawn.status == ContestStatus.SOLVING.value

        _, deadline = _window()
        locked = await service.advance_time(contest.id, now=deadline)
        await session.commit()
        assert locked.status == ContestStatus.LOCKED.value

        first_seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == first.id,
            )
        )
        second_seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == second.id,
            )
        )
        assert first_seat is not None
        assert second_seat is not None
        assert second_seat.status == ContestSeatStatus.WITHDRAWN.value

        ready = await service.record_infrastructure_failure(
            contest.id,
            first_seat.id,
            reason_code="judge_timeout",
            summary="judge did not complete before the infrastructure deadline",
            now=deadline + timedelta(seconds=1),
        )
        await session.commit()
        assert ready.status == ContestStatus.READY_FOR_ADJUDICATION.value
        assert first_seat.final_fact_type == "INFRASTRUCTURE_FAILURE"
        assert first_seat.evaluation_status == "INFRASTRUCTURE_FAILURE"
        assert first_seat.evaluation_id is None
        assert "AC" not in (first_seat.fact_summary or "")
        assert "WA" not in (first_seat.fact_summary or "")
        assert second_seat.final_fact_type == "WITHDRAWN"
        assert "winner" not in ready.model_dump_json().lower()

        failure_event = await session.scalar(
            select(ContestEvent).where(
                ContestEvent.contest_id == contest.id,
                ContestEvent.event_type == "infrastructure_failure",
            )
        )
        assert failure_event is not None
        assert "AC" not in str(failure_event.payload)
        assert "WA" not in str(failure_event.payload)
        assert "judge did not complete" not in str(failure_event.payload)


@pytest.mark.asyncio
async def test_cancelled_contest_cannot_resume_or_record_final_facts_and_phase_f_actions_are_rejected(
    recovery_database,
) -> None:
    async with recovery_database() as session:
        service, owner, first, _, problem, contest = await _start_solving(session)
        submission = await _create_submission(
            session,
            first,
            problem.id,
            source="print('cancelled')",
        )
        evaluation = _evaluation(submission)
        session.add(evaluation)
        await session.flush()
        await session.commit()

        cancelled = await service.apply_action(
            owner,
            contest.id,
            ContestActionRequest(
                client_action_id="recovery-cancel",
                expected_version=2,
                action_type=ContestActionType.CANCEL,
                payload={},
            ),
        )
        await session.commit()
        assert cancelled.status == ContestStatus.CANCELLED.value

        seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == first.id,
            )
        )
        assert seat is not None

        with pytest.raises(ContestStateError):
            await service.apply_action(
                owner,
                contest.id,
                ContestActionRequest(
                    client_action_id="recovery-resume-cancelled",
                    expected_version=cancelled.state_version,
                    action_type=ContestActionType.RESUME,
                    payload={},
                ),
            )
        with pytest.raises(ContestStateError):
            await service.record_evaluation(
                contest.id,
                seat.id,
                evaluation.id,
                now=datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
            )
        with pytest.raises(ContestStateError):
            await service.record_infrastructure_failure(
                contest.id,
                seat.id,
                reason_code="cancelled",
                summary="must not be written",
                now=datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
            )

        with pytest.raises(ValidationError):
            ContestActionRequest(
                client_action_id="phase-f-challenge",
                expected_version=cancelled.state_version,
                action_type="challenge",
                payload={},
            )


@pytest.mark.asyncio
async def test_agent_lease_is_exclusive_and_expired_lease_can_be_reclaimed(
    recovery_database,
) -> None:
    async with recovery_database() as session:
        _, _, _, agent, _, contest = await _start_solving(session)
        seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == agent.id,
            )
        )
        assert seat is not None
        first_now = datetime(2026, 9, 21, 12, 1, tzinfo=timezone.utc)
        worker = ContestAgentWorker(session, lease_seconds=30)

        first = await worker.acquire_lease(
            contest.id,
            seat.id,
            worker_id="worker-1",
            now=first_now,
        )
        first_attempt = await worker.start_attempt(
            first.lease_id,
            client_action_id="expired-agent-action",
            lease_token=first.lease_token,
            now=first_now,
        )
        await session.commit()
        assert first.attempt_number == 1
        assert len(first.lease_token) >= 32

        with pytest.raises(ContestLeaseConflictError):
            await ContestAgentWorker(session, lease_seconds=30).acquire_lease(
                contest.id,
                seat.id,
                worker_id="worker-2",
                now=first_now + timedelta(seconds=1),
            )

        await ContestAgentWorker(session, lease_seconds=30).recover_expired_leases(
            now=first.expires_at + timedelta(seconds=1)
        )
        expired_attempt = await session.get(ContestAgentAttempt, first_attempt.id)
        assert expired_attempt is not None
        assert expired_attempt.status == "EXPIRED"
        assert expired_attempt.failure_code == "lease_expired"
        second = await ContestAgentWorker(session, lease_seconds=30).acquire_lease(
            contest.id,
            seat.id,
            worker_id="worker-2",
            now=first.expires_at + timedelta(seconds=1),
        )
        await session.commit()

        assert second.attempt_number == 2
        assert second.lease_token != first.lease_token
        saved_first = await session.get(ContestAgentLease, first.lease_id)
        assert saved_first is not None
        assert saved_first.lease_token_hash != first.lease_token
        assert saved_first.released_at is not None


@pytest.mark.asyncio
async def test_agent_attempts_store_only_outcome_and_not_model_prompt_or_output(
    recovery_database,
) -> None:
    async with recovery_database() as session:
        _, _, _, agent, _, contest = await _start_solving(session)
        seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == agent.id,
            )
        )
        assert seat is not None
        now = datetime(2026, 9, 21, 12, 2, tzinfo=timezone.utc)
        worker = ContestAgentWorker(session, lease_seconds=30)
        lease = await worker.acquire_lease(contest.id, seat.id, "worker-1", now=now)
        attempt = await worker.start_attempt(
            lease.lease_id,
            client_action_id="agent-action-failed",
            lease_token=lease.lease_token,
            now=now,
        )
        failed = await worker.fail_attempt(
            lease.lease_id,
            client_action_id="agent-action-failed",
            lease_token=lease.lease_token,
            failure_code="provider_timeout",
            failure_summary="provider did not return an action",
            now=now + timedelta(seconds=5),
        )
        await session.commit()

        assert failed.id == attempt.id
        assert failed.status == "FAILED"
        assert failed.failure_code == "provider_timeout"
        assert not hasattr(failed, "prompt")
        assert not hasattr(failed, "model_output")
        assert not hasattr(failed, "credential")
        refreshed_seat = await session.get(ContestSeat, seat.id)
        refreshed_contest = await session.get(Contest, contest.id)
        assert refreshed_seat is not None
        assert refreshed_contest is not None
        assert refreshed_seat.status == ContestSeatStatus.ACTIVE.value
        assert refreshed_contest.status == ContestStatus.SOLVING.value


@pytest.mark.asyncio
async def test_completed_client_action_is_idempotent_across_worker_restart(
    recovery_database,
) -> None:
    async with recovery_database() as session:
        _, _, _, agent, problem, contest = await _start_solving(session)
        seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == agent.id,
            )
        )
        assert seat is not None
        submission = await _create_submission(
            session,
            agent,
            problem.id,
            source="print('agent')",
        )
        now = datetime(2026, 9, 21, 12, 3, tzinfo=timezone.utc)
        worker = ContestAgentWorker(session, lease_seconds=30)
        lease = await worker.acquire_lease(contest.id, seat.id, "worker-1", now=now)
        await worker.start_attempt(
            lease.lease_id,
            "agent-submit-1",
            lease_token=lease.lease_token,
            now=now,
        )
        action = ContestActionRequest(
            client_action_id="agent-submit-1",
            expected_version=2,
            action_type=ContestActionType.SUBMIT_SUBMISSION,
            payload={"submission_id": str(submission.id)},
        )
        await worker.complete_attempt(
            lease.lease_id,
            client_action_id="agent-submit-1",
            lease_token=lease.lease_token,
            action=action,
            now=now + timedelta(seconds=1),
        )
        await session.commit()
        contest_after_first = await session.get(Contest, contest.id)
        assert contest_after_first is not None
        first_version = contest_after_first.state_version

        restarted = ContestAgentWorker(session, lease_seconds=30)
        replayed = await restarted.complete_attempt(
            lease.lease_id,
            client_action_id="agent-submit-1",
            lease_token=lease.lease_token,
            action=action,
            now=now + timedelta(seconds=2),
        )
        await session.commit()
        contest_after_replay = await session.get(Contest, contest.id)
        actions = (
            await session.scalars(
                select(ContestAction).where(
                    ContestAction.contest_id == contest.id,
                    ContestAction.client_action_id == "agent-submit-1",
                )
            )
        ).all()

        assert replayed.status == "SUCCEEDED"
        assert contest_after_replay is not None
        assert contest_after_replay.state_version == first_version
        assert len(actions) == 1


@pytest.mark.asyncio
async def test_agent_context_contains_only_own_contest_summary(
    recovery_database,
) -> None:
    async with recovery_database() as session:
        _, _, human, agent, problem, contest = await _start_solving(session)
        human_submission = await _create_submission(
            session,
            human,
            problem.id,
            source="human-secret-source",
        )
        agent_submission = await _create_submission(
            session,
            agent,
            problem.id,
            source="agent-visible-source",
        )
        service = ContestService(session)
        await service.apply_action(
            human,
            contest.id,
            ContestActionRequest(
                client_action_id="human-context-submit",
                expected_version=2,
                action_type=ContestActionType.SUBMIT_SUBMISSION,
                payload={"submission_id": str(human_submission.id)},
            ),
        )
        await service.apply_action(
            agent,
            contest.id,
            ContestActionRequest(
                client_action_id="agent-context-submit",
                expected_version=3,
                action_type=ContestActionType.SUBMIT_SUBMISSION,
                payload={"submission_id": str(agent_submission.id)},
            ),
        )
        agent_seat = await session.scalar(
            select(ContestSeat).where(
                ContestSeat.contest_id == contest.id,
                ContestSeat.account_id == agent.id,
            )
        )
        assert agent_seat is not None

        context = await ContestAgentWorker(session).build_context(contest.id, agent_seat.id)
        serialized = context.model_dump_json()

        assert context.source == "agent-visible-source"
        assert "human-secret-source" not in serialized
        assert "prompt" not in serialized.lower()
        assert "hidden" not in serialized.lower()
        assert "expected_output" not in serialized
        assert "container" not in serialized.lower()
        assert "session" not in context.model_dump()
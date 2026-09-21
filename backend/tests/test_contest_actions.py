from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, SubjectType
from app.contests.contracts import ContestActionRequest
from app.contests.rules import ContestActionType, ContestSeatStatus, ContestStatus
from app.contests.service import (
    ContestActionConflictError,
    ContestForbiddenError,
    ContestNotFoundError,
    ContestStateError,
    ContestValidationError,
    ContestVersionConflictError,
    ContestService,
)
from app.database import Base
from app.models.contest import Contest, ContestAction, ContestEvent, ContestSeat
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.models.submission import Submission
from app.services.submissions import SubmissionService


@pytest.fixture
async def contest_database(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'contest-actions.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


async def _create_context(session: AsyncSession) -> tuple[Account, Account, Account, Problem]:
    owner = Account(subject_type=SubjectType.HUMAN, name="actions-owner")
    first = Account(subject_type=SubjectType.HUMAN, name="actions-human")
    second = Account(subject_type=SubjectType.AGENT, name="actions-agent")
    problem = Problem(
        slug="actions-problem",
        title="Actions Problem",
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


def _window() -> tuple[datetime, datetime]:
    starts_at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    return starts_at, starts_at + timedelta(minutes=30)


async def _create_draft(session: AsyncSession) -> tuple[ContestService, Account, Account, Account, Contest]:
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
    await session.commit()
    return service, owner, first, second, contest


async def _start_solving(
    session: AsyncSession,
) -> tuple[ContestService, Account, Account, Account, Problem, Contest]:
    service, owner, first, second, contest = await _create_draft(session)
    problem = await session.get(Problem, contest.problem_id)
    assert problem is not None
    await service.apply_action(
        owner,
        contest.id,
        ContestActionRequest(
            client_action_id="task-3-publish",
            expected_version=0,
            action_type=ContestActionType.PUBLISH,
            payload={},
        ),
    )
    starts_at, _ = _window()
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


@pytest.mark.asyncio
async def test_create_draft_initializes_two_assigned_seats_and_creation_event(
    contest_database,
) -> None:
    async with contest_database() as session:
        service, owner, first, second, contest = await _create_draft(session)

        assert owner.id != first.id != second.id
        assert contest.status == ContestStatus.DRAFT.value
        assert contest.rule_version == "stage-e-v1"
        assert contest.state_version == 0
        assert contest.event_sequence == 1

        seats = (
            await session.scalars(
                select(ContestSeat).where(ContestSeat.contest_id == contest.id).order_by(ContestSeat.seat_key)
            )
        ).all()
        assert [(seat.seat_key, seat.account_id, seat.status) for seat in seats] == [
            ("A", first.id, ContestSeatStatus.ASSIGNED.value),
            ("B", second.id, ContestSeatStatus.ASSIGNED.value),
        ]
        event = await session.scalar(
            select(ContestEvent).where(
                ContestEvent.contest_id == contest.id,
                ContestEvent.sequence == 1,
            )
        )
        assert event is not None
        assert event.event_type == "contest_created"
        assert event.payload == {"status": ContestStatus.DRAFT.value}


@pytest.mark.asyncio
async def test_create_draft_rejects_invalid_accounts_problem_and_time_window(contest_database) -> None:
    async with contest_database() as session:
        owner, first, second, problem = await _create_context(session)
        starts_at, deadline = _window()
        service = ContestService(session)

        with pytest.raises(ContestValidationError):
            await service.create_draft(
                owner,
                problem_id=problem.id,
                first_account_id=first.id,
                second_account_id=first.id,
                starts_at=starts_at,
                solving_deadline=deadline,
            )

        with pytest.raises(ContestValidationError):
            await service.create_draft(
                owner,
                problem_id=problem.id,
                first_account_id=first.id,
                second_account_id=second.id,
                starts_at=deadline,
                solving_deadline=deadline,
            )

        with pytest.raises(ContestNotFoundError):
            await service.create_draft(
                owner,
                problem_id=999,
                first_account_id=first.id,
                second_account_id=second.id,
                starts_at=starts_at,
                solving_deadline=deadline,
            )


@pytest.mark.asyncio
async def test_publish_start_and_deadline_are_ordered_and_idempotent(contest_database) -> None:
    async with contest_database() as session:
        service, owner, _, _, contest = await _create_draft(session)
        publish = ContestActionRequest(
            client_action_id="publish-actions",
            expected_version=0,
            action_type=ContestActionType.PUBLISH,
            payload={},
        )

        published = await service.apply_action(owner, contest.id, publish)
        await session.commit()
        assert published.status == ContestStatus.OPEN.value
        assert published.state_version == 1
        assert published.event_sequence == 2

        replayed = await service.apply_action(owner, contest.id, publish)
        assert replayed.model_dump() == published.model_dump()
        await session.commit()

        starts_at, deadline = _window()
        solving = await service.advance_time(contest.id, now=starts_at)
        await session.commit()
        assert solving.status == ContestStatus.SOLVING.value
        assert solving.state_version == 2
        assert solving.event_sequence == 3
        assert all(seat.status == ContestSeatStatus.ACTIVE.value for seat in solving.seats)

        locked = await service.advance_time(contest.id, now=deadline + timedelta(seconds=1))
        await session.commit()
        assert locked.status == ContestStatus.LOCKED.value
        assert locked.state_version == 3
        assert locked.event_sequence == 4

        events = (
            await session.scalars(
                select(ContestEvent)
                .where(ContestEvent.contest_id == contest.id)
                .order_by(ContestEvent.sequence)
            )
        ).all()
        assert [event.event_type for event in events] == [
            "contest_created",
            "contest_opened",
            "contest_started",
            "contest_locked",
        ]

        unchanged = await service.advance_time(contest.id, now=deadline + timedelta(minutes=1))
        assert unchanged.state_version == 3
        assert unchanged.event_sequence == 4


@pytest.mark.asyncio
async def test_owner_cancel_and_expected_version_reject_invalid_actions_without_writes(
    contest_database,
) -> None:
    async with contest_database() as session:
        service, owner, first, _, contest = await _create_draft(session)
        publish = ContestActionRequest(
            client_action_id="publish-for-conflict",
            expected_version=0,
            action_type=ContestActionType.PUBLISH,
            payload={},
        )
        await service.apply_action(owner, contest.id, publish)
        await session.commit()

        with pytest.raises(ContestVersionConflictError):
            await service.apply_action(
                owner,
                contest.id,
                ContestActionRequest(
                    client_action_id="stale-cancel",
                    expected_version=0,
                    action_type=ContestActionType.CANCEL,
                    payload={},
                ),
            )
        assert await session.scalar(
            select(func.count()).select_from(ContestAction).where(ContestAction.client_action_id == "stale-cancel")
        ) == 0

        with pytest.raises(ContestForbiddenError):
            await service.apply_action(
                first,
                contest.id,
                ContestActionRequest(
                    client_action_id="participant-cancel",
                    expected_version=1,
                    action_type=ContestActionType.CANCEL,
                    payload={},
                ),
            )

        cancelled = await service.apply_action(
            owner,
            contest.id,
            ContestActionRequest(
                client_action_id="owner-cancel",
                expected_version=1,
                action_type=ContestActionType.CANCEL,
                payload={},
            ),
        )
        await session.commit()
        assert cancelled.status == ContestStatus.CANCELLED.value
        assert cancelled.state_version == 2

        with pytest.raises(ContestStateError):
            await service.apply_action(
                owner,
                contest.id,
                ContestActionRequest(
                    client_action_id="cancel-again",
                    expected_version=2,
                    action_type=ContestActionType.CANCEL,
                    payload={},
                ),
            )

        assert await session.scalar(
            select(func.count()).select_from(ContestAction).where(ContestAction.contest_id == contest.id)
        ) == 2


@pytest.mark.asyncio
async def test_human_and_agent_submit_through_the_same_action_and_hide_opponent_source(
    contest_database,
) -> None:
    async with contest_database() as session:
        service, _, first, second, problem, contest = await _start_solving(session)
        human_submission = await _create_submission(
            session,
            first,
            problem.id,
            source="print('human')",
        )
        agent_submission = await _create_submission(
            session,
            second,
            problem.id,
            source="print('agent')",
        )
        await session.commit()

        human_result = await service.apply_action(
            first,
            contest.id,
            ContestActionRequest(
                client_action_id="human-submit",
                expected_version=2,
                action_type=ContestActionType.SUBMIT_SUBMISSION,
                payload={"submission_id": str(human_submission.id)},
            ),
        )
        await session.commit()
        assert human_result.state_version == 3
        human_seat = next(seat for seat in human_result.seats if seat.account_id == first.id)
        opponent_seat = next(seat for seat in human_result.seats if seat.account_id == second.id)
        assert human_seat.current_submission_id == human_submission.id
        assert human_seat.source == "print('human')"
        assert opponent_seat.source is None
        assert opponent_seat.current_submission_id is None

        agent_result = await service.apply_action(
            second,
            contest.id,
            ContestActionRequest(
                client_action_id="agent-submit",
                expected_version=3,
                action_type=ContestActionType.SUBMIT_SUBMISSION,
                payload={"submission_id": str(agent_submission.id)},
            ),
        )
        await session.commit()
        assert agent_result.status == ContestStatus.SOLVING.value
        agent_seat = next(seat for seat in agent_result.seats if seat.account_id == second.id)
        other_seat = next(seat for seat in agent_result.seats if seat.account_id == first.id)
        assert agent_seat.source == "print('agent')"
        assert other_seat.source is None


@pytest.mark.asyncio
async def test_submission_rejects_wrong_author_problem_cleaned_source_and_non_linear_versions(
    contest_database,
) -> None:
    async with contest_database() as session:
        service, _, first, second, problem, contest = await _start_solving(session)
        first_submission = await _create_submission(
            session,
            first,
            problem.id,
            source="print(1)",
        )
        other_submission = await _create_submission(
            session,
            second,
            problem.id,
            source="print(2)",
        )
        first_revision = await _create_submission(
            session,
            first,
            problem.id,
            source="print(3)",
            supersedes_submission_id=first_submission.id,
        )
        branched_revision = await _create_submission(
            session,
            first,
            problem.id,
            source="print(4)",
            supersedes_submission_id=first_submission.id,
        )
        first_submission.source = None
        first_submission.source_deleted_at = datetime.now(timezone.utc)
        await session.commit()

        async def submit(subject: Account, submission: Submission, action_id: str, version: int):
            return await service.apply_action(
                subject,
                contest.id,
                ContestActionRequest(
                    client_action_id=action_id,
                    expected_version=version,
                    action_type=ContestActionType.SUBMIT_SUBMISSION,
                    payload={"submission_id": str(submission.id)},
                ),
            )

        with pytest.raises(ContestForbiddenError):
            await submit(first, other_submission, "wrong-author", 2)

        with pytest.raises(ContestValidationError):
            await submit(first, first_submission, "cleaned-source", 2)

        created_problem = Problem(
            slug="other-actions-problem",
            title="Other Problem",
            description="other",
            allowed_languages=["python"],
            active_case_version="v1",
        )
        session.add(created_problem)
        await session.flush()
        session.add(ProblemSubmissionPermission(account_id=first.id, problem_id=created_problem.id))
        await session.flush()
        other_problem_submission = await _create_submission(
            session,
            first,
            created_problem.id,
            source="print(5)",
        )
        await session.commit()

        with pytest.raises(ContestValidationError):
            await submit(first, other_problem_submission, "wrong-problem", 2)

        first_submission.source = "print(1)"
        first_submission.source_deleted_at = None
        await session.commit()
        first_result = await submit(first, first_submission, "first-version", 2)
        await session.commit()
        assert first_result.state_version == 3

        second_result = await submit(first, first_revision, "second-version", 3)
        await session.commit()
        assert second_result.state_version == 4

        with pytest.raises(ContestValidationError):
            await submit(first, branched_revision, "branched-version", 4)


@pytest.mark.asyncio
async def test_submission_limit_is_three_linear_versions_and_locked_state_rejects_new_versions(
    contest_database,
) -> None:
    async with contest_database() as session:
        service, _, first, _, problem, contest = await _start_solving(session)
        submissions = [
            await _create_submission(session, first, problem.id, source="print(1)"),
        ]
        submissions.append(
            await _create_submission(
                session,
                first,
                problem.id,
                source="print(2)",
                supersedes_submission_id=submissions[-1].id,
            )
        )
        submissions.append(
            await _create_submission(
                session,
                first,
                problem.id,
                source="print(3)",
                supersedes_submission_id=submissions[-1].id,
            )
        )
        fourth = await _create_submission(
            session,
            first,
            problem.id,
            source="print(4)",
            supersedes_submission_id=submissions[-1].id,
        )
        await session.commit()

        version = 2
        for index, submission in enumerate(submissions, start=1):
            result = await service.apply_action(
                first,
                contest.id,
                ContestActionRequest(
                    client_action_id=f"linear-{index}",
                    expected_version=version,
                    action_type=ContestActionType.SUBMIT_SUBMISSION,
                    payload={"submission_id": str(submission.id)},
                ),
            )
            await session.commit()
            version = result.state_version

        assert next(seat for seat in result.seats if seat.account_id == first.id).submission_count == 3
        with pytest.raises(ContestValidationError):
            await service.apply_action(
                first,
                contest.id,
                ContestActionRequest(
                    client_action_id="linear-fourth",
                    expected_version=version,
                    action_type=ContestActionType.SUBMIT_SUBMISSION,
                    payload={"submission_id": str(fourth.id)},
                ),
            )

        _, deadline = _window()
        locked = await service.advance_time(contest.id, now=deadline + timedelta(seconds=1))
        await session.commit()
        assert locked.status == ContestStatus.LOCKED.value
        with pytest.raises(ContestStateError):
            await service.apply_action(
                first,
                contest.id,
                ContestActionRequest(
                    client_action_id="submit-after-lock",
                    expected_version=locked.state_version,
                    action_type=ContestActionType.SUBMIT_SUBMISSION,
                    payload={"submission_id": str(fourth.id)},
                ),
            )


@pytest.mark.asyncio
async def test_withdraw_is_irreversible_and_two_withdrawn_seats_cancel_contest(
    contest_database,
) -> None:
    async with contest_database() as session:
        service, _, first, second, _, contest = await _start_solving(session)
        first_withdrawn = await service.apply_action(
            first,
            contest.id,
            ContestActionRequest(
                client_action_id="withdraw-first",
                expected_version=2,
                action_type=ContestActionType.WITHDRAW,
                payload={},
            ),
        )
        await session.commit()
        first_seat = next(seat for seat in first_withdrawn.seats if seat.account_id == first.id)
        assert first_seat.status == ContestSeatStatus.WITHDRAWN.value
        assert first_withdrawn.status == ContestStatus.SOLVING.value

        with pytest.raises(ContestStateError):
            await service.apply_action(
                first,
                contest.id,
                ContestActionRequest(
                    client_action_id="withdraw-first-again",
                    expected_version=3,
                    action_type=ContestActionType.WITHDRAW,
                    payload={},
                ),
            )

        second_withdrawn = await service.apply_action(
            second,
            contest.id,
            ContestActionRequest(
                client_action_id="withdraw-second",
                expected_version=3,
                action_type=ContestActionType.WITHDRAW,
                payload={},
            ),
        )
        await session.commit()
        assert second_withdrawn.status == ContestStatus.CANCELLED.value
        assert all(seat.status == ContestSeatStatus.WITHDRAWN.value for seat in second_withdrawn.seats)


@pytest.mark.asyncio
async def test_same_action_key_with_different_payload_is_a_conflict_and_event_has_no_source(
    contest_database,
) -> None:
    async with contest_database() as session:
        service, _, first, _, problem, contest = await _start_solving(session)
        first_submission = await _create_submission(
            session,
            first,
            problem.id,
            source="secret-source",
        )
        second_submission = await _create_submission(
            session,
            first,
            problem.id,
            source="other-secret-source",
            supersedes_submission_id=first_submission.id,
        )
        await session.commit()
        request = ContestActionRequest(
            client_action_id="same-key",
            expected_version=2,
            action_type=ContestActionType.SUBMIT_SUBMISSION,
            payload={"submission_id": str(first_submission.id)},
        )
        first_result = await service.apply_action(first, contest.id, request)
        await session.commit()
        replayed = await service.apply_action(first, contest.id, request)
        assert replayed.model_dump() == first_result.model_dump()

        with pytest.raises(ContestActionConflictError):
            await service.apply_action(
                first,
                contest.id,
                ContestActionRequest(
                    client_action_id="same-key",
                    expected_version=3,
                    action_type=ContestActionType.SUBMIT_SUBMISSION,
                    payload={"submission_id": str(second_submission.id)},
                ),
            )

        event = await session.scalar(
            select(ContestEvent).where(
                ContestEvent.contest_id == contest.id,
                ContestEvent.event_type == "submission_accepted",
            )
        )
        assert event is not None
        serialized = str(event.payload).lower()
        assert "secret-source" not in serialized
        assert "prompt" not in serialized
        assert "hidden" not in serialized
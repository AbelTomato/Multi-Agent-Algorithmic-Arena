import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import Account, SubjectType
from app.contests.contracts import ContestActionRequest
from app.contests.rules import ContestActionType, ContestStatus
from app.database import Base
from app.models.contest import Contest, ContestAction, ContestEvent, ContestSeat
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.models.submission import Submission


def _load_migration(name: str):
    path = Path(__file__).parents[1] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_revision(connection, revision, operation: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(revision, operation)()


def test_stage_e_migration_creates_and_removes_only_stage_e_tables(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'stage-e.db'}")
    revisions = [
        _load_migration("0001_create_problems_table.py"),
        _load_migration("0002_create_evaluation_runs_table.py"),
        _load_migration("0003_create_accounts_submissions_evaluations.py"),
        _load_migration("0004_create_contests_and_recovery.py"),
    ]
    stage_e_tables = {
        "contests",
        "contest_seats",
        "contest_actions",
        "contest_events",
        "contest_agent_leases",
        "contest_agent_attempts",
    }

    with engine.begin() as connection:
        for revision in revisions:
            _run_revision(connection, revision, "upgrade")

        tables_after_upgrade = set(inspect(connection).get_table_names())
        assert stage_e_tables <= tables_after_upgrade
        assert {"accounts", "submissions", "evaluations"} <= tables_after_upgrade

        _run_revision(connection, revisions[-1], "downgrade")

        tables_after_downgrade = set(inspect(connection).get_table_names())
        assert stage_e_tables.isdisjoint(tables_after_downgrade)
        assert {"accounts", "submissions", "evaluations"} <= tables_after_downgrade

    engine.dispose()


def test_contest_action_contract_forbids_unknown_fields_and_payloads() -> None:
    valid_publish = ContestActionRequest(
        client_action_id="publish-1",
        expected_version=0,
        action_type=ContestActionType.PUBLISH,
        payload={},
    )
    valid_submission = ContestActionRequest(
        client_action_id="submit-1",
        expected_version=1,
        action_type=ContestActionType.SUBMIT_SUBMISSION,
        payload={"submission_id": str(uuid4())},
    )

    assert valid_publish.payload == {}
    assert set(valid_submission.payload) == {"submission_id"}

    with pytest.raises(ValidationError):
        ContestActionRequest(
            client_action_id="publish-2",
            expected_version=0,
            action_type=ContestActionType.PUBLISH,
            payload={},
            unexpected="rejected",
        )

    with pytest.raises(ValidationError):
        ContestActionRequest(
            client_action_id="publish-3",
            expected_version=-1,
            action_type=ContestActionType.PUBLISH,
            payload={},
        )

    with pytest.raises(ValidationError):
        ContestActionRequest(
            client_action_id="publish-4",
            expected_version=0,
            action_type=ContestActionType.PUBLISH,
            payload={"unexpected": True},
        )

    with pytest.raises(ValidationError):
        ContestActionRequest(
            client_action_id="submit-2",
            expected_version=1,
            action_type=ContestActionType.SUBMIT_SUBMISSION,
            payload={"submission_id": str(uuid4()), "source": "print(1)"},
        )

    with pytest.raises(ValidationError):
        ContestActionRequest(
            client_action_id="x" * 101,
            expected_version=0,
            action_type=ContestActionType.CANCEL,
            payload={},
        )


def test_contest_models_enforce_unique_seats_actions_and_event_sequences(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'contest-models.db'}")
    Base.metadata.create_all(engine)

    owner = Account(subject_type=SubjectType.HUMAN, name="contest-owner")
    first = Account(subject_type=SubjectType.HUMAN, name="contest-first")
    second = Account(subject_type=SubjectType.AGENT, name="contest-second")
    problem = Problem(
        slug="contest-problem",
        title="Contest Problem",
        description="description",
        allowed_languages=["python"],
        active_case_version="v1",
    )

    starts_at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    deadline = starts_at + timedelta(minutes=30)
    with Session(engine) as session:
        session.add_all([owner, first, second, problem])
        session.flush()
        session.add_all(
            [
                ProblemSubmissionPermission(account_id=first.id, problem_id=problem.id),
                ProblemSubmissionPermission(account_id=second.id, problem_id=problem.id),
            ]
        )
        submission = Submission(
            problem_id=problem.id,
            author_subject_id=first.id,
            language="python",
            runtime_id="python-3.11-v1",
            source="print(1)",
            source_sha256="a" * 64,
            retention_expires_at=deadline,
        )
        session.add(submission)
        session.flush()
        contest = Contest(
            owner_account_id=owner.id,
            problem_id=problem.id,
            rule_version="stage-e-v1",
            status=ContestStatus.DRAFT.value,
            starts_at=starts_at,
            solving_deadline=deadline,
            state_version=0,
        )
        session.add(contest)
        session.flush()
        session.add_all(
            [
                ContestSeat(
                    contest_id=contest.id,
                    seat_key="A",
                    account_id=first.id,
                    status="ASSIGNED",
                ),
                ContestSeat(
                    contest_id=contest.id,
                    seat_key="B",
                    account_id=second.id,
                    status="ASSIGNED",
                ),
            ]
        )
        session.flush()

        event = ContestEvent(
            contest_id=contest.id,
            sequence=1,
            event_type="contest_created",
            actor_account_id=owner.id,
            payload={"status": ContestStatus.DRAFT.value},
        )
        session.add(event)
        session.flush()
        session.add(
            ContestAction(
                contest_id=contest.id,
                client_action_id="action-1",
                actor_account_id=owner.id,
                action_type=ContestActionType.PUBLISH.value,
                payload_hash="b" * 64,
                result_payload={"status": ContestStatus.OPEN.value},
                result_state_version=1,
                result_event_sequence=2,
            )
        )
        session.commit()

        duplicate_seat = ContestSeat(
            contest_id=contest.id,
            seat_key="C",
            account_id=first.id,
            status="ASSIGNED",
        )
        session.add(duplicate_seat)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        duplicate_action = ContestAction(
            contest_id=contest.id,
            client_action_id="action-1",
            actor_account_id=owner.id,
            action_type=ContestActionType.CANCEL.value,
            payload_hash="c" * 64,
            result_payload={"status": ContestStatus.CANCELLED.value},
            result_state_version=2,
            result_event_sequence=3,
        )
        session.add(duplicate_action)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        duplicate_event = ContestEvent(
            contest_id=contest.id,
            sequence=1,
            event_type="duplicate",
            payload={},
        )
        session.add(duplicate_event)
        with pytest.raises(IntegrityError):
            session.flush()

    engine.dispose()
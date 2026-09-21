from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.contests.rules import (
    ContestActionType,
    ContestSeatStatus,
    ContestStatus,
)
from app.database import Base


class Contest(Base):
    __tablename__ = "contests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'OPEN', 'SOLVING', 'PAUSED_INFRASTRUCTURE', "
            "'LOCKED', 'READY_FOR_ADJUDICATION', 'CANCELLED')",
            name="ck_contests_status",
        ),
        CheckConstraint("state_version >= 0", name="ck_contests_state_version_nonnegative"),
        CheckConstraint(
            "solving_deadline > starts_at",
            name="ck_contests_deadline_after_start",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False, default="stage-e-v1")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ContestStatus.DRAFT.value
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    solving_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paused_previous_status: Mapped[str] = mapped_column(String(32), nullable=True)
    paused_remaining_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ContestSeat(Base):
    __tablename__ = "contest_seats"
    __table_args__ = (
        UniqueConstraint("contest_id", "seat_key", name="uq_contest_seats_contest_seat_key"),
        UniqueConstraint("contest_id", "account_id", name="uq_contest_seats_contest_account"),
        CheckConstraint(
            "status IN ('ASSIGNED', 'ACTIVE', 'WITHDRAWN')",
            name="ck_contest_seats_status",
        ),
        CheckConstraint("submission_count >= 0", name="ck_contest_seats_submission_count"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seat_key: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContestSeatStatus.ASSIGNED.value
    )
    current_submission_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("submissions.id", ondelete="RESTRICT"), nullable=True
    )
    submission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluation_status: Mapped[str] = mapped_column(String(40), nullable=True)
    final_fact_type: Mapped[str] = mapped_column(String(40), nullable=True)
    evaluation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluations.id", ondelete="RESTRICT"), nullable=True
    )
    fact_summary: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    withdrawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class ContestAction(Base):
    __tablename__ = "contest_actions"
    __table_args__ = (
        UniqueConstraint(
            "contest_id",
            "client_action_id",
            name="uq_contest_actions_contest_client_action",
        ),
        CheckConstraint(
            "action_type IN ('publish', 'cancel', 'resume', 'submit_submission', 'withdraw')",
            name="ck_contest_actions_action_type",
        ),
        CheckConstraint("result_state_version >= 0", name="ck_contest_actions_result_version"),
        CheckConstraint("result_event_sequence >= 0", name="ck_contest_actions_result_sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_action_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContestEvent(Base):
    __tablename__ = "contest_events"
    __table_args__ = (
        UniqueConstraint("contest_id", "sequence", name="uq_contest_events_contest_sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    actor_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    seat_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contest_seats.id", ondelete="CASCADE"), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContestAgentLease(Base):
    __tablename__ = "contest_agent_leases"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="ck_contest_agent_leases_attempt_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seat_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contest_seats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContestAgentAttempt(Base):
    __tablename__ = "contest_agent_attempts"
    __table_args__ = (
        UniqueConstraint("lease_id", "attempt_number", name="uq_contest_agent_attempts_lease_attempt"),
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'EXPIRED')",
            name="ck_contest_agent_attempts_status",
        ),
        CheckConstraint("attempt_number > 0", name="ck_contest_agent_attempts_attempt_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seat_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contest_seats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lease_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contest_agent_leases.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    client_action_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    failure_code: Mapped[str] = mapped_column(String(60), nullable=True)
    failure_summary: Mapped[str] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "Contest",
    "ContestAction",
    "ContestAgentAttempt",
    "ContestAgentLease",
    "ContestEvent",
    "ContestSeat",
]
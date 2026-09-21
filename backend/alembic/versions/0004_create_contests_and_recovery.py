"""create stage E contest actions and recovery tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_account_id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.String(length=40), nullable=False, server_default="stage-e-v1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("solving_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paused_previous_status", sa.String(length=32), nullable=True),
        sa.Column("paused_remaining_seconds", sa.Integer(), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'OPEN', 'SOLVING', 'PAUSED_INFRASTRUCTURE', 'LOCKED', "
            "'READY_FOR_ADJUDICATION', 'CANCELLED')",
            name="ck_contests_status",
        ),
        sa.CheckConstraint("state_version >= 0", name="ck_contests_state_version_nonnegative"),
        sa.CheckConstraint("solving_deadline > starts_at", name="ck_contests_deadline_after_start"),
        sa.ForeignKeyConstraint(["owner_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contests_owner_account_id", "contests", ["owner_account_id"])
    op.create_index("ix_contests_problem_id", "contests", ["problem_id"])

    op.create_table(
        "contest_seats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contest_id", sa.Uuid(), nullable=False),
        sa.Column("seat_key", sa.String(length=20), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ASSIGNED"),
        sa.Column("current_submission_id", sa.Uuid(), nullable=True),
        sa.Column("submission_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evaluation_status", sa.String(length=40), nullable=True),
        sa.Column("final_fact_type", sa.String(length=40), nullable=True),
        sa.Column("evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("fact_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ASSIGNED', 'ACTIVE', 'WITHDRAWN')",
            name="ck_contest_seats_status",
        ),
        sa.CheckConstraint("submission_count >= 0", name="ck_contest_seats_submission_count"),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_submission_id"], ["submissions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contest_id", "seat_key", name="uq_contest_seats_contest_seat_key"),
        sa.UniqueConstraint("contest_id", "account_id", name="uq_contest_seats_contest_account"),
    )
    op.create_index("ix_contest_seats_contest_id", "contest_seats", ["contest_id"])
    op.create_index("ix_contest_seats_account_id", "contest_seats", ["account_id"])

    op.create_table(
        "contest_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contest_id", sa.Uuid(), nullable=False),
        sa.Column("client_action_id", sa.String(length=100), nullable=False),
        sa.Column("actor_account_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("result_state_version", sa.Integer(), nullable=False),
        sa.Column("result_event_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "action_type IN ('publish', 'cancel', 'resume', 'submit_submission', 'withdraw')",
            name="ck_contest_actions_action_type",
        ),
        sa.CheckConstraint("result_state_version >= 0", name="ck_contest_actions_result_version"),
        sa.CheckConstraint("result_event_sequence >= 0", name="ck_contest_actions_result_sequence"),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "contest_id", "client_action_id", name="uq_contest_actions_contest_client_action"
        ),
    )
    op.create_index("ix_contest_actions_contest_id", "contest_actions", ["contest_id"])
    op.create_index("ix_contest_actions_actor_account_id", "contest_actions", ["actor_account_id"])

    op.create_table(
        "contest_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contest_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("actor_account_id", sa.Uuid(), nullable=True),
        sa.Column("seat_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seat_id"], ["contest_seats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contest_id", "sequence", name="uq_contest_events_contest_sequence"),
    )
    op.create_index("ix_contest_events_contest_id", "contest_events", ["contest_id"])

    op.create_table(
        "contest_agent_leases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contest_id", sa.Uuid(), nullable=False),
        sa.Column("seat_id", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("attempt_number > 0", name="ck_contest_agent_leases_attempt_number"),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seat_id"], ["contest_seats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contest_agent_leases_contest_id", "contest_agent_leases", ["contest_id"])
    op.create_index("ix_contest_agent_leases_seat_id", "contest_agent_leases", ["seat_id"])

    op.create_table(
        "contest_agent_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contest_id", sa.Uuid(), nullable=False),
        sa.Column("seat_id", sa.Uuid(), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("client_action_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="RUNNING"),
        sa.Column("failure_code", sa.String(length=60), nullable=True),
        sa.Column("failure_summary", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'EXPIRED')",
            name="ck_contest_agent_attempts_status",
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_contest_agent_attempts_attempt_number"),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seat_id"], ["contest_seats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lease_id"], ["contest_agent_leases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lease_id", "attempt_number", name="uq_contest_agent_attempts_lease_attempt"),
    )
    op.create_index("ix_contest_agent_attempts_contest_id", "contest_agent_attempts", ["contest_id"])
    op.create_index("ix_contest_agent_attempts_seat_id", "contest_agent_attempts", ["seat_id"])


def downgrade() -> None:
    op.drop_index("ix_contest_agent_attempts_seat_id", table_name="contest_agent_attempts")
    op.drop_index("ix_contest_agent_attempts_contest_id", table_name="contest_agent_attempts")
    op.drop_table("contest_agent_attempts")
    op.drop_index("ix_contest_agent_leases_seat_id", table_name="contest_agent_leases")
    op.drop_index("ix_contest_agent_leases_contest_id", table_name="contest_agent_leases")
    op.drop_table("contest_agent_leases")
    op.drop_index("ix_contest_events_contest_id", table_name="contest_events")
    op.drop_table("contest_events")
    op.drop_index("ix_contest_actions_actor_account_id", table_name="contest_actions")
    op.drop_index("ix_contest_actions_contest_id", table_name="contest_actions")
    op.drop_table("contest_actions")
    op.drop_index("ix_contest_seats_account_id", table_name="contest_seats")
    op.drop_index("ix_contest_seats_contest_id", table_name="contest_seats")
    op.drop_table("contest_seats")
    op.drop_index("ix_contests_problem_id", table_name="contests")
    op.drop_index("ix_contests_owner_account_id", table_name="contests")
    op.drop_table("contests")
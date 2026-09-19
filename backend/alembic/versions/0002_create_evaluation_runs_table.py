"""create evaluation runs table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-19

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_key_hash", sa.String(length=64), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("problem_slug", sa.String(length=100), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("run_status", sa.String(length=20), nullable=False),
        sa.Column("judge_status", sa.String(length=10), nullable=True),
        sa.Column("case_version", sa.String(length=50), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("executed_count", sa.Integer(), nullable=True),
        sa.Column("passed_count", sa.Integer(), nullable=True),
        sa.Column("failed_case_index", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_category", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint("case_count >= 0", name="ck_evaluation_runs_case_count"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_evaluation_runs_duration_ms",
        ),
        sa.CheckConstraint(
            "error_category IS NULL OR error_category IN "
            "('AGENT_ERROR', 'CONTROLLER_BUSY', 'CONTROLLER_UNAVAILABLE', 'CONTROLLER_TIMEOUT', "
            "'CONTROLLER_RESPONSE_ERROR', 'EVALUATION_TIMEOUT', 'INTERNAL_ERROR')",
            name="ck_evaluation_runs_error_category",
        ),
        sa.CheckConstraint(
            "executed_count IS NULL OR executed_count >= 0",
            name="ck_evaluation_runs_executed_count",
        ),
        sa.CheckConstraint(
            "(run_status NOT IN ('FAILED', 'TIMED_OUT', 'REJECTED', 'INTERRUPTED')) OR "
            "(error_category IS NOT NULL AND summary IS NOT NULL AND finished_at IS NOT NULL "
            "AND duration_ms IS NOT NULL AND judge_status IS NULL)",
            name="ck_evaluation_runs_failure_shape",
        ),
        sa.CheckConstraint(
            "failed_case_index IS NULL OR failed_case_index >= 0",
            name="ck_evaluation_runs_failed_case_index",
        ),
        sa.CheckConstraint(
            "judge_status IS NULL OR judge_status IN ('AC', 'WA', 'RE', 'TLE', 'MLE', 'OLE', 'UKE')",
            name="ck_evaluation_runs_judge_status",
        ),
        sa.CheckConstraint("language = 'python'", name="ck_evaluation_runs_language"),
        sa.CheckConstraint(
            "passed_count IS NULL OR passed_count >= 0",
            name="ck_evaluation_runs_passed_count",
        ),
        sa.CheckConstraint(
            "run_status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'REJECTED', 'INTERRUPTED')",
            name="ck_evaluation_runs_run_status",
        ),
        sa.CheckConstraint(
            "(run_status != 'RUNNING') OR "
            "(judge_status IS NULL AND error_category IS NULL AND summary IS NULL "
            "AND finished_at IS NULL AND duration_ms IS NULL)",
            name="ck_evaluation_runs_running_shape",
        ),
        sa.CheckConstraint(
            "length(session_key_hash) = 64",
            name="ck_evaluation_runs_session_hash_length",
        ),
        sa.CheckConstraint(
            "(run_status != 'SUCCEEDED') OR "
            "(judge_status IS NOT NULL AND executed_count IS NOT NULL AND passed_count IS NOT NULL "
            "AND summary IS NOT NULL AND finished_at IS NOT NULL AND duration_ms IS NOT NULL "
            "AND error_category IS NULL)",
            name="ck_evaluation_runs_succeeded_shape",
        ),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_runs_session_key_hash",
        "evaluation_runs",
        ["session_key_hash"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_session_created_id",
        "evaluation_runs",
        ["session_key_hash", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_session_problem_created_id",
        "evaluation_runs",
        ["session_key_hash", "problem_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_session_problem_created_id", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_session_created_id", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_session_key_hash", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
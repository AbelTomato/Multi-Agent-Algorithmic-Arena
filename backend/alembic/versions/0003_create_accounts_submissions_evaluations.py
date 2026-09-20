"""create stage D account, submission and evaluation tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "problems",
        sa.Column(
            "allowed_languages",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"python\"]'"),
        ),
    )
    op.add_column(
        "problems",
        sa.Column("active_case_version", sa.String(length=50), nullable=False, server_default="v1"),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("subject_type IN ('human', 'agent')", name="ck_accounts_subject_type"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_access_tokens_hash_length"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_access_tokens_account_id", "access_tokens", ["account_id"])
    op.create_index("ix_access_tokens_token_hash", "access_tokens", ["token_hash"])

    op.create_table(
        "problem_submission_permissions",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(length=20), nullable=False, server_default="submit"),
        sa.CheckConstraint("permission = 'submit'", name="ck_submission_permissions_permission"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id", "problem_id"),
    )

    op.create_table(
        "submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("author_subject_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("runtime_id", sa.String(length=80), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("supersedes_submission_id", sa.Uuid(), nullable=True),
        sa.Column("source_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("language IN ('python', 'cpp')", name="ck_submissions_language"),
        sa.CheckConstraint("length(source) <= 65536", name="ck_submissions_source_length"),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_submissions_sha256_length"),
        sa.ForeignKeyConstraint(["author_subject_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_submission_id"], ["submissions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_submissions_problem_id", "submissions", ["problem_id"])
    op.create_index("ix_submissions_author_subject_id", "submissions", ["author_subject_id"])

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("runtime_id", sa.String(length=80), nullable=False),
        sa.Column("case_version", sa.String(length=50), nullable=False),
        sa.Column("judge_status", sa.String(length=10), nullable=True),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("executed_count", sa.Integer(), nullable=True),
        sa.Column("passed_count", sa.Integer(), nullable=True),
        sa.Column("failed_case_index", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "judge_status IS NULL OR judge_status IN ('AC', 'WA', 'RE', 'TLE', 'MLE', 'OLE', 'UKE')",
            name="ck_evaluations_judge_status",
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_evaluations_sha256_length"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluations_submission_id", "evaluations", ["submission_id"])


def downgrade() -> None:
    op.drop_index("ix_evaluations_submission_id", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_submissions_author_subject_id", table_name="submissions")
    op.drop_index("ix_submissions_problem_id", table_name="submissions")
    op.drop_table("submissions")
    op.drop_table("problem_submission_permissions")
    op.drop_index("ix_access_tokens_token_hash", table_name="access_tokens")
    op.drop_index("ix_access_tokens_account_id", table_name="access_tokens")
    op.drop_table("access_tokens")
    op.drop_table("accounts")
    op.drop_column("problems", "allowed_languages")
    op.drop_column("problems", "active_case_version")
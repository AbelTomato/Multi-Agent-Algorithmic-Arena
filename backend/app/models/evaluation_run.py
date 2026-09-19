"""评测运行记录模型，只保存受控摘要和生命周期状态。"""

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.database import Base


class EvaluationRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    REJECTED = "REJECTED"
    INTERRUPTED = "INTERRUPTED"


class EvaluationErrorCategory(StrEnum):
    AGENT_ERROR = "AGENT_ERROR"
    CONTROLLER_BUSY = "CONTROLLER_BUSY"
    CONTROLLER_UNAVAILABLE = "CONTROLLER_UNAVAILABLE"
    CONTROLLER_TIMEOUT = "CONTROLLER_TIMEOUT"
    CONTROLLER_RESPONSE_ERROR = "CONTROLLER_RESPONSE_ERROR"
    EVALUATION_TIMEOUT = "EVALUATION_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class UTCDateTime(TypeDecorator[datetime]):
    """在 PostgreSQL 和 SQLite 测试中统一返回 timezone-aware UTC。"""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


RUN_STATUSES = tuple(status.value for status in EvaluationRunStatus)
ERROR_CATEGORIES = tuple(category.value for category in EvaluationErrorCategory)
JUDGE_STATUSES = ("AC", "WA", "RE", "TLE", "MLE", "OLE", "UKE")
TERMINAL_FAILURE_STATUSES = (
    EvaluationRunStatus.FAILED.value,
    EvaluationRunStatus.TIMED_OUT.value,
    EvaluationRunStatus.REJECTED.value,
    EvaluationRunStatus.INTERRUPTED.value,
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            f"run_status IN ({_sql_values(RUN_STATUSES)})",
            name="ck_evaluation_runs_run_status",
        ),
        CheckConstraint(
            f"judge_status IS NULL OR judge_status IN ({_sql_values(JUDGE_STATUSES)})",
            name="ck_evaluation_runs_judge_status",
        ),
        CheckConstraint(
            f"error_category IS NULL OR error_category IN ({_sql_values(ERROR_CATEGORIES)})",
            name="ck_evaluation_runs_error_category",
        ),
        CheckConstraint("length(session_key_hash) = 64", name="ck_evaluation_runs_session_hash_length"),
        CheckConstraint("language = 'python'", name="ck_evaluation_runs_language"),
        CheckConstraint("case_count >= 0", name="ck_evaluation_runs_case_count"),
        CheckConstraint(
            "executed_count IS NULL OR executed_count >= 0",
            name="ck_evaluation_runs_executed_count",
        ),
        CheckConstraint(
            "passed_count IS NULL OR passed_count >= 0",
            name="ck_evaluation_runs_passed_count",
        ),
        CheckConstraint(
            "failed_case_index IS NULL OR failed_case_index >= 0",
            name="ck_evaluation_runs_failed_case_index",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_evaluation_runs_duration_ms",
        ),
        CheckConstraint(
            "(run_status != 'RUNNING') OR "
            "(judge_status IS NULL AND error_category IS NULL AND summary IS NULL "
            "AND finished_at IS NULL AND duration_ms IS NULL)",
            name="ck_evaluation_runs_running_shape",
        ),
        CheckConstraint(
            "(run_status != 'SUCCEEDED') OR "
            "(judge_status IS NOT NULL AND executed_count IS NOT NULL AND passed_count IS NOT NULL "
            "AND summary IS NOT NULL AND finished_at IS NOT NULL AND duration_ms IS NOT NULL "
            "AND error_category IS NULL)",
            name="ck_evaluation_runs_succeeded_shape",
        ),
        CheckConstraint(
            f"(run_status NOT IN ({_sql_values(TERMINAL_FAILURE_STATUSES)})) OR "
            "(error_category IS NOT NULL AND summary IS NOT NULL AND finished_at IS NOT NULL "
            "AND duration_ms IS NOT NULL AND judge_status IS NULL)",
            name="ck_evaluation_runs_failure_shape",
        ),
        Index("ix_evaluation_runs_session_key_hash", "session_key_hash"),
        Index(
            "ix_evaluation_runs_session_created_id",
            "session_key_hash",
            "created_at",
            "id",
        ),
        Index(
            "ix_evaluation_runs_session_problem_created_id",
            "session_key_hash",
            "problem_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    problem_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("problems.id", ondelete="RESTRICT"),
        nullable=False,
    )
    problem_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="python")
    run_status: Mapped[str] = mapped_column(String(20), nullable=False)
    judge_status: Mapped[str] = mapped_column(String(10), nullable=True)
    case_version: Mapped[str] = mapped_column(String(50), nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_count: Mapped[int] = mapped_column(Integer, nullable=True)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=True)
    failed_case_index: Mapped[int] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    error_category: Mapped[str] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=True)
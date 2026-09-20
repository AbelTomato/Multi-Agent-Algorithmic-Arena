from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(
            "judge_status IS NULL OR judge_status IN ('AC', 'WA', 'RE', 'TLE', 'MLE', 'OLE', 'UKE')",
            name="ck_evaluations_judge_status",
        ),
        CheckConstraint("length(source_sha256) = 64", name="ck_evaluations_sha256_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("submissions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    runtime_id: Mapped[str] = mapped_column(String(80), nullable=False)
    case_version: Mapped[str] = mapped_column(String(50), nullable=False)
    judge_status: Mapped[str] = mapped_column(String(10), nullable=True)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_count: Mapped[int] = mapped_column(Integer, nullable=True)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=True)
    failed_case_index: Mapped[int] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=True)
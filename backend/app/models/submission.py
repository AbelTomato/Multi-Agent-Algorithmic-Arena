from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


LANGUAGE_RUNTIME_IDS = {
    "python": "python-3.11-v1",
    "cpp": "cpp-gcc-14-cpp20-v1",
}


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint("language IN ('python', 'cpp')", name="ck_submissions_language"),
        CheckConstraint("length(source) <= 65536", name="ck_submissions_source_length"),
        CheckConstraint("length(source_sha256) = 64", name="ck_submissions_sha256_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    author_subject_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    runtime_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_submission_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("submissions.id", ondelete="RESTRICT"), nullable=True
    )
    source_deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_id: int = Field(gt=0)
    language: str
    source: str
    supersedes_submission_id: UUID | None = None


class SubmissionRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_id: int = Field(gt=0)
    language: str
    source: str


class SubmissionResponse(BaseModel):
    submission_id: UUID
    problem_id: int
    author_subject_id: UUID
    language: str
    runtime_id: str
    source: str | None
    source_sha256: str
    supersedes_submission_id: UUID | None
    source_deleted_at: datetime | None
    retention_expires_at: datetime
    created_at: datetime
    replayable: bool

    @classmethod
    def from_submission(cls, submission) -> "SubmissionResponse":
        return cls(
            submission_id=submission.id,
            problem_id=submission.problem_id,
            author_subject_id=submission.author_subject_id,
            language=submission.language,
            runtime_id=submission.runtime_id,
            source=submission.source,
            source_sha256=submission.source_sha256,
            supersedes_submission_id=submission.supersedes_submission_id,
            source_deleted_at=submission.source_deleted_at,
            retention_expires_at=submission.retention_expires_at,
            created_at=submission.created_at,
            replayable=submission.source is not None and submission.source_deleted_at is None,
        )
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SubmissionEvaluationResponse(BaseModel):
    evaluation_id: UUID
    submission_id: UUID
    source_sha256: str
    language: str
    runtime_id: str
    case_version: str
    judge_status: str | None
    case_count: int
    executed_count: int | None
    passed_count: int | None
    failed_case_index: int | None
    summary: str | None
    created_at: datetime
    finished_at: datetime | None
    duration_ms: int | None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_evaluation(cls, evaluation) -> "SubmissionEvaluationResponse":
        return cls(
            evaluation_id=evaluation.id,
            submission_id=evaluation.submission_id,
            source_sha256=evaluation.source_sha256,
            language=evaluation.language,
            runtime_id=evaluation.runtime_id,
            case_version=evaluation.case_version,
            judge_status=evaluation.judge_status,
            case_count=evaluation.case_count,
            executed_count=evaluation.executed_count,
            passed_count=evaluation.passed_count,
            failed_case_index=evaluation.failed_case_index,
            summary=evaluation.summary,
            created_at=evaluation.created_at,
            finished_at=evaluation.finished_at,
            duration_ms=evaluation.duration_ms,
        )
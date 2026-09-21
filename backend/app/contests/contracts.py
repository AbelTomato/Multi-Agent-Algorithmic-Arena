from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contests.rules import ContestActionType, EMPTY_PAYLOAD_ACTION_TYPES


class ContestActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=0)
    action_type: ContestActionType
    payload: dict[str, object]

    @model_validator(mode="after")
    def validate_action_payload(self) -> "ContestActionRequest":
        payload_keys = set(self.payload)
        if self.action_type in EMPTY_PAYLOAD_ACTION_TYPES:
            if payload_keys:
                raise ValueError(f"{self.action_type.value} does not accept a payload")
            return self

        if self.action_type is ContestActionType.SUBMIT_SUBMISSION:
            if payload_keys != {"submission_id"}:
                raise ValueError("submit_submission payload must contain only submission_id")
            try:
                submission_id = UUID(str(self.payload["submission_id"]))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("submission_id must be a valid UUID") from error
            self.payload = {"submission_id": str(submission_id)}
            return self

        raise ValueError(f"unsupported contest action: {self.action_type.value}")


class ContestSeatView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat_id: UUID
    seat_key: str
    account_id: UUID
    status: str
    source: str | None = None
    current_submission_id: UUID | None = None
    submission_count: int = 0
    evaluation_status: str | None = None
    final_fact_type: str | None = None
    evaluation_id: UUID | None = None
    fact_summary: str | None = None


class ContestView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contest_id: UUID
    owner_account_id: UUID
    problem_id: int
    rule_version: str
    status: str
    starts_at: datetime
    solving_deadline: datetime
    paused_previous_status: str | None = None
    paused_remaining_seconds: int | None = None
    state_version: int
    event_sequence: int
    seats: list[ContestSeatView]


class ContestActionResponse(ContestView):
    action_id: UUID
    client_action_id: str


class ContestLeaseGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: UUID
    contest_id: UUID
    seat_id: UUID
    worker_id: str
    attempt_number: int = Field(gt=0)
    expires_at: datetime
    lease_token: str = Field(min_length=32)


class ContestAgentContext(BaseModel):
    """仅向 Agent Driver 暴露当前席位有权消费的比赛摘要。"""

    model_config = ConfigDict(extra="forbid")

    contest_id: UUID
    seat_id: UUID
    seat_key: str
    problem_id: int
    rule_version: str
    status: str
    state_version: int
    event_sequence: int
    current_submission_id: UUID | None = None
    submission_count: int = 0
    source: str | None = None
    language: str | None = None
    runtime_id: str | None = None
    evaluation_status: str | None = None
    final_fact_type: str | None = None
    fact_summary: str | None = None
from enum import StrEnum


RULE_VERSION = "stage-e-v1"


class ContestStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SOLVING = "SOLVING"
    PAUSED_INFRASTRUCTURE = "PAUSED_INFRASTRUCTURE"
    LOCKED = "LOCKED"
    READY_FOR_ADJUDICATION = "READY_FOR_ADJUDICATION"
    CANCELLED = "CANCELLED"


class ContestSeatStatus(StrEnum):
    ASSIGNED = "ASSIGNED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ContestFinalFactType(StrEnum):
    EVALUATION = "EVALUATION"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    WITHDRAWN = "WITHDRAWN"
    NO_SUBMISSION = "NO_SUBMISSION"


class ContestActionType(StrEnum):
    PUBLISH = "publish"
    CANCEL = "cancel"
    RESUME = "resume"
    SUBMIT_SUBMISSION = "submit_submission"
    WITHDRAW = "withdraw"


PUBLIC_ACTION_TYPES = frozenset(ContestActionType)
EMPTY_PAYLOAD_ACTION_TYPES = frozenset(
    {
        ContestActionType.PUBLISH,
        ContestActionType.CANCEL,
        ContestActionType.RESUME,
        ContestActionType.WITHDRAW,
    }
)
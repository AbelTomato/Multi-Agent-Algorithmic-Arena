"""评测 API 和 Agent 结构化输出的严格契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_AGENT_RESPONSE_BYTES = 128 * 1024
MAX_CODE_BYTES = 64 * 1024
MAX_EXPLANATION_BYTES = 16 * 1024


def _validate_utf8_limit(value: str, limit: int, field_name: str) -> str:
    if len(value.encode("utf-8")) > limit:
        raise ValueError(f"{field_name} 不得超过 {limit // 1024} KiB")
    return value


class EvaluationRequest(BaseModel):
    """客户端只能指定待评测题目。"""

    model_config = ConfigDict(extra="forbid")

    problem_id: int = Field(gt=0)


class AgentEvaluationOutput(BaseModel):
    """评测链路要求 Agent 返回的纯 JSON 对象。"""

    model_config = ConfigDict(extra="forbid")

    language: Literal["python"]
    code: str = Field(min_length=1)
    explanation: str

    @field_validator("code")
    @classmethod
    def validate_code_bytes(cls, value: str) -> str:
        return _validate_utf8_limit(value, MAX_CODE_BYTES, "code")

    @field_validator("explanation")
    @classmethod
    def validate_explanation_bytes(cls, value: str) -> str:
        return _validate_utf8_limit(value, MAX_EXPLANATION_BYTES, "explanation")
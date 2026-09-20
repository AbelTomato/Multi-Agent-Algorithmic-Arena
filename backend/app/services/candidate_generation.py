from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_CANDIDATE_SOURCE_BYTES = 64 * 1024


class CandidateOutput(BaseModel):
    """候选生成的唯一输出边界，不包含任何运行或评测参数。"""

    model_config = ConfigDict(extra="forbid")

    language: Literal["python", "cpp"]
    source: str = Field(min_length=1)

    @field_validator("source")
    @classmethod
    def validate_source_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_CANDIDATE_SOURCE_BYTES:
            raise ValueError("source must not exceed 64 KiB")
        return value


class CandidateGeneration:
    """将外部生成结果转换为纯结构化候选；不访问存储或评测执行器。"""

    @staticmethod
    def from_payload(payload: object) -> CandidateOutput:
        return CandidateOutput.model_validate(payload)
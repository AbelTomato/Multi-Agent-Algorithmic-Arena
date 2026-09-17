"""执行协议：请求和结果的数据模型

不包含题目判定逻辑，只定义执行器的输入输出边界。
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ProtocolVersion(str, Enum):
    """支持的协议版本"""
    JSON_STDIO_V1 = "json-stdio-v1"


class ExecutionExitReason(str, Enum):
    """执行退出原因"""
    COMPLETED = "completed"  # 正常完成（退出码 0）
    NON_ZERO_EXIT = "non_zero_exit"  # 非零退出码
    TIMEOUT = "timeout"  # 墙钟超时
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"  # 输出超限
    CANCELLED = "cancelled"  # 请求被取消
    DOCKER_ERROR = "docker_error"  # Docker 启动/运行错误
    UNKNOWN_ERROR = "unknown_error"  # 未知错误


class ExecutionRequest(BaseModel):
    """执行请求

    承载候选代码、单个用例输入和协议版本。
    不接受调用者覆盖安全策略（镜像、限制、挂载等）。
    """

    code: str = Field(
        ...,
        min_length=1,
        max_length=64 * 1024,  # 64 KiB 代码上限
        description="完整的可执行 Python 程序"
    )

    stdin_input: str = Field(
        ...,
        max_length=64 * 1024,  # 64 KiB 单例输入上限
        description="单个用例的 JSON 输入，将写入 stdin"
    )

    protocol_version: ProtocolVersion = Field(
        default=ProtocolVersion.JSON_STDIO_V1,
        description="执行协议版本"
    )

    task_id: Optional[str] = Field(
        default=None,
        description="任务 ID，用于容器标签和清理追踪"
    )

    @field_validator('code')
    @classmethod
    def validate_code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("代码不能为空或仅包含空白字符")
        return v


class ExecutionResult(BaseModel):
    """执行结果

    承载退出原因、有界输出和观测信息。
    不产生 AC/WA 判定，这是 Judge 的责任。
    """

    exit_reason: ExecutionExitReason = Field(
        ...,
        description="退出原因"
    )

    exit_code: Optional[int] = Field(
        default=None,
        description="进程退出码（如果可用）"
    )

    stdout: str = Field(
        default="",
        max_length=64 * 1024,  # 64 KiB 输出上限
        description="标准输出（已截断至上限）"
    )

    stderr: str = Field(
        default="",
        max_length=64 * 1024,  # 64 KiB 输出上限（与 stdout 共享预算）
        description="标准错误（已截断至上限）"
    )

    wall_time_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="墙钟时间（毫秒）"
    )

    container_id: Optional[str] = Field(
        default=None,
        description="Docker 容器 ID（用于调试）"
    )

    error_message: Optional[str] = Field(
        default=None,
        description="错误消息（Docker 错误、取消等）"
    )

    @property
    def success(self) -> bool:
        """执行是否成功完成（不代表答案正确）"""
        return self.exit_reason == ExecutionExitReason.COMPLETED and self.exit_code == 0

    @property
    def combined_output_size(self) -> int:
        """stdout + stderr 的总字节数"""
        return len(self.stdout.encode('utf-8')) + len(self.stderr.encode('utf-8'))

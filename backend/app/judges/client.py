"""Go 执行控制器的有界异步 HTTP 客户端。"""

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.judges.base import EvaluationStatus, JSON_STDIO_V1

EXECUTION_API_V2 = "execution-api-v2"
PYTHON_RUNTIME_V1 = "python-3.11-v1"
CPP_RUNTIME_V1 = "cpp-gcc-14-cpp20-v1"


class ControllerError(Exception):
    """执行控制器基础设施错误的基类。"""


class ControllerBusyError(ControllerError):
    """控制器单槽已被占用。"""


class ControllerUnavailableError(ControllerError):
    """控制器无法连接或返回服务端错误。"""


class ControllerTimeoutError(ControllerError):
    """控制器 HTTP 请求超时。"""


class ControllerResponseError(ControllerError):
    """控制器成功响应不符合冻结契约。"""


class ExecutionResult(BaseModel):
    """冻结的 Go 控制器执行响应。"""

    model_config = ConfigDict(extra="forbid")

    exit_reason: str
    exit_code: int | None = None
    stdout: str
    stderr: str
    wall_time_ms: int
    oom_killed: bool


class SandboxClient:
    """执行控制器客户端

    调用 sandbox 执行控制器的 HTTP 接口。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8001",
        timeout: float = 10.0,
        runtime_id: str = PYTHON_RUNTIME_V1,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if runtime_id not in {PYTHON_RUNTIME_V1, CPP_RUNTIME_V1}:
            raise ValueError(f"unsupported runtime: {runtime_id}")
        self.runtime_id = runtime_id
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout, trust_env=False)

    async def execute(self, *, code: str, stdin_input: str) -> tuple[EvaluationStatus, ExecutionResult]:
        request_data = {
            "api_version": EXECUTION_API_V2,
            "runtime_id": self.runtime_id,
            "source": code,
            "stdin_input": stdin_input,
            "io_protocol": JSON_STDIO_V1,
        }
        try:
            response = await self.client.post(f"{self.base_url}/execute", json=request_data)
        except httpx.TimeoutException as error:
            raise ControllerTimeoutError("执行控制器请求超时") from error
        except httpx.HTTPError as error:
            raise ControllerUnavailableError("无法连接到执行控制器") from error
        if response.status_code == 409:
            raise ControllerBusyError("执行控制器忙碌")
        if response.status_code >= 500:
            raise ControllerUnavailableError("执行控制器不可用")
        if response.status_code != 200:
            raise ControllerResponseError("执行控制器拒绝了内部执行请求")
        try:
            result = ExecutionResult.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise ControllerResponseError("执行控制器响应格式无效") from error
        return self._classify_execution_result(result), result

    @staticmethod
    def _classify_execution_result(result: ExecutionResult) -> EvaluationStatus:
        if result.exit_reason == "completed" and result.exit_code == 0:
            return EvaluationStatus.AC
        if result.exit_reason == "non_zero_exit":
            return EvaluationStatus.RE
        if result.exit_reason == "timeout":
            return EvaluationStatus.TLE
        if result.exit_reason == "output_limit_exceeded":
            return EvaluationStatus.OLE
        if result.exit_reason == "memory_limit_exceeded" and result.oom_killed:
            return EvaluationStatus.MLE
        return EvaluationStatus.UKE

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> "SandboxClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        await self.aclose()

"""执行控制器客户端

通过 httpx 调用独立的执行控制器服务。
"""

import httpx
from typing import Optional

from app.judges.base import EvaluationStatus


class ExecutionRequest(dict):
    """执行请求（简化版，直接继承 dict）"""
    pass


class ExecutionResult(dict):
    """执行结果（简化版，直接继承 dict）"""
    pass


class SandboxClient:
    """执行控制器客户端

    调用 sandbox 执行控制器的 HTTP 接口。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8001",
        timeout: float = 10.0
    ):
        """初始化客户端

        Args:
            base_url: 执行控制器基础 URL
            timeout: 单次请求超时（秒），默认 10 秒
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def execute(
        self,
        code: str,
        stdin_input: str,
        task_id: Optional[str] = None
    ) -> tuple[EvaluationStatus, ExecutionResult]:
        """执行代码

        Args:
            code: 完整的可执行 Python 程序
            stdin_input: 单个用例的 JSON 输入字符串
            task_id: 任务 ID（可选）

        Returns:
            (status, result): 评测状态和执行结果

        Raises:
            httpx.HTTPError: 网络或 HTTP 错误
        """
        request_data = {
            "code": code,
            "stdin_input": stdin_input,
            "protocol_version": "json-stdio-v1"
        }

        if task_id:
            request_data["task_id"] = task_id

        try:
            response = self.client.post(
                f"{self.base_url}/execute",
                json=request_data
            )
            response.raise_for_status()
            result = response.json()

            # 根据执行结果判定状态
            status = self._classify_execution_result(result)
            return status, result

        except httpx.ConnectError as e:
            raise httpx.HTTPError(f"无法连接到执行控制器: {e}") from e
        except httpx.TimeoutException as e:
            raise httpx.HTTPError(f"执行控制器超时: {e}") from e

    def _classify_execution_result(self, result: ExecutionResult) -> EvaluationStatus:
        """根据执行结果分类评测状态

        只判断执行层面的状态（TLE/OLE/RE），不判断答案正确性（AC/WA）。
        """
        exit_reason = result.get("exit_reason")

        if exit_reason == "timeout":
            return EvaluationStatus.TLE

        if exit_reason == "output_limit_exceeded":
            return EvaluationStatus.OLE

        if exit_reason in ("non_zero_exit", "docker_error", "unknown_error"):
            return EvaluationStatus.RE

        if exit_reason == "completed" and result.get("exit_code") == 0:
            # 正常完成，需要后续判定答案
            return EvaluationStatus.AC  # 临时标记，由 evaluator 覆盖

        # 其他情况视为运行时错误
        return EvaluationStatus.RE

    def health_check(self) -> bool:
        """健康检查

        Returns:
            bool: 执行控制器是否可用
        """
        try:
            # 使用独立的短超时客户端进行健康检查
            with httpx.Client(timeout=3.0) as check_client:
                response = check_client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    def close(self):
        """关闭客户端"""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

"""集成测试：真实 Docker 执行验证

通过环境变量 ARENA_SANDBOX_INTEGRATION=1 启用
"""

import os
import pytest

from app.protocol import ExecutionRequest, ExecutionExitReason
from app.runner import DockerRunner

# 跳过条件：未设置环境变量
skip_integration = os.getenv("ARENA_SANDBOX_INTEGRATION") != "1"
skip_reason = "请设置 ARENA_SANDBOX_INTEGRATION=1 启用集成测试"


@pytest.mark.skipif(skip_integration, reason=skip_reason)
class TestDockerIntegration:
    """真实 Docker 执行集成测试"""

    def test_hello_world(self):
        """正常执行应该返回 COMPLETED"""
        runner = DockerRunner()
        request = ExecutionRequest(
            code='print("Hello, World!")',
            stdin_input='{}',
            task_id="integration-test-hello"
        )

        result = runner.execute(request)

        assert result.exit_reason == ExecutionExitReason.COMPLETED
        assert result.exit_code == 0
        assert "Hello, World!" in result.stdout
        assert result.wall_time_ms is not None
        assert result.wall_time_ms > 0

    def test_json_stdio_protocol(self):
        """测试 JSON 输入输出协议"""
        runner = DockerRunner()
        code = '''
import json
import sys

input_data = json.loads(sys.stdin.read())
result = input_data["a"] + input_data["b"]
print(json.dumps({"sum": result}))
'''
        request = ExecutionRequest(
            code=code,
            stdin_input='{"a": 5, "b": 3}',
            task_id="integration-test-json"
        )

        result = runner.execute(request)

        assert result.exit_reason == ExecutionExitReason.COMPLETED
        assert result.exit_code == 0
        assert '"sum": 8' in result.stdout or '"sum":8' in result.stdout

    def test_non_zero_exit(self):
        """非零退出应该返回 NON_ZERO_EXIT"""
        runner = DockerRunner()
        request = ExecutionRequest(
            code='import sys; sys.exit(1)',
            stdin_input='{}',
            task_id="integration-test-exit1"
        )

        result = runner.execute(request)

        assert result.exit_reason == ExecutionExitReason.NON_ZERO_EXIT
        assert result.exit_code == 1

    def test_timeout(self):
        """超时应该返回 TIMEOUT"""
        runner = DockerRunner()
        request = ExecutionRequest(
            code='import time; time.sleep(10)',
            stdin_input='{}',
            task_id="integration-test-timeout"
        )

        result = runner.execute(request)

        assert result.exit_reason == ExecutionExitReason.TIMEOUT
        assert result.wall_time_ms is not None
        # 应该接近 5000ms （墙钟限制）
        assert result.wall_time_ms >= 4500

    def test_runtime_error(self):
        """运行时错误应该捕获"""
        runner = DockerRunner()
        request = ExecutionRequest(
            code='1 / 0',
            stdin_input='{}',
            task_id="integration-test-error"
        )

        result = runner.execute(request)

        assert result.exit_reason == ExecutionExitReason.NON_ZERO_EXIT
        assert result.exit_code != 0
        assert "ZeroDivisionError" in result.stderr or "Traceback" in result.stderr

    def test_network_disabled(self):
        """网络应该被禁用"""
        runner = DockerRunner()
        code = '''
import socket
try:
    socket.create_connection(("google.com", 80), timeout=1)
    print("NETWORK_WORKS")
except Exception as e:
    print(f"NETWORK_BLOCKED: {type(e).__name__}")
'''
        request = ExecutionRequest(
            code=code,
            stdin_input='{}',
            task_id="integration-test-network"
        )

        result = runner.execute(request)

        # 网络应该被阻断
        assert "NETWORK_BLOCKED" in result.stdout
        assert "NETWORK_WORKS" not in result.stdout

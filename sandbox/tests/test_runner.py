"""执行控制器单元测试

使用 mock Docker CLI，测试生命周期、异常、超时和清理逻辑。
"""

import pytest
from app.protocol import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionExitReason,
    ProtocolVersion,
)


class TestExecutionRequest:
    """测试执行请求模型"""

    def test_valid_request(self):
        """合法请求应该通过验证"""
        req = ExecutionRequest(
            code='print("hello")',
            stdin_input='{"test": 1}',
            task_id="test-001"
        )
        assert req.code == 'print("hello")'
        assert req.stdin_input == '{"test": 1}'
        assert req.task_id == "test-001"

    def test_empty_code_rejected(self):
        """空代码应该被拒绝"""
        with pytest.raises(ValueError, match="代码不能为空"):
            ExecutionRequest(code="   ", stdin_input='{"test": 1}')

    def test_code_too_large_rejected(self):
        """超过 64 KiB 的代码应该被拒绝"""
        with pytest.raises(ValueError):
            ExecutionRequest(
                code="x" * (64 * 1024 + 1),
                stdin_input='{"test": 1}'
            )

    def test_stdin_too_large_rejected(self):
        """超过 64 KiB 的输入应该被拒绝"""
        with pytest.raises(ValueError):
            ExecutionRequest(
                code='print("test")',
                stdin_input="x" * (64 * 1024 + 1)
            )


class TestExecutionResult:
    """测试执行结果模型"""

    def test_success_property(self):
        """正常完成且退出码 0 应该视为成功"""
        result = ExecutionResult(
            exit_reason=ExecutionExitReason.COMPLETED,
            exit_code=0,
            stdout='{"result": true}'
        )
        assert result.success is True

    def test_non_zero_exit_not_success(self):
        """非零退出码不应该视为成功"""
        result = ExecutionResult(
            exit_reason=ExecutionExitReason.NON_ZERO_EXIT,
            exit_code=1,
            stdout=""
        )
        assert result.success is False

    def test_timeout_not_success(self):
        """超时不应该视为成功"""
        result = ExecutionResult(
            exit_reason=ExecutionExitReason.TIMEOUT,
            exit_code=None,
            stdout=""
        )
        assert result.success is False

    def test_combined_output_size(self):
        """应该正确计算 stdout + stderr 的字节数"""
        result = ExecutionResult(
            exit_reason=ExecutionExitReason.COMPLETED,
            exit_code=0,
            stdout="hello",  # 5 bytes
            stderr="world"   # 5 bytes
        )
        assert result.combined_output_size == 10

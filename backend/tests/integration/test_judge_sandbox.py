"""Judge 与 Sandbox 集成测试

使用真实 Docker 执行器验证完整评测链路。
"""

import os
import asyncio

import httpx
import pytest

from app.judges.base import EvaluationStatus
from app.judges.catalog import CaseCatalog
from app.judges.client import ControllerBusyError, ControllerUnavailableError, SandboxClient
from app.judges.evaluator import Evaluator

# 只在显式设置环境变量时运行集成测试
pytestmark = pytest.mark.skipif(
    os.getenv("ARENA_SANDBOX_INTEGRATION") != "1",
    reason="需要设置 ARENA_SANDBOX_INTEGRATION=1 并启动 sandbox 执行控制器"
)


CORRECT_VALID_PARENTHESES = """
import json
import sys

data = json.loads(sys.stdin.read())
s = data["s"]

stack = []
mapping = {')': '(', '}': '{', ']': '['}

for char in s:
    if char in mapping:
        top = stack.pop() if stack else '#'
        if mapping[char] != top:
            result = False
            break
    else:
        stack.append(char)
else:
    result = len(stack) == 0

print(json.dumps({"result": result}))
"""

WRONG_VALID_PARENTHESES = """
import json
import sys

data = json.loads(sys.stdin.read())
print(json.dumps({"result": True}))
"""

RUNTIME_ERROR = """
raise RuntimeError("candidate failure")
"""

INFINITE_LOOP = """
while True:
    pass
"""

OUTPUT_FLOOD = """
import sys
sys.stdout.write("x" * (65 * 1024))
"""

MEMORY_FLOOD = """
data = bytearray(256 * 1024 * 1024)
print(data[0])
"""

CORRECT_TWO_SUM = """
import json
import sys

data = json.loads(sys.stdin.read())
nums = data["nums"]
target = data["target"]

seen = {}
for i, num in enumerate(nums):
    complement = target - num
    if complement in seen:
        indices = [seen[complement], i]
        break
    seen[num] = i

print(json.dumps({"indices": indices}))
"""


class TestValidParenthesesIntegration:
    """Valid Parentheses 集成测试"""

    @pytest.mark.asyncio
    async def test_correct_solution(self):
        """测试正确的 Valid Parentheses 解法"""
        catalog = CaseCatalog()
        cases = catalog.load("valid-parentheses", "v1")

        async with SandboxClient() as client:
            result = await Evaluator(client).evaluate(
                problem_id=1,
                problem_slug="valid-parentheses",
                code=CORRECT_VALID_PARENTHESES,
                cases=cases,
            )

        assert result.status == EvaluationStatus.AC
        assert result.case_count == 12
        assert result.executed_count == 12
        assert result.passed_count == 12
        assert result.failed_case_index is None
        assert "通过当前版本评测用例" in result.summary

    @pytest.mark.asyncio
    async def test_wrong_solution(self):
        """测试错误的 Valid Parentheses 解法（永远返回 true）"""
        catalog = CaseCatalog()
        cases = catalog.load("valid-parentheses", "v1")

        async with SandboxClient() as client:
            result = await Evaluator(client).evaluate(
                problem_id=1,
                problem_slug="valid-parentheses",
                code=WRONG_VALID_PARENTHESES,
                cases=cases,
            )

        assert result.status == EvaluationStatus.WA
        assert result.executed_count > 0
        assert result.passed_count < result.case_count
        assert result.failed_case_index is not None
        assert "答案错误" in result.summary


class TestTwoSumIntegration:
    """Two Sum 集成测试"""

    @pytest.mark.asyncio
    async def test_correct_solution(self):
        """测试正确的 Two Sum 解法"""
        catalog = CaseCatalog()
        cases = catalog.load("two-sum", "v1")

        async with SandboxClient() as client:
            result = await Evaluator(client).evaluate(
                problem_id=2,
                problem_slug="two-sum",
                code=CORRECT_TWO_SUM,
                cases=cases,
            )

        assert result.status == EvaluationStatus.AC
        assert result.case_count == 9
        assert result.executed_count == 9
        assert result.passed_count == 9
        assert result.failed_case_index is None


class TestExecutionFailureIntegration:
    """真实 Go 控制器错误分类与准入集成测试。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("code", "expected_status"),
        [
            (RUNTIME_ERROR, EvaluationStatus.RE),
            (INFINITE_LOOP, EvaluationStatus.TLE),
            (OUTPUT_FLOOD, EvaluationStatus.OLE),
            (MEMORY_FLOOD, EvaluationStatus.MLE),
        ],
    )
    async def test_execution_failure_status(self, code: str, expected_status: EvaluationStatus) -> None:
        cases = CaseCatalog().load("valid-parentheses", "v1")
        async with SandboxClient() as client:
            result = await Evaluator(client).evaluate(1, "valid-parentheses", code, cases)

        assert result.status == expected_status
        assert result.executed_count == 1
        assert result.passed_count == 0
        assert result.failed_case_index == 0

    @pytest.mark.asyncio
    async def test_controller_unavailable_is_preserved_for_api_mapping(self) -> None:
        cases = CaseCatalog().load("valid-parentheses", "v1")
        async with SandboxClient(base_url="http://127.0.0.1:1", timeout=0.2) as client:
            with pytest.raises(ControllerUnavailableError):
                await Evaluator(client).evaluate(1, "valid-parentheses", CORRECT_VALID_PARENTHESES, cases)

    @pytest.mark.asyncio
    async def test_busy_controller_is_preserved_without_running_second_candidate(self) -> None:
        cases = CaseCatalog().load("valid-parentheses", "v1")
        payload = {
            "code": INFINITE_LOOP,
            "stdin_input": '{"s":"()"}',
            "protocol_version": "json-stdio-v1",
        }
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as holder:
            first_request = asyncio.create_task(holder.post("http://127.0.0.1:8001/execute", json=payload))
            await asyncio.sleep(0.25)
            async with SandboxClient() as client:
                with pytest.raises(ControllerBusyError):
                    await Evaluator(client).evaluate(
                        1, "valid-parentheses", CORRECT_VALID_PARENTHESES, cases
                    )
            first_response = await first_request

        assert first_response.status_code == 200

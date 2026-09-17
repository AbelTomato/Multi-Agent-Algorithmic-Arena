"""Judge 与 Sandbox 集成测试

使用真实 Docker 执行器验证完整评测链路。
"""

import os
import pytest

from app.judges.base import EvaluationStatus
from app.judges.catalog import CaseCatalog
from app.judges.client import SandboxClient
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

    def test_correct_solution(self):
        """测试正确的 Valid Parentheses 解法"""
        catalog = CaseCatalog()
        cases = catalog.load("valid-parentheses", "v1")

        client = SandboxClient()
        evaluator = Evaluator(client)

        result = evaluator.evaluate(
            problem_id=1,
            problem_slug="valid-parentheses",
            code=CORRECT_VALID_PARENTHESES,
            cases=cases
        )

        assert result.status == EvaluationStatus.AC
        assert result.case_count == 12
        assert result.executed_count == 12
        assert result.passed_count == 12
        assert result.failed_case_index is None
        assert "通过当前版本评测用例" in result.summary

    def test_wrong_solution(self):
        """测试错误的 Valid Parentheses 解法（永远返回 true）"""
        catalog = CaseCatalog()
        cases = catalog.load("valid-parentheses", "v1")

        client = SandboxClient()
        evaluator = Evaluator(client)

        result = evaluator.evaluate(
            problem_id=1,
            problem_slug="valid-parentheses",
            code=WRONG_VALID_PARENTHESES,
            cases=cases
        )

        assert result.status == EvaluationStatus.WA
        assert result.executed_count > 0
        assert result.passed_count < result.case_count
        assert result.failed_case_index is not None
        assert "答案错误" in result.summary


class TestTwoSumIntegration:
    """Two Sum 集成测试"""

    def test_correct_solution(self):
        """测试正确的 Two Sum 解法"""
        catalog = CaseCatalog()
        cases = catalog.load("two-sum", "v1")

        client = SandboxClient()
        evaluator = Evaluator(client)

        result = evaluator.evaluate(
            problem_id=2,
            problem_slug="two-sum",
            code=CORRECT_TWO_SUM,
            cases=cases
        )

        assert result.status == EvaluationStatus.AC
        assert result.case_count == 9
        assert result.executed_count == 9
        assert result.passed_count == 9
        assert result.failed_case_index is None

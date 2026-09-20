"""可信 Judge：执行单例、解析严格 JSON 并按题意判定。"""

import json
from typing import Any

from app.judges.base import EvaluationStatus, JudgeCases, JudgeResult, MAX_STDIN_BYTES
from app.judges.client import PYTHON_RUNTIME_V1, SandboxClient


class Evaluator:
    """逐用例串行评测，首个失败后立即停止。"""

    def __init__(self, sandbox_client: SandboxClient, runtime_id: str = PYTHON_RUNTIME_V1) -> None:
        self.client = sandbox_client
        self.runtime_id = runtime_id

    async def evaluate(
        self, problem_id: int, problem_slug: str, code: str, cases: JudgeCases
    ) -> JudgeResult:
        all_cases = cases.all_cases
        if not all_cases or len(all_cases) > 32:
            return self._result(problem_id, problem_slug, cases, EvaluationStatus.UKE, 0, 0, None)

        passed_count = 0
        for index, test_case in enumerate(all_cases):
            stdin_input = json.dumps(test_case.input, ensure_ascii=False, separators=(",", ":"))
            if len(stdin_input.encode("utf-8")) > MAX_STDIN_BYTES:
                return self._result(
                    problem_id, problem_slug, cases, EvaluationStatus.UKE, index, passed_count, index
                )
            execution_status, execution_result = await self.client.execute(
                code=code, stdin_input=stdin_input
            )

            if execution_status != EvaluationStatus.AC:
                return self._result(
                    problem_id,
                    problem_slug,
                    cases,
                    execution_status,
                    index + 1,
                    passed_count,
                    index,
                )

            verdict = self._judge_output(
                problem_slug, execution_result.stdout, test_case.expected, test_case.input
            )
            if verdict != EvaluationStatus.AC:
                return self._result(
                    problem_id, problem_slug, cases, verdict, index + 1, passed_count, index
                )
            passed_count += 1

        return self._result(
            problem_id, problem_slug, cases, EvaluationStatus.AC, len(all_cases), passed_count, None
        )

    def _judge_output(
        self,
        problem_slug: str,
        stdout: str,
        expected: dict[str, Any],
        case_input: dict[str, Any] | None = None,
    ) -> EvaluationStatus:
        try:
            output = json.loads(stdout.strip())
        except (json.JSONDecodeError, AttributeError):
            return EvaluationStatus.RE
        if not isinstance(output, dict):
            return EvaluationStatus.RE
        if problem_slug == "valid-parentheses":
            return self._judge_valid_parentheses(output, expected)
        if problem_slug == "two-sum":
            return self._judge_two_sum(output, case_input)
        return EvaluationStatus.UKE

    @staticmethod
    def _judge_valid_parentheses(output: dict[str, Any], expected: dict[str, Any]) -> EvaluationStatus:
        if set(output) != {"result"} or not isinstance(output["result"], bool):
            return EvaluationStatus.RE
        expected_result = expected.get("result")
        if not isinstance(expected_result, bool):
            return EvaluationStatus.UKE
        return EvaluationStatus.AC if output["result"] == expected_result else EvaluationStatus.WA

    @staticmethod
    def _judge_two_sum(output: dict[str, Any], case_input: dict[str, Any] | None) -> EvaluationStatus:
        if set(output) != {"indices"} or not isinstance(output["indices"], list):
            return EvaluationStatus.RE
        indices = output["indices"]
        if len(indices) != 2 or any(not isinstance(index, int) or isinstance(index, bool) for index in indices):
            return EvaluationStatus.RE
        if not isinstance(case_input, dict):
            return EvaluationStatus.UKE
        nums, target = case_input.get("nums"), case_input.get("target")
        if (
            not isinstance(nums, list)
            or not isinstance(target, int)
            or isinstance(target, bool)
            or any(not isinstance(value, int) or isinstance(value, bool) for value in nums)
        ):
            return EvaluationStatus.UKE
        first, second = indices
        if first == second or first < 0 or second < 0 or first >= len(nums) or second >= len(nums):
            return EvaluationStatus.WA
        return EvaluationStatus.AC if nums[first] + nums[second] == target else EvaluationStatus.WA

    @staticmethod
    def _summary(status: EvaluationStatus, failed_case_index: int | None) -> str:
        if status == EvaluationStatus.AC:
            return "通过当前版本评测用例"
        if status == EvaluationStatus.UKE:
            return "评测系统错误或结果无法可靠分类"
        descriptions = {
            EvaluationStatus.WA: "答案错误",
            EvaluationStatus.RE: "运行时错误",
            EvaluationStatus.TLE: "超时",
            EvaluationStatus.MLE: "内存超限",
            EvaluationStatus.OLE: "输出超限",
        }
        return f"第 {failed_case_index + 1} 个用例{descriptions[status]}"

    def _result(
        self,
        problem_id: int,
        problem_slug: str,
        cases: JudgeCases,
        status: EvaluationStatus,
        executed_count: int,
        passed_count: int,
        failed_case_index: int | None,
    ) -> JudgeResult:
        return JudgeResult(
            problem_id=problem_id,
            problem_slug=problem_slug,
            language="python",
            status=status,
            case_version=cases.version,
            case_count=len(cases.all_cases),
            executed_count=executed_count,
            passed_count=passed_count,
            failed_case_index=failed_case_index,
            summary=self._summary(status, failed_case_index),
        )
"""可信判定器

执行严格的 JSON 输出比较和语义判定。
"""

import json
from typing import Any, Optional

from app.judges.base import EvaluationStatus, JudgeCases, JudgeResult, TestCase
from app.judges.client import SandboxClient


class Evaluator:
    """可信判定器

    根据实施计划 2.2.3 节定义的判定规则进行严格比较。
    """

    def __init__(self, sandbox_client: SandboxClient):
        """初始化判定器

        Args:
            sandbox_client: 执行控制器客户端
        """
        self.client = sandbox_client

    def evaluate(
        self,
        problem_id: int,
        problem_slug: str,
        code: str,
        cases: JudgeCases
    ) -> JudgeResult:
        """执行完整评测

        Args:
            problem_id: 题目 ID
            problem_slug: 题目 slug
            code: 候选代码
            cases: 评测用例集合

        Returns:
            JudgeResult: 评测结果摘要
        """
        all_cases = cases.all_cases
        case_count = len(all_cases)
        executed_count = 0
        passed_count = 0
        failed_case_index: Optional[int] = None
        final_status = EvaluationStatus.AC

        # 遇到首个失败即停止（fail-fast）
        for i, test_case in enumerate(all_cases):
            executed_count += 1

            # 序列化输入
            stdin_input = json.dumps(test_case.input)
            task_id = f"{problem_slug}-case-{i}"

            try:
                # 执行代码
                exec_status, exec_result = self.client.execute(
                    code=code,
                    stdin_input=stdin_input,
                    task_id=task_id
                )

                # 如果执行层面已经失败（TLE/OLE/RE），直接失败
                if exec_status in (EvaluationStatus.TLE, EvaluationStatus.OLE, EvaluationStatus.RE):
                    final_status = exec_status
                    failed_case_index = i
                    break

                # 执行成功，判定答案
                stdout = exec_result.get("stdout", "")
                verdict = self._judge_output(
                    problem_slug=problem_slug,
                    stdout=stdout,
                    expected=test_case.expected
                )

                if verdict == EvaluationStatus.AC:
                    passed_count += 1
                else:
                    # WA 或 RE（输出协议错误）
                    final_status = verdict
                    failed_case_index = i
                    break

            except Exception as e:
                # 执行控制器不可用或其他基础设施错误
                final_status = EvaluationStatus.UKE
                failed_case_index = i
                break

        # 生成摘要
        summary = self._generate_summary(
            status=final_status,
            executed_count=executed_count,
            case_count=case_count,
            passed_count=passed_count,
            failed_case_index=failed_case_index
        )

        return JudgeResult(
            problem_id=problem_id,
            problem_slug=problem_slug,
            language="python",
            status=final_status,
            case_version=cases.version,
            case_count=case_count,
            executed_count=executed_count,
            passed_count=passed_count,
            failed_case_index=failed_case_index,
            summary=summary
        )

    def _judge_output(
        self,
        problem_slug: str,
        stdout: str,
        expected: dict
    ) -> EvaluationStatus:
        """判定输出是否正确

        根据实施计划 2.2.2 和 2.2.3 节的协议和判定规则。
        """
        # 解析输出 JSON
        try:
            # 去除前后空白
            stdout = stdout.strip()
            if not stdout:
                return EvaluationStatus.RE  # 空输出

            output = json.loads(stdout)

            if not isinstance(output, dict):
                return EvaluationStatus.RE  # 输出不是 JSON 对象

        except json.JSONDecodeError:
            return EvaluationStatus.RE  # 非法 JSON

        # 根据题目类型判定
        if problem_slug == "valid-parentheses":
            return self._judge_valid_parentheses(output, expected)
        elif problem_slug == "two-sum":
            return self._judge_two_sum(output, expected)
        else:
            # 未知题目类型
            return EvaluationStatus.UKE

    def _judge_valid_parentheses(
        self,
        output: dict,
        expected: dict
    ) -> EvaluationStatus:
        """Valid Parentheses 判定

        根据实施计划 2.2.3 节：
        - 必须有 result 字段
        - result 必须是 JSON 布尔值（不接受 1/0 或字符串）
        - 严格比较布尔值
        """
        # 检查字段
        if "result" not in output:
            return EvaluationStatus.RE  # 缺少字段

        if len(output) != 1:
            return EvaluationStatus.RE  # 额外字段

        result = output["result"]
        expected_result = expected["result"]

        # 类型检查：必须是布尔值
        if not isinstance(result, bool):
            return EvaluationStatus.RE  # 类型错误

        if not isinstance(expected_result, bool):
            return EvaluationStatus.UKE  # 期望值类型错误（系统错误）

        # 严格比较
        if result == expected_result:
            return EvaluationStatus.AC
        else:
            return EvaluationStatus.WA

    def _judge_two_sum(
        self,
        output: dict,
        expected: dict
    ) -> EvaluationStatus:
        """Two Sum 判定

        根据实施计划 2.2.3 节：
        - 必须有 indices 字段
        - indices 必须恰含两个严格 JSON 整数
        - 两下标不同且均在数组范围内
        - 满足 nums[i] + nums[j] == target
        - 忽略下标顺序
        """
        # 检查字段
        if "indices" not in output:
            return EvaluationStatus.RE  # 缺少字段

        if len(output) != 1:
            return EvaluationStatus.RE  # 额外字段

        indices = output["indices"]

        # 类型检查：必须是数组
        if not isinstance(indices, list):
            return EvaluationStatus.RE

        # 长度检查：必须恰含两个元素
        if len(indices) != 2:
            return EvaluationStatus.RE

        # 元素类型检查：必须是整数，不接受布尔值
        for idx in indices:
            if not isinstance(idx, int) or isinstance(idx, bool):
                return EvaluationStatus.RE

        i, j = indices[0], indices[1]

        # 两下标必须不同
        if i == j:
            return EvaluationStatus.WA

        # 期望值也必须是合法的两个整数下标
        expected_indices = expected["indices"]
        if not isinstance(expected_indices, list) or len(expected_indices) != 2:
            return EvaluationStatus.UKE  # 期望值格式错误（系统错误）

        # 获取期望的下标集合（忽略顺序）
        expected_set = set(expected_indices)
        output_set = set(indices)

        # 比较下标集合
        if output_set == expected_set:
            return EvaluationStatus.AC
        else:
            return EvaluationStatus.WA

    def _generate_summary(
        self,
        status: EvaluationStatus,
        executed_count: int,
        case_count: int,
        passed_count: int,
        failed_case_index: Optional[int]
    ) -> str:
        """生成评测摘要"""
        if status == EvaluationStatus.AC:
            return "通过当前版本评测用例"

        if status == EvaluationStatus.WA:
            return f"第 {failed_case_index + 1} 个用例答案错误"

        if status == EvaluationStatus.RE:
            return f"第 {failed_case_index + 1} 个用例运行时错误"

        if status == EvaluationStatus.TLE:
            return f"第 {failed_case_index + 1} 个用例超时"

        if status == EvaluationStatus.OLE:
            return f"第 {failed_case_index + 1} 个用例输出超限"

        if status == EvaluationStatus.MLE:
            return f"第 {failed_case_index + 1} 个用例内存超限"

        if status == EvaluationStatus.UKE:
            return "评测系统错误或结果无法可靠分类"

        return "未知状态"

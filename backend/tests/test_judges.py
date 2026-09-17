"""Judge 模块单元测试

测试用例加载、判定逻辑、状态分类和结果聚合。
"""

import json
import pytest
from pathlib import Path

from app.judges.base import EvaluationStatus, JudgeCases, TestCase
from app.judges.catalog import CaseCatalog, CaseNotFoundError
from app.judges.evaluator import Evaluator


class TestCaseCatalog:
    """用例目录加载器测试"""

    def test_load_valid_parentheses(self):
        """测试加载 Valid Parentheses 用例"""
        catalog = CaseCatalog()
        cases = catalog.load("valid-parentheses", "v1")

        assert cases.problem_slug == "valid-parentheses"
        assert cases.version == "v1"
        assert cases.protocol_version == "json-stdio-v1"
        assert len(cases.public_cases) == 6
        assert len(cases.hidden_cases) == 6
        assert len(cases.all_cases) == 12

    def test_load_two_sum(self):
        """测试加载 Two Sum 用例"""
        catalog = CaseCatalog()
        cases = catalog.load("two-sum", "v1")

        assert cases.problem_slug == "two-sum"
        assert cases.version == "v1"
        assert cases.protocol_version == "json-stdio-v1"
        assert len(cases.public_cases) == 3
        assert len(cases.hidden_cases) == 6
        assert len(cases.all_cases) == 9

    def test_load_nonexistent_case(self):
        """测试加载不存在的用例"""
        catalog = CaseCatalog()

        with pytest.raises(CaseNotFoundError):
            catalog.load("nonexistent-problem", "v1")

    def test_slug_mismatch(self, tmp_path):
        """测试 slug 不匹配"""
        # 创建临时用例文件，slug 不匹配
        case_dir = tmp_path / "test-problem"
        case_dir.mkdir()
        case_file = case_dir / "v1.json"
        case_file.write_text(json.dumps({
            "problem_slug": "wrong-slug",
            "version": "v1",
            "protocol_version": "json-stdio-v1",
            "public_cases": [],
            "hidden_cases": []
        }))

        catalog = CaseCatalog(base_dir=tmp_path)

        with pytest.raises(ValueError, match="slug 不匹配"):
            catalog.load("test-problem", "v1")

    def test_empty_cases(self, tmp_path):
        """测试空用例集合"""
        case_dir = tmp_path / "test-problem"
        case_dir.mkdir()
        case_file = case_dir / "v1.json"
        case_file.write_text(json.dumps({
            "problem_slug": "test-problem",
            "version": "v1",
            "protocol_version": "json-stdio-v1",
            "public_cases": [],
            "hidden_cases": []
        }))

        catalog = CaseCatalog(base_dir=tmp_path)

        with pytest.raises(ValueError, match="用例集合为空"):
            catalog.load("test-problem", "v1")


class TestEvaluatorJudgment:
    """判定逻辑测试（不涉及真实执行）"""

    def test_valid_parentheses_correct(self):
        """测试 Valid Parentheses 正确输出"""
        # Mock SandboxClient
        class MockClient:
            def execute(self, code, stdin_input, task_id=None):
                return EvaluationStatus.AC, {
                    "exit_reason": "completed",
                    "exit_code": 0,
                    "stdout": '{"result": true}'
                }

        evaluator = Evaluator(MockClient())

        # 测试正确判定
        status = evaluator._judge_output(
            problem_slug="valid-parentheses",
            stdout='{"result": true}',
            expected={"result": True}
        )
        assert status == EvaluationStatus.AC

    def test_valid_parentheses_wrong_answer(self):
        """测试 Valid Parentheses 答案错误"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="valid-parentheses",
            stdout='{"result": false}',
            expected={"result": True}
        )
        assert status == EvaluationStatus.WA

    def test_valid_parentheses_missing_field(self):
        """测试 Valid Parentheses 缺少字段"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="valid-parentheses",
            stdout='{}',
            expected={"result": True}
        )
        assert status == EvaluationStatus.RE

    def test_valid_parentheses_extra_field(self):
        """测试 Valid Parentheses 额外字段"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="valid-parentheses",
            stdout='{"result": true, "extra": "field"}',
            expected={"result": True}
        )
        assert status == EvaluationStatus.RE

    def test_valid_parentheses_wrong_type(self):
        """测试 Valid Parentheses 类型错误（整数代替布尔值）"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        # 1 不是 JSON 布尔值
        status = evaluator._judge_output(
            problem_slug="valid-parentheses",
            stdout='{"result": 1}',
            expected={"result": True}
        )
        assert status == EvaluationStatus.RE

    def test_two_sum_correct(self):
        """测试 Two Sum 正确输出"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        # 下标顺序可任意
        status = evaluator._judge_output(
            problem_slug="two-sum",
            stdout='{"indices": [0, 1]}',
            expected={"indices": [0, 1]}
        )
        assert status == EvaluationStatus.AC

        # 反序也正确
        status = evaluator._judge_output(
            problem_slug="two-sum",
            stdout='{"indices": [1, 0]}',
            expected={"indices": [0, 1]}
        )
        assert status == EvaluationStatus.AC

    def test_two_sum_wrong_indices(self):
        """测试 Two Sum 下标错误"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="two-sum",
            stdout='{"indices": [0, 2]}',
            expected={"indices": [0, 1]}
        )
        assert status == EvaluationStatus.WA

    def test_two_sum_same_index(self):
        """测试 Two Sum 相同下标"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="two-sum",
            stdout='{"indices": [1, 1]}',
            expected={"indices": [0, 1]}
        )
        assert status == EvaluationStatus.WA

    def test_two_sum_wrong_length(self):
        """测试 Two Sum 长度错误"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="two-sum",
            stdout='{"indices": [0]}',
            expected={"indices": [0, 1]}
        )
        assert status == EvaluationStatus.RE

    def test_empty_output(self):
        """测试空输出"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="valid-parentheses",
            stdout='',
            expected={"result": True}
        )
        assert status == EvaluationStatus.RE

    def test_invalid_json(self):
        """测试非法 JSON"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="valid-parentheses",
            stdout='not a json',
            expected={"result": True}
        )
        assert status == EvaluationStatus.RE

    def test_unknown_problem(self):
        """测试未知题目类型"""
        class MockClient:
            pass

        evaluator = Evaluator(MockClient())

        status = evaluator._judge_output(
            problem_slug="unknown-problem",
            stdout='{"result": true}',
            expected={"result": True}
        )
        assert status == EvaluationStatus.UKE

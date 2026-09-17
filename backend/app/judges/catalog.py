"""用例目录加载器

按 problem_slug 和 version 从文件系统加载评测用例。
"""

import json
from pathlib import Path
from typing import Optional

from app.judges.base import JudgeCases


class CaseNotFoundError(Exception):
    """用例文件不存在或无法加载"""
    pass


class CaseCatalog:
    """用例目录管理器

    从 backend/judge_cases/<slug>/<version>.json 加载用例。
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """初始化用例目录

        Args:
            base_dir: 用例根目录，默认为 backend/judge_cases
        """
        if base_dir is None:
            # 默认为 backend/judge_cases
            # 当前文件在 backend/app/judges/catalog.py
            backend_dir = Path(__file__).parent.parent.parent
            base_dir = backend_dir / "judge_cases"

        self.base_dir = base_dir

    def load(self, problem_slug: str, version: str = "v1") -> JudgeCases:
        """加载指定题目的评测用例

        Args:
            problem_slug: 题目 slug
            version: 用例版本，默认 v1

        Returns:
            JudgeCases: 评测用例集合

        Raises:
            CaseNotFoundError: 用例文件不存在
            ValueError: 用例文件格式错误或版本不匹配
        """
        case_file = self.base_dir / problem_slug / f"{version}.json"

        if not case_file.exists():
            raise CaseNotFoundError(
                f"用例文件不存在: {case_file}"
            )

        try:
            with open(case_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"用例文件 JSON 损坏: {e}") from e
        except Exception as e:
            raise CaseNotFoundError(f"无法读取用例文件: {e}") from e

        try:
            cases = JudgeCases.model_validate(data)
        except Exception as e:
            raise ValueError(f"用例文件格式错误: {e}") from e

        # 验证 slug 和 version 匹配
        if cases.problem_slug != problem_slug:
            raise ValueError(
                f"用例文件 slug 不匹配: 期望 {problem_slug}，实际 {cases.problem_slug}"
            )

        if cases.version != version:
            raise ValueError(
                f"用例文件版本不匹配: 期望 {version}，实际 {cases.version}"
            )

        # 验证用例不为空
        if not cases.all_cases:
            raise ValueError("用例集合为空")

        return cases

"""Judge 抽象与结果模型

定义评测状态、结果数据模型和 Judge 协议。
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EvaluationStatus(str, Enum):
    """评测状态

    根据实施计划 2.2.7 节定义的状态语义。
    """
    AC = "AC"    # 所有当前版本用例通过
    WA = "WA"    # 输出结构合法，但答案语义错误
    RE = "RE"    # 非零或信号退出，或 stdout 协议错误
    TLE = "TLE"  # 单用例超过墙钟限制
    MLE = "MLE"  # 有可靠 Docker/cgroup OOM 证据的内存超限
    OLE = "OLE"  # stdout 与 stderr 合计超过输出限制
    UKE = "UKE"  # 结果无法可靠分类，或 Judge/执行基础设施出现未知错误


class TestCase(BaseModel):
    """单个测试用例"""
    input: dict = Field(..., description="用例输入（JSON 对象）")
    expected: dict = Field(..., description="期望输出（JSON 对象）")
    note: Optional[str] = Field(default=None, description="用例说明（不外泄）")


class JudgeCases(BaseModel):
    """评测用例集合

    对应 judge_cases/<slug>/<version>.json 文件格式。
    """
    problem_slug: str = Field(..., description="题目 slug")
    version: str = Field(..., description="用例版本")
    protocol_version: str = Field(..., description="执行协议版本")
    public_cases: list[TestCase] = Field(default_factory=list, description="公开用例")
    hidden_cases: list[TestCase] = Field(default_factory=list, description="隐藏用例")

    @property
    def all_cases(self) -> list[TestCase]:
        """返回所有用例（公开 + 隐藏）"""
        return self.public_cases + self.hidden_cases


class JudgeResult(BaseModel):
    """评测结果摘要

    对应 POST /api/evaluations 的响应格式。
    不包含源码、原始输出、隐藏输入或期望答案。
    """
    problem_id: int = Field(..., description="题目 ID")
    problem_slug: str = Field(..., description="题目 slug")
    language: str = Field(..., description="编程语言")
    status: EvaluationStatus = Field(..., description="评测状态")
    case_version: str = Field(..., description="用例版本")
    case_count: int = Field(..., ge=0, description="用例总数")
    executed_count: int = Field(..., ge=0, description="已执行用例数")
    passed_count: int = Field(..., ge=0, description="通过用例数")
    failed_case_index: Optional[int] = Field(
        default=None,
        description="首个失败用例的序号（从 0 开始），AC 时为 null"
    )
    summary: str = Field(..., description="评测摘要")

"""benchmark-v1 的安全摘要契约；不接受候选正文和原始异常。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.candidate_generation import CandidateOutput


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, pattern=r"^\S+$")]


class ProblemManifest(Contract):
    problem_id: int = Field(gt=0, strict=True)
    split: Literal["smoke", "development", "holdout"]
    statement_sha256: Sha256
    cases_sha256: Sha256
    case_version: Identifier


class StrategyManifest(Contract):
    strategy_id: Identifier
    prompt_sha256: Sha256
    config_sha256: Sha256


class ProblemSnapshot(Contract):
    """策略可见的冻结题面；不携带 Catalog、用例或参考答案。"""

    problem_id: int = Field(gt=0, strict=True)
    slug: Identifier
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    allowed_languages: tuple[Literal["python", "cpp"], ...] = Field(min_length=1)


class BudgetConfig(Contract):
    max_calls: int = Field(gt=0, strict=True)
    max_output_tokens_per_call: int = Field(gt=0, strict=True)
    timeout_seconds: float = Field(gt=0)


class StrategyResult(Contract):
    """策略输出边界；不记录原始 Prompt、响应或异常正文。"""

    candidate: CandidateOutput | None = Field(default=None, repr=False)
    reason: Literal[
        "FORMAT_ERROR", "REFUSAL", "NO_CANDIDATE", "LANGUAGE_MISMATCH",
        "BUDGET_EXHAUSTED", "STRATEGY_TIMEOUT", "PROVIDER_ERROR", "UNKNOWN_ERROR", "CANCELLED",
    ] | None = None
    calls: int = Field(default=0, ge=0, strict=True)
    usage_calls: int = Field(default=0, ge=0, strict=True)
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def consistent(self) -> "StrategyResult":
        if self.usage_calls > self.calls:
            raise ValueError("usage coverage exceeds calls")
        if self.calls and self.usage_calls == self.calls:
            if self.input_tokens is None or self.output_tokens is None:
                raise ValueError("complete usage requires both token counts")
        elif self.input_tokens is not None or self.output_tokens is not None:
            raise ValueError("incomplete usage must not masquerade as complete totals")
        if self.candidate is not None and self.reason is not None:
            raise ValueError("successful candidate cannot have a failure reason")
        if self.candidate is None and self.reason is None:
            raise ValueError("missing candidate requires a controlled reason")
        return self


class ExperimentManifest(Contract):
    """只描述冻结条件，不提供运行授权，不接收数据库 URL 或凭据。"""

    rule_version: Literal["benchmark-v1"] = "benchmark-v1"
    language: Literal["python"] = "python"
    experiment_id: Identifier
    dataset_version: Identifier
    split_version: Identifier
    provider: Identifier
    model: Identifier
    price_version: Identifier
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    max_calls: int = Field(gt=0, strict=True)
    max_output_tokens_per_call: int = Field(gt=0, strict=True)
    strategy_timeout_seconds: float = Field(gt=0)
    experiment_cost_cap: float = Field(gt=0)
    sampling_parameters: dict[str, float | int | bool | None]
    provider_supports_seed: bool = Field(strict=True)
    scheduling_seed: int = Field(strict=True)
    statistics_seed: int = Field(strict=True)
    code_version: Identifier
    source_snapshot_sha256: Sha256
    source_files: tuple[Identifier, ...] = Field(min_length=1)
    checker_sha256: Sha256
    runtime_id: Literal["python-3.11-v1"]
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    execution_limits: dict[str, Annotated[int, Field(gt=0, strict=True)]] = Field(min_length=1)
    strategies: tuple[StrategyManifest, ...] = Field(min_length=1)
    problems: tuple[ProblemManifest, ...] = Field(min_length=1)
    repeats: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def unique_entries(self) -> "ExperimentManifest":
        if len({p.problem_id for p in self.problems}) != len(self.problems):
            raise ValueError("duplicate problem")
        if len({s.strategy_id for s in self.strategies}) != len(self.strategies):
            raise ValueError("duplicate strategy")
        return self

    def materialize(self, records: list["RunRecord"]) -> list["RunRecord"]:
        """校验记录归属，并显式保留所有未开始计划项；不覆盖已有事实。"""
        planned = {}
        for strategy in self.strategies:
            for problem in self.problems:
                for repeat in range(self.repeats):
                    row = RunRecord(
                        experiment_id=self.experiment_id, strategy_id=strategy.strategy_id,
                        problem_id=problem.problem_id, repeat_index=repeat,
                        split=problem.split, terminal_state="NOT_RUN",
                    )
                    planned[row.key] = row
        seen = set()
        for row in records:
            if row.key in seen:
                raise ValueError("duplicate run key")
            if row.key not in planned or row.split != planned[row.key].split:
                raise ValueError("record does not belong to manifest")
            seen.add(row.key)
            planned[row.key] = row
        return list(planned.values())


class RunRecord(Contract):
    experiment_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    problem_id: int = Field(gt=0, strict=True)
    repeat_index: int = Field(ge=0, strict=True)
    split: Literal["smoke", "development", "holdout"]
    terminal_state: Literal["AC", "STRATEGY_FAILURE", "INFRA_UNRESOLVED", "NOT_RUN"]
    reason: Literal[
        "FORMAT_ERROR", "REFUSAL", "NO_CANDIDATE", "LANGUAGE_MISMATCH",
        "BUDGET_EXHAUSTED", "STRATEGY_TIMEOUT", "JUDGE_REJECTED",
        "PROVIDER_ERROR", "CONTROLLER_ERROR", "JUDGE_UKE", "UNKNOWN_ERROR",
        "VERSION_DRIFT", "SAFETY_STOP", "CANCELLED",
    ] | None = None
    judge_status: Literal["AC", "WA", "RE", "TLE", "MLE", "OLE", "UKE"] | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    generation_ms: float | None = Field(default=None, ge=0)
    evaluation_ms: float | None = Field(default=None, ge=0)
    source_sha256: Sha256 | None = None
    submission_id: str | None = Field(default=None, min_length=1)
    evaluation_id: str | None = Field(default=None, min_length=1)
    calls: int = Field(default=0, ge=0, strict=True)
    usage_calls: int = Field(default=0, ge=0, strict=True)
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    cost: float | None = Field(default=None, ge=0)
    price_version: str | None = Field(default=None, min_length=1)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @property
    def key(self) -> tuple[str, str, int, int]:
        return self.experiment_id, self.strategy_id, self.problem_id, self.repeat_index

    @model_validator(mode="after")
    def consistent(self) -> "RunRecord":
        if self.usage_calls > self.calls:
            raise ValueError("usage coverage exceeds calls")
        if self.calls and self.usage_calls == self.calls:
            if self.input_tokens is None or self.output_tokens is None:
                raise ValueError("complete usage requires both token counts")
        elif self.input_tokens is not None or self.output_tokens is not None:
            raise ValueError("incomplete usage must not masquerade as complete totals")
        if self.cost is not None and (
            not self.calls or self.usage_calls != self.calls
            or not self.price_version or not self.currency
        ):
            raise ValueError("cost requires complete usage and versioned prices")
        if self.terminal_state == "NOT_RUN":
            if self.calls or self.judge_status or any(value is not None for value in (
                self.duration_ms, self.generation_ms, self.evaluation_ms, self.cost,
            )):
                raise ValueError("NOT_RUN cannot contain execution facts")
            if self.reason not in (None, "SAFETY_STOP"):
                raise ValueError("invalid NOT_RUN reason")
        elif self.terminal_state == "AC":
            if self.judge_status != "AC" or self.reason is not None:
                raise ValueError("AC requires a successful Judge fact")
        elif self.terminal_state == "STRATEGY_FAILURE":
            if self.reason not in {
                "FORMAT_ERROR", "REFUSAL", "NO_CANDIDATE", "LANGUAGE_MISMATCH",
                "BUDGET_EXHAUSTED", "STRATEGY_TIMEOUT", "JUDGE_REJECTED",
            } or self.judge_status in {"AC", "UKE"}:
                raise ValueError("invalid strategy failure")
        elif self.reason not in {
            "PROVIDER_ERROR", "CONTROLLER_ERROR", "JUDGE_UKE", "UNKNOWN_ERROR", "VERSION_DRIFT", "CANCELLED",
        } or self.judge_status not in (None, "UKE"):
            raise ValueError("invalid infrastructure failure")
        return self


class BenchmarkSummary(Contract):
    rule_version: Literal["benchmark-v1"] = "benchmark-v1"
    experiment_id: str | None
    strategy_id: str | None
    problems: dict[int, "BenchmarkSummary"] = Field(default_factory=dict)
    split: str | None
    planned: int
    started: int
    valid: int
    unresolved: int
    not_run: int
    complete: bool
    final_ac_rate: float | None
    problem_ac_rates: dict[int, float | None]
    unresolved_rate: float | None
    success_lower_bound: float | None
    reasons: dict[str, int]
    calls: int
    mean_calls: float | None
    usage_coverage: float | None
    input_tokens: int | None
    output_tokens: int | None
    mean_input_tokens: float | None
    mean_output_tokens: float | None
    cost: float | None
    mean_cost: float | None
    price_version: str | None
    currency: str | None
    duration_median_ms: float | None
    duration_p95_ms: float | None
    generation_median_ms: float | None
    evaluation_median_ms: float | None
    infrastructure_median_ms: float | None
    infrastructure_p95_ms: float | None


class ComparisonSummary(Contract):
    baseline: BenchmarkSummary
    candidate: BenchmarkSummary
    valid_pairs: int
    excluded_pairs: dict[str, int]
    problem_differences: dict[int, float | None]
    difference: float | None
    confidence_interval: tuple[float, float] | None
    complete: bool
    seed: int
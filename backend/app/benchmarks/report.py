"""等题权统计、按题聚类 bootstrap 与安全 Markdown 摘要。"""

from collections import Counter, defaultdict
from html import escape
from math import ceil
from random import Random
from statistics import mean, median

from app.benchmarks.contracts import BenchmarkSummary, ComparisonSummary, RunRecord


VALID = {"AC", "STRATEGY_FAILURE"}


def _group(records: list[RunRecord]) -> None:
    if len({r.key for r in records}) != len(records):
        raise ValueError("duplicate run key")
    if len({(r.experiment_id, r.strategy_id, r.split) for r in records}) > 1:
        raise ValueError("mixed experiment/strategy/split group")


def _mean(values):
    return mean(values) if values else None


def _latency(records, field, percentile=False):
    values = [getattr(r, field) for r in records]
    # 缺失耗时不能静默缩小样本后宣称完整时延指标。
    if not values or any(v is None for v in values):
        return None
    return sorted(values)[ceil(0.95 * len(values)) - 1] if percentile else median(values)


def summarize(records: list[RunRecord]) -> BenchmarkSummary:
    return _summarize(records, include_problems=True)


def _summarize(records: list[RunRecord], *, include_problems: bool) -> BenchmarkSummary:
    _group(records)
    started = [r for r in records if r.terminal_state != "NOT_RUN"]
    valid = [r for r in records if r.terminal_state in VALID]
    infra = [r for r in records if r.terminal_state == "INFRA_UNRESOLVED"]
    by_problem = {}
    for problem in sorted({r.problem_id for r in records}):
        by_problem[problem] = _mean([int(r.terminal_state == "AC") for r in valid
                                    if r.problem_id == problem])
    calls = sum(r.calls for r in started)
    usage_calls = sum(r.usage_calls for r in started)
    input_tokens = output_tokens = None
    if started and calls == usage_calls:
        input_tokens = sum(r.input_tokens or 0 for r in started)
        output_tokens = sum(r.output_tokens or 0 for r in started)
    price_keys = {(r.price_version, r.currency) for r in started}
    cost = None
    price_version = currency = None
    if started and len(price_keys) == 1 and all(r.cost is not None for r in started):
        cost = sum(r.cost for r in started)
        price_version, currency = next(iter(price_keys))
    return BenchmarkSummary(
        experiment_id=records[0].experiment_id if records else None,
        strategy_id=records[0].strategy_id if records else None,
        problems={p: _summarize([r for r in records if r.problem_id == p], include_problems=False)
                  for p in by_problem} if include_problems else {},
        split=records[0].split if records else None,
        planned=len(records), started=len(started), valid=len(valid), unresolved=len(infra),
        not_run=len(records) - len(started), complete=bool(records) and len(records) == len(started),
        final_ac_rate=_mean([v for v in by_problem.values() if v is not None]),
        problem_ac_rates=by_problem,
        unresolved_rate=len(infra) / len(records) if records else None,
        success_lower_bound=sum(r.terminal_state == "AC" for r in records) / len(records)
        if records else None,
        reasons=dict(sorted(Counter(r.reason for r in records if r.reason).items())),
        calls=calls, mean_calls=calls / len(started) if started else None,
        usage_coverage=usage_calls / calls if calls else None,
        input_tokens=input_tokens, output_tokens=output_tokens,
        mean_input_tokens=input_tokens / len(started) if input_tokens is not None else None,
        mean_output_tokens=output_tokens / len(started) if output_tokens is not None else None,
        cost=cost, mean_cost=cost / len(started) if cost is not None else None,
        price_version=price_version, currency=currency,
        duration_median_ms=_latency(valid, "duration_ms"),
        duration_p95_ms=_latency(valid, "duration_ms", True),
        generation_median_ms=_latency(valid, "generation_ms"),
        evaluation_median_ms=_latency(valid, "evaluation_ms"),
        infrastructure_median_ms=_latency(infra, "duration_ms"),
        infrastructure_p95_ms=_latency(infra, "duration_ms", True),
    )


def compare(baseline: list[RunRecord], candidate: list[RunRecord], *, seed: int) -> ComparisonSummary:
    left_summary, right_summary = summarize(baseline), summarize(candidate)
    if baseline and candidate and (
        baseline[0].experiment_id != candidate[0].experiment_id
        or baseline[0].split != candidate[0].split
    ):
        raise ValueError("different experiment or split")
    left = {(r.problem_id, r.repeat_index): r for r in baseline}
    right = {(r.problem_id, r.repeat_index): r for r in candidate}
    differences = defaultdict(list)
    exclusions = Counter()
    for key in sorted(left.keys() | right.keys()):
        differences[key[0]]
        a, b = left.get(key), right.get(key)
        if a is None or b is None:
            exclusions["MISSING"] += 1
        elif "NOT_RUN" in (a.terminal_state, b.terminal_state):
            exclusions["NOT_RUN"] += 1
        elif "INFRA_UNRESOLVED" in (a.terminal_state, b.terminal_state):
            exclusions["INFRA_UNRESOLVED"] += 1
        else:
            differences[key[0]].append(int(b.terminal_state == "AC") - int(a.terminal_state == "AC"))
    problem_means = {p: _mean(v) for p, v in differences.items()}
    values = [v for v in problem_means.values() if v is not None]
    interval = None
    if len(values) > 1:
        rng = Random(seed)
        samples = sorted(mean(rng.choices(values, k=len(values))) for _ in range(10_000))
        # 经验分位数的线性插值；采样单位是整题，保留该题所有有效配对。
        def quantile(q):
            position = (len(samples) - 1) * q
            lower = int(position)
            return samples[lower] + (samples[ceil(position)] - samples[lower]) * (position - lower)
        interval = (quantile(0.025), quantile(0.975))
    return ComparisonSummary(
        baseline=left_summary, candidate=right_summary,
        valid_pairs=sum(len(v) for v in differences.values()),
        excluded_pairs=dict(sorted(exclusions.items())), problem_differences=problem_means,
        difference=_mean(values), confidence_interval=interval, seed=seed,
        complete=left_summary.complete and right_summary.complete and not exclusions["MISSING"],
    )


def render_markdown(summary: BenchmarkSummary, comparison: ComparisonSummary | None = None) -> str:
    if comparison is not None and summary != comparison.baseline:
        raise ValueError("summary must match comparison baseline")
    def value(item):
        if item is None:
            return "unknown"
        return escape(str(item)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")

    lines = ["# Benchmark 摘要", "", f"实验：{value(summary.experiment_id)}",
             f"策略：{value(summary.strategy_id)}", f"分集：{value(summary.split)}",
             "冒烟不能用于能力结论；AC 仅表示通过冻结用例。" if summary.split == "smoke"
             else "仅描述冻结题集与条件下的观察，不宣称普遍提升。", "",
             "| 指标 | 值 |", "| --- | --- |"]
    for field, title in (
        ("planned", "计划数"), ("started", "已启动"), ("valid", "有效运行"),
        ("not_run", "NOT_RUN"), ("unresolved", "基础设施未决"),
        ("final_ac_rate", "等题权 AC 率"), ("success_lower_bound", "成功下界"),
        ("unresolved_rate", "未决率"), ("mean_calls", "平均调用数"),
        ("usage_coverage", "usage 覆盖率"), ("mean_input_tokens", "平均输入 token"),
        ("mean_output_tokens", "平均输出 token"), ("mean_cost", "平均费用"),
        ("price_version", "价格版本"), ("currency", "币种"),
        ("duration_median_ms", "有效耗时中位数 ms"), ("duration_p95_ms", "有效耗时 P95 ms"),
        ("generation_median_ms", "生成中位数 ms"), ("evaluation_median_ms", "评测中位数 ms"),
        ("infrastructure_p95_ms", "基础设施耗时 P95 ms"),
    ):
        lines.append(f"| {title} | {value(getattr(summary, field))} |")
    lines.extend(["", f"逐题 AC 率：{summary.problem_ac_rates}", f"失败分类：{summary.reasons}"])
    lines.extend(["", "## 逐题资源", "",
                  "| 题目 | 计划/已启动/有效/未决/未运行 | 平均调用 | 输入/输出 token 总量 | usage 覆盖 | 平均费用 |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for problem, item in summary.problems.items():
        lines.append(
            f"| {problem} | {item.planned}/{item.started}/{item.valid}/{item.unresolved}/{item.not_run}"
            f" | {value(item.mean_calls)} | {value(item.input_tokens)}/{value(item.output_tokens)}"
            f" | {value(item.usage_coverage)} | {value(item.mean_cost)} |"
        )
    if not summary.complete or (comparison is not None and not comparison.complete):
        lines.append("实验未完成，不能宣称比较完成或策略收益。")
    if comparison is not None:
        lines.extend(["", f"## 基线 {value(comparison.baseline.strategy_id)}",
                      "以上为基线完整摘要。", "",
                      f"## 候选 {value(comparison.candidate.strategy_id)}",
                      render_markdown(comparison.candidate), "## 配对比较"])
        delta = comparison.difference
        lines.extend([f"配对差值（百分点）：{'unknown' if delta is None else f'{delta * 100:.2f}'}",
                      f"95% 区间（比例）：{value(comparison.confidence_interval)}",
                      f"逐题差值：{comparison.problem_differences}",
                      f"排除配对：{comparison.excluded_pairs}",
                      f"统计种子：{comparison.seed}；按题聚类 bootstrap 10000 次"])
        if comparison.confidence_interval is None or (
            comparison.confidence_interval[0] <= 0 <= comparison.confidence_interval[1]
        ):
            lines.append("证据不足。")
    return "\n".join(lines) + "\n"
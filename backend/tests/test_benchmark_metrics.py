"""benchmark-v1 第 3、5 节的纯统计验收，不调用外部服务。"""

import pytest
from pydantic import ValidationError

from app.benchmarks.contracts import RunRecord
from app.benchmarks.report import compare, render_markdown, summarize


def record(problem=1, repeat=0, state="AC", strategy="B0", **changes):
    data = dict(
        experiment_id="exp", strategy_id=strategy, problem_id=problem,
        repeat_index=repeat, split="smoke", terminal_state=state,
        reason=None if state in {"AC", "NOT_RUN"} else "FORMAT_ERROR",
        judge_status="AC" if state == "AC" else None,
    )
    if state != "NOT_RUN":
        data.update(duration_ms=100, generation_ms=80, evaluation_ms=20,
                    calls=1, usage_calls=1, input_tokens=10, output_tokens=5)
    if state == "INFRA_UNRESOLVED":
        data.update(reason="PROVIDER_ERROR")
    data.update(changes)
    return RunRecord(**data)


def test_fixed_spec_example_and_bootstrap():
    baseline = [record(p, i, "AC" if i < p else "STRATEGY_FAILURE")
                for p in (1, 2) for i in range(3)]
    candidate = [record(p, i, "AC" if i < 2 else "STRATEGY_FAILURE", "S1")
                 for p in (1, 2) for i in range(3)]
    assert summarize(baseline).final_ac_rate == pytest.approx(0.5)
    result = compare(baseline, candidate, seed=7)
    assert result.difference == pytest.approx(1 / 6)
    assert result.valid_pairs == 6
    assert result.confidence_interval == pytest.approx((0, 1 / 3))
    assert result == compare(list(reversed(baseline)), candidate, seed=7)


def test_equal_problem_weight_and_unresolved_are_not_zero():
    summary = summarize([record(), record(2, 0, "STRATEGY_FAILURE"),
                         record(2, 1, "STRATEGY_FAILURE"),
                         record(3, 0, "INFRA_UNRESOLVED"), record(4, 0, "NOT_RUN")])
    assert summary.final_ac_rate == 0.5
    assert summary.problem_ac_rates == {1: 1, 2: 0, 3: None, 4: None}
    assert (summary.planned, summary.started, summary.valid, summary.unresolved,
            summary.not_run) == (5, 4, 3, 1, 1)
    assert summary.unresolved_rate == 0.2
    assert summary.success_lower_bound == 0.2
    assert not summary.complete


def test_pair_exclusions_missing_and_single_problem_interval():
    left = [record(), record(2, state="INFRA_UNRESOLVED"),
            record(3, state="NOT_RUN"), record(4)]
    right = [record(strategy="S1"), record(2, strategy="S1"), record(3, strategy="S1")]
    result = compare(left, right, seed=0)
    assert result.excluded_pairs == {"INFRA_UNRESOLVED": 1, "NOT_RUN": 1, "MISSING": 1}
    assert result.difference == 0
    assert result.confidence_interval is None
    assert not result.complete
    assert compare(left[1:3], right[1:], seed=0).difference is None


def test_empty_unknown_usage_and_latency():
    empty = summarize([])
    assert empty.final_ac_rate is empty.usage_coverage is empty.duration_p95_ms is None
    assert empty.unresolved_rate is None
    summary = summarize([record(), record(repeat=1, usage_calls=0,
                                         input_tokens=None, output_tokens=None)])
    assert summary.usage_coverage == 0.5
    assert summary.input_tokens is summary.mean_input_tokens is summary.cost is None
    values = [record(repeat=i, duration_ms=i + 1) for i in range(20)]
    values.append(record(2, state="INFRA_UNRESOLVED", duration_ms=999))
    summary = summarize(values)
    assert summary.duration_p95_ms == 19
    assert summary.duration_median_ms == 10.5
    assert summary.infrastructure_p95_ms == 999


def test_constant_cluster_difference_and_safe_report():
    left = [record(p, state="STRATEGY_FAILURE") for p in (1, 2)]
    right = [record(p, strategy="S1") for p in (1, 2)]
    result = compare(left, right, seed=42)
    assert result.confidence_interval == (1, 1)
    text = render_markdown(summarize(left), result)
    assert "不能用于能力结论" in text
    assert "AC" in text and "unknown" in text
    assert "100.00" in text


def test_duplicate_and_mixed_groups_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        summarize([record(), record()])
    for changes in ({"strategy_id": "S1"}, {"experiment_id": "other"}, {"split": "holdout"}):
        with pytest.raises(ValueError, match="group"):
            summarize([record(), record(repeat=1, **changes)])
    with pytest.raises(ValueError, match="experiment"):
        compare([record()], [record(strategy="S1", experiment_id="other")], seed=0)


@pytest.mark.parametrize("changes", [
    {"source": "private"}, {"reason": "raw exception"}, {"calls": -1},
    {"duration_ms": float("nan")}, {"usage_calls": 2},
    {"terminal_state": "NOT_RUN"}, {"judge_status": "UKE"},
    {"input_tokens": None}, {"cost": 1},
])
def test_record_validation(changes):
    with pytest.raises(ValidationError):
        record(**changes)


def test_complete_usage_and_versioned_cost():
    summary = summarize([record(cost=0.2, price_version="v1", currency="USD"),
                         record(repeat=1, cost=0.4, price_version="v1", currency="USD")])
    assert summary.input_tokens == 20
    assert summary.mean_input_tokens == 10
    assert summary.cost == pytest.approx(0.6)
    assert summary.price_version == "v1"


def test_pair_means_do_not_weight_problems_by_repeat_count():
    left = [record(1, state="STRATEGY_FAILURE"), record(2), record(2, repeat=1)]
    right = [record(1, strategy="S1"), record(2, strategy="S1"),
             record(2, repeat=1, strategy="S1")]
    assert compare(left, right, seed=9).difference == 0.5


def test_report_escapes_price_metadata():
    summary = summarize([record(cost=1, price_version="<script>|price\nrow", currency="USD")])
    text = render_markdown(summary)
    assert "<script>" not in text
    assert "price\nrow" not in text


def test_mixed_price_versions_do_not_produce_total_cost():
    summary = summarize([record(cost=1, price_version="v1", currency="USD"),
                         record(repeat=1, cost=1, price_version="v2", currency="USD")])
    assert summary.cost is summary.mean_cost is summary.price_version is None


def manifest_payload():
    return dict(
        experiment_id="exp", dataset_version="smoke-v1", split_version="v1",
        provider="mock", model="test-only", price_version="test-v1", currency="USD",
        max_calls=2, max_output_tokens_per_call=100, strategy_timeout_seconds=10,
        experiment_cost_cap=1, sampling_parameters={"temperature": 0},
        provider_supports_seed=False, scheduling_seed=1, statistics_seed=2,
        code_version="test-snapshot", source_snapshot_sha256="a" * 64,
        source_files=["app/benchmarks/runner.py"],
        checker_sha256="b" * 64, runtime_id="python-3.11-v1",
        image_digest="sha256:" + "c" * 64,
        execution_limits={"wall_time_ms": 1000},
        strategies=[dict(strategy_id=s, prompt_sha256="d" * 64,
                         config_sha256="e" * 64) for s in ("B0", "S1")],
        problems=[dict(problem_id=p, split="smoke", statement_sha256="f" * 64,
                       cases_sha256="a" * 64, case_version="v1") for p in (1, 2)],
        repeats=2,
    )


def test_manifest_materializes_all_missing_plan_items():
    from app.benchmarks.contracts import ExperimentManifest
    manifest = ExperimentManifest(**manifest_payload())
    rows = manifest.materialize([record()])
    assert len(rows) == 8
    assert sum(r.terminal_state == "NOT_RUN" for r in rows) == 7
    assert summarize([r for r in rows if r.strategy_id == "B0"]).planned == 4
    for bad in ([record(), record()], [record(problem=3)], [record(split="holdout")]):
        with pytest.raises(ValueError):
            manifest.materialize(bad)
    assert manifest == ExperimentManifest.model_validate_json(manifest.model_dump_json())


@pytest.mark.parametrize("change", [
    {"max_calls": 0}, {"experiment_cost_cap": 0}, {"source_snapshot_sha256": "bad"},
    {"database_url": "not-allowed"}, {"repeats": True}, {"strategies": []},
])
def test_manifest_rejects_invalid_configuration(change):
    from app.benchmarks.contracts import ExperimentManifest
    with pytest.raises(ValidationError):
        ExperimentManifest(**(manifest_payload() | change))


def test_manifest_rejects_duplicate_problem_and_strategy():
    from app.benchmarks.contracts import ExperimentManifest
    for key in ("problems", "strategies"):
        payload = manifest_payload()
        payload[key].append(payload[key][0])
        with pytest.raises(ValidationError):
            ExperimentManifest(**payload)


def test_problem_resources_and_both_strategy_reports():
    left = summarize([record(), record(2, usage_calls=0, input_tokens=None, output_tokens=None)])
    assert left.problems[1].input_tokens == 10
    assert left.problems[2].input_tokens is None
    comparison = compare([record()], [record(strategy="S1", calls=2, usage_calls=2,
                                             input_tokens=999)], seed=0)
    text = render_markdown(comparison.baseline, comparison)
    assert "基线 B0" in text and "候选 S1" in text
    assert "999" in text and "逐题资源" in text
    with pytest.raises(ValueError):
        render_markdown(left, comparison)
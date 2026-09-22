import asyncio
from hashlib import sha256
import json

import pytest
from pydantic import ValidationError

from app.benchmarks.contracts import BudgetConfig, ExperimentManifest, ProblemSnapshot
from app.benchmarks.runner import (
    B0Strategy,
    B1Strategy,
    prepare_output_dir,
    append_jsonl,
    main,
    snapshot_hashes,
    validate_snapshot_hashes,
    strategy_failure_record,
    validate_run_mode,
    freeze_case_snapshot,
    temporary_benchmark_database,
    source_snapshot_sha256,
    validate_manifest_fingerprints,
)
from app.providers.base import CompletionResult, TokenUsage


def problem() -> ProblemSnapshot:
    return ProblemSnapshot(
        problem_id=1,
        slug="two-sum",
        title="Two Sum",
        statement="Return two indices whose values sum to target.",
        allowed_languages=("python",),
    )


def budget(max_calls=1) -> BudgetConfig:
    return BudgetConfig(max_calls=max_calls, max_output_tokens_per_call=100, timeout_seconds=1)


def candidate(source="def solve():\n    pass\n") -> str:
    return json.dumps({"language": "python", "source": source})


@pytest.mark.asyncio
async def test_b0_generates_one_structured_candidate_and_counts_usage():
    class Provider:
        def __init__(self):
            self.prompts = []

        async def complete_with_metadata(self, prompt):
            self.prompts.append(prompt)
            return CompletionResult(
                text=candidate(), usage=TokenUsage(input_tokens=10, output_tokens=5)
            )

    provider = Provider()
    result = await B0Strategy(provider).generate(problem(), budget())

    assert result.candidate is not None
    assert result.candidate.language == "python"
    assert result.reason is None
    assert (result.calls, result.usage_calls, result.input_tokens, result.output_tokens) == (1, 1, 10, 5)
    assert len(provider.prompts) == 1
    assert "hidden" not in provider.prompts[0].lower()


@pytest.mark.asyncio
async def test_b0_budget_expiry_is_strategy_failure_without_candidate():
    class Provider:
        async def complete_with_metadata(self, prompt):
            await asyncio.sleep(1)

    limits = BudgetConfig(max_calls=1, max_output_tokens_per_call=100, timeout_seconds=0.001)
    result = await B0Strategy(Provider()).generate(problem(), limits)

    assert result.candidate is None
    assert result.reason == "STRATEGY_TIMEOUT"
    assert result.calls == 1


def test_budget_rejects_zero_calls():
    with pytest.raises(ValidationError):
        budget(max_calls=0)


def test_output_directory_must_not_overwrite_existing_experiment(tmp_path):
    output = tmp_path / "experiment"
    output.mkdir()

    with pytest.raises(FileExistsError):
        prepare_output_dir(output)


def test_real_mode_requires_cost_boundary_and_known_usage():
    with pytest.raises(ValueError, match="cost boundary"):
        validate_run_mode("real", cost_cap=1, usage_is_reliable=False)
    assert validate_run_mode("mock", cost_cap=None, usage_is_reliable=False) is None
    assert validate_run_mode("real", cost_cap=1, usage_is_reliable=True) is None


def test_manifest_fingerprints_require_exact_sources_checker_and_python_runtime(tmp_path):
    root = tmp_path / "project"
    source = root / "app" / "benchmarks" / "runner.py"
    checker = root / "app" / "judges" / "evaluator.py"
    source.parent.mkdir(parents=True)
    checker.parent.mkdir(parents=True)
    source.write_text("runner-v1")
    checker.write_text("checker-v1")
    from tests.test_benchmark_metrics import manifest_payload

    payload = manifest_payload() | {
        "source_files": ["app/benchmarks/runner.py"],
        "source_snapshot_sha256": source_snapshot_sha256(root, ["app/benchmarks/runner.py"]),
        "checker_sha256": sha256(checker.read_bytes()).hexdigest(),
        "image_digest": "sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534",
        "execution_limits": {"wall_time_ms": 5000, "memory_mb": 128,
                             "memory_swap_mb": 128, "pids_limit": 32,
                             "max_source_bytes": 65536, "max_input_bytes": 65536,
                             "max_output_bytes": 65536},
    }
    manifest = ExperimentManifest.model_validate(payload)

    validate_manifest_fingerprints(manifest, project_root=root,
                                   checker_file="app/judges/evaluator.py")
    source.write_text("drift")
    with pytest.raises(ValueError, match="source snapshot"):
        validate_manifest_fingerprints(manifest, project_root=root,
                                       checker_file="app/judges/evaluator.py")


@pytest.mark.parametrize("bad_path", ["../secret.py", "/etc/passwd", "app/link.py"])
def test_source_snapshot_rejects_paths_outside_project_or_symlinks(tmp_path, bad_path):
    root = tmp_path / "project"
    root.mkdir()
    if bad_path == "app/link.py":
        (root / "app").mkdir()
        (root / bad_path).symlink_to(tmp_path / "outside.py")
    with pytest.raises(ValueError, match="source snapshot path"):
        source_snapshot_sha256(root, [bad_path])


@pytest.mark.asyncio
async def test_b0_invalid_structured_output_is_format_failure():
    class Provider:
        async def complete_with_metadata(self, prompt):
            return CompletionResult(text="not json")

    result = await B0Strategy(Provider()).generate(problem(), budget())

    assert result.candidate is None
    assert result.reason == "FORMAT_ERROR"
    assert result.calls == 1
    assert result.usage_calls == 0


@pytest.mark.asyncio
async def test_b1_self_check_stays_within_budget_and_keeps_last_valid_candidate():
    class Provider:
        def __init__(self):
            self.prompts = []

        async def complete_with_metadata(self, prompt):
            self.prompts.append(prompt)
            texts = [candidate("def solve():\n    return 1\n"), "not json", candidate()]
            return CompletionResult(text=texts[len(self.prompts) - 1])

    provider = Provider()
    result = await B1Strategy(provider).generate(problem(), budget(max_calls=3))

    assert result.candidate is not None
    assert result.candidate.source == "def solve():\n    pass\n"
    assert result.calls == 3
    assert result.reason is None
    assert all("hidden" not in prompt.lower() for prompt in provider.prompts)
    assert all("judge" not in prompt.lower() for prompt in provider.prompts)


@pytest.mark.asyncio
async def test_strategy_provider_error_is_controlled_failure_and_does_not_leak_error():
    class Provider:
        async def complete_with_metadata(self, prompt):
            raise RuntimeError("secret response and api-key")

    result = await B0Strategy(Provider()).generate(problem(), budget())

    assert result.candidate is None
    assert result.reason == "PROVIDER_ERROR"
    assert "secret response" not in repr(result)
    assert "api-key" not in repr(result)


def test_strategy_failure_record_preserves_calls_and_monotonic_duration():
    class Result:
        reason = "PROVIDER_ERROR"
        calls = 1
        usage_calls = 0
        input_tokens = None
        output_tokens = None

    record = strategy_failure_record(
        experiment_id="exp",
        strategy_id="B0",
        problem_id=1,
        repeat_index=0,
        split="smoke",
        result=Result(),
        duration_ms=12.5,
    )

    assert record.terminal_state == "INFRA_UNRESOLVED"
    assert record.reason == "PROVIDER_ERROR"
    assert record.calls == 1
    assert record.duration_ms == 12.5


def test_strategy_failure_record_maps_format_and_budget_to_strategy_failure():
    for reason in ("FORMAT_ERROR", "BUDGET_EXHAUSTED", "STRATEGY_TIMEOUT"):
        class Result:
            calls = 1
            usage_calls = 1
            input_tokens = 2
            output_tokens = 3

        Result.reason = reason
        record = strategy_failure_record(
            experiment_id="exp", strategy_id="B0", problem_id=1, repeat_index=0,
            split="smoke", result=Result(), duration_ms=1,
        )
        assert record.terminal_state == "STRATEGY_FAILURE"


def test_snapshot_hashes_are_canonical_and_drift_is_rejected():
    statement = "Return two indices."
    cases = b'{"version":"v1","cases":[]}'
    hashes = snapshot_hashes(statement, cases)
    assert hashes == {
        "statement_sha256": sha256(statement.encode()).hexdigest(),
        "cases_sha256": sha256(cases).hexdigest(),
    }
    validate_snapshot_hashes(statement, cases, hashes)
    with pytest.raises(ValueError, match="snapshot drift"):
        validate_snapshot_hashes(statement + " changed", cases, hashes)


def test_jsonl_output_contains_only_run_fact_and_rejects_candidate_body(tmp_path):
    record = strategy_failure_record(
        experiment_id="exp", strategy_id="B0", problem_id=1, repeat_index=0,
        split="smoke", result=type("Result", (), {
            "reason": "FORMAT_ERROR", "calls": 1, "usage_calls": 0,
            "input_tokens": None, "output_tokens": None,
        })(), duration_ms=1,
    )
    path = tmp_path / "runs.jsonl"
    append_jsonl(path, record)
    data = json.loads(path.read_text())
    assert data["terminal_state"] == "STRATEGY_FAILURE"
    assert "source" not in data and "candidate" not in data and "prompt" not in data


def test_freeze_case_snapshot_copies_only_validated_case_files_and_rejects_drift(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    case_file = source / "two-sum" / "v1.json"
    case_file.parent.mkdir()
    case_file.write_text('{"problem_slug":"two-sum","version":"v1","all_cases":[]}', encoding="utf-8")
    destination = tmp_path / "snapshot"

    snapshot = freeze_case_snapshot(
        source, destination, [("two-sum", "v1", sha256(case_file.read_bytes()).hexdigest())]
    )
    assert snapshot == destination
    assert (destination / "two-sum" / "v1.json").read_bytes() == case_file.read_bytes()

    assert (destination / "two-sum" / "v1.json").stat().st_mode & 0o222 == 0
    (destination / "two-sum" / "v1.json").chmod(0o600)

    (destination / "two-sum" / "v1.json").write_text("drift", encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot drift"):
        freeze_case_snapshot(
            source, destination, [("two-sum", "v1", sha256(case_file.read_bytes()).hexdigest())]
        )


def test_freeze_case_snapshot_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="invalid case path"):
        freeze_case_snapshot(tmp_path, tmp_path / "snapshot", [("../secret", "v1", "a" * 64)])


@pytest.mark.asyncio
async def test_temporary_benchmark_database_isolated_and_creates_schema(tmp_path):
    from sqlalchemy import inspect

    async with temporary_benchmark_database(tmp_path) as database:
        assert database.path.parent == tmp_path
        async with database.session_factory() as session:
            tables = await session.run_sync(lambda sync: inspect(sync.connection()).get_table_names())
        assert {"accounts", "problems", "submissions", "evaluations"}.issubset(tables)
    assert not database.path.exists()


def test_freeze_case_snapshot_rejects_destination_symlink(tmp_path):
    source = tmp_path / "source"
    (source / "two-sum").mkdir(parents=True)
    data = b"{}"
    (source / "two-sum" / "v1.json").write_bytes(data)
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "snapshot"
    destination.mkdir()
    (destination / "two-sum").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="invalid case path"):
        freeze_case_snapshot(source, destination, [("two-sum", "v1", sha256(data).hexdigest())])
    assert not (outside / "v1.json").exists()


@pytest.mark.asyncio
async def test_temporary_databases_do_not_collide_and_cleanup_on_exception(tmp_path):
    async with temporary_benchmark_database(tmp_path) as first:
        with pytest.raises(RuntimeError, match="test failure"):
            async with temporary_benchmark_database(tmp_path) as second:
                assert first.path != second.path
                raise RuntimeError("test failure")
        assert not second.path.exists()
        assert first.path.exists()


@pytest.mark.asyncio
async def test_temporary_database_cleanup_when_schema_creation_fails(tmp_path, monkeypatch):
    from app.database import Base

    def fail(*args, **kwargs):
        raise RuntimeError("schema creation failed")

    monkeypatch.setattr(Base.metadata, "create_all", fail)
    with pytest.raises(RuntimeError, match="schema creation failed"):
        async with temporary_benchmark_database(tmp_path):
            pytest.fail("must not yield a partially initialized database")
    assert not list(tmp_path.glob("benchmark-*.sqlite3"))


def test_cli_mock_freezes_manifest_without_running_real_provider(tmp_path):
    from tests.test_benchmark_metrics import manifest_payload

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_payload()), encoding="utf-8")
    output = tmp_path / "out"

    with pytest.raises(ValueError, match="problem snapshots"):
        main(["--manifest", str(manifest), "--output-dir", str(output), "--mode", "mock"])
    assert not output.exists()


def test_cli_rejects_fingerprint_drift_before_creating_output(tmp_path):
    from tests.test_benchmark_metrics import manifest_payload

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_payload() | {"source_snapshot_sha256": "a" * 64}))
    output = tmp_path / "out"
    problems = tmp_path / "problems.json"
    problems.write_text("[]")

    with pytest.raises(ValueError, match="source snapshot"):
        main(["--manifest", str(manifest), "--problems", str(problems),
              "--case-dir", str(tmp_path), "--output-dir", str(output)])
    assert not output.exists()


def test_cli_real_mode_is_rejected_without_usage_reliability(tmp_path):
    from tests.test_benchmark_metrics import manifest_payload

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_payload()), encoding="utf-8")
    output = tmp_path / "out"

    with pytest.raises(ValueError, match="reliable usage"):
        main(["--manifest", str(manifest), "--output-dir", str(output), "--mode", "real"])
    assert not output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", [B0Strategy, B1Strategy])
async def test_strategies_reject_non_python_candidates(strategy):
    class Provider:
        async def complete_with_metadata(self, prompt):
            return CompletionResult(text=json.dumps({"language": "cpp", "source": "int main(){}"}))

    result = await strategy(Provider()).generate(problem(), budget())
    assert result.candidate is None
    assert result.reason == "LANGUAGE_MISMATCH"


@pytest.mark.asyncio
async def test_b1_final_invalid_revision_keeps_previous_candidate():
    class Provider:
        calls = 0

        async def complete_with_metadata(self, prompt):
            self.calls += 1
            return CompletionResult(text=candidate("print(42)") if self.calls == 1 else "invalid")

    result = await B1Strategy(Provider()).generate(problem(), budget(2))
    assert result.reason is None
    assert result.candidate.source == "print(42)"
    assert result.calls == 2


@pytest.mark.asyncio
async def test_unknown_provider_exception_is_not_network_failure():
    class Provider:
        async def complete_with_metadata(self, prompt):
            raise KeyError("private programming error")

    result = await B0Strategy(Provider()).generate(problem(), budget())
    assert result.reason == "UNKNOWN_ERROR"
    assert result.calls == 1


@pytest.mark.asyncio
async def test_meter_is_fresh_for_each_strategy_run(monkeypatch):
    from app.providers.base import MeteredProvider
    import app.benchmarks.runner as runner

    meters = []

    class TrackingMeter(MeteredProvider):
        def __init__(self, provider):
            super().__init__(provider)
            meters.append(self)

    class Provider:
        async def complete_with_metadata(self, prompt):
            return CompletionResult(text=candidate())

    monkeypatch.setattr(runner, "MeteredProvider", TrackingMeter, raising=False)
    strategy = B1Strategy(Provider())
    for _ in range(2):
        result = await strategy.generate(problem(), budget(2))
        assert result.calls == 2
    assert len(meters) == 2
    assert [meter.calls for meter in meters] == [2, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy_type", [B0Strategy, B1Strategy])
async def test_reported_output_over_budget_rejects_candidate(strategy_type):
    class Provider:
        async def complete_with_metadata(self, prompt):
            return CompletionResult(text=candidate(), usage=TokenUsage(input_tokens=10, output_tokens=101))

    result = await strategy_type(Provider()).generate(problem(), budget())
    assert result.reason == "BUDGET_EXHAUSTED"
    assert result.candidate is None
    assert result.output_tokens == 101


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy_type", [B0Strategy, B1Strategy])
async def test_cancelled_strategy_keeps_attempt_accounting(strategy_type):
    class Provider:
        async def complete_with_metadata(self, prompt):
            raise asyncio.CancelledError()

    result = await strategy_type(Provider()).generate(problem(), budget())
    assert result.reason == "CANCELLED"
    assert result.calls == 1
    assert result.usage_calls == 0
    assert result.input_tokens is result.output_tokens is None
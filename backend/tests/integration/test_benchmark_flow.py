"""仅使用临时 SQLite 与 Fake Judge，不调用 Controller。"""

import json
from hashlib import sha256
import os

import pytest

from app.auth.models import Account, SubjectType
from app.benchmarks.contracts import BudgetConfig, ProblemSnapshot
from app.benchmarks.runner import B0Strategy, run_candidate, temporary_benchmark_database
from app.judges.base import JudgeResult
from app.judges.catalog import CaseCatalog
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.providers.base import CompletionResult
from app.services.submission_evaluations import SubmissionEvaluationService
from app.services.submissions import SubmissionService


controller_required = pytest.mark.skipif(
    os.getenv("ARENA_SANDBOX_INTEGRATION") != "1",
    reason="需要设置 ARENA_SANDBOX_INTEGRATION=1 并由用户启动 Go 执行控制器；测试会创建和删除临时 Arena Docker 资源",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,terminal,reason,permitted", [
    ("AC", "AC", None, True),
    ("WA", "STRATEGY_FAILURE", "JUDGE_REJECTED", True),
    ("UKE", "INFRA_UNRESOLVED", "JUDGE_UKE", True),
    (None, "INFRA_UNRESOLVED", "UNKNOWN_ERROR", False),
])
async def test_candidate_passes_real_services_once(tmp_path, status, terminal, reason, permitted):
    calls = []

    class Provider:
        async def complete_with_metadata(self, prompt):
            assert "private-canary" not in prompt
            calls.append("generate")
            return CompletionResult(text=json.dumps({"language": "python", "source": "print(1)"}))

    class Judge:
        async def evaluate(self, problem_id, slug, source, cases):
            calls.append("evaluate")
            return JudgeResult(
                problem_id=problem_id, problem_slug=slug, language="python", status=status,
                case_version=cases.version, case_count=1, executed_count=1,
                passed_count=int(status == "AC"), summary="controlled",
            )

    case_dir = tmp_path / "cases" / "two-sum"
    case_dir.mkdir(parents=True)
    (case_dir / "v1.json").write_text(json.dumps({
        "problem_slug": "two-sum", "version": "v1", "protocol_version": "json-stdio-v1",
        "hidden_cases": [{"input": {}, "expected": {}, "note": "private-canary"}],
    }))
    async with temporary_benchmark_database(tmp_path) as database:
        async with database.session_factory() as session:
            owner = Account(subject_type=SubjectType.AGENT, name="benchmark")
            problem = Problem(id=1, slug="two-sum", title="Two Sum", description="public")
            session.add_all([owner, problem])
            await session.flush()
            if permitted:
                session.add(ProblemSubmissionPermission(account_id=owner.id, problem_id=1))
            await session.commit()
            record = await run_candidate(
                experiment_id="exp", strategy_id="B0", repeat_index=0, split="smoke",
                problem=ProblemSnapshot(problem_id=1, slug="two-sum", title="Two Sum",
                                        statement="public", allowed_languages=("python",)),
                budget=BudgetConfig(max_calls=1, max_output_tokens_per_call=100, timeout_seconds=1),
                strategy=B0Strategy(Provider()), subject=owner,
                submissions=SubmissionService(session),
                evaluations=SubmissionEvaluationService(
                    session, case_catalog=CaseCatalog(tmp_path / "cases"),
                    evaluator_factory=lambda runtime: Judge(),
                ),
            )
            assert record.terminal_state == terminal
            assert record.reason == reason
            assert record.judge_status == status
            assert record.source_sha256 == sha256(b"print(1)").hexdigest()
            if permitted:
                assert record.submission_id and record.evaluation_id
            else:
                assert record.submission_id is None and record.evaluation_id is None
            assert record.duration_ms == pytest.approx(record.generation_ms + record.evaluation_ms)
            assert "private-canary" not in record.model_dump_json()
            assert "print(1)" not in record.model_dump_json()
    assert calls == (["generate", "evaluate"] if permitted else ["generate"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["AC", "WA", "UKE", "exception", "drift", "cancel", "controller", "judge-cancel"])
async def test_experiment_records_reports_and_safety_stop(tmp_path, status):
    from app.benchmarks import runner
    from app.benchmarks.contracts import ExperimentManifest, RunRecord
    from tests.test_benchmark_metrics import manifest_payload

    snapshots = [ProblemSnapshot(problem_id=i, slug=slug, title=slug,
                                 statement="public", allowed_languages=("python",))
                 for i, slug in [(1, "two-sum"), (2, "valid-parentheses")]]
    payload = manifest_payload()
    payload["strategies"] = [dict(strategy_id="B0", prompt_sha256="a" * 64,
                                  config_sha256="b" * 64)]
    payload["repeats"] = 2
    payload["problems"] = []
    source = tmp_path / "cases"
    for snapshot in snapshots:
        directory = source / snapshot.slug
        directory.mkdir(parents=True)
        data = json.dumps({"problem_slug": snapshot.slug, "version": "v1",
                           "protocol_version": "json-stdio-v1",
                           "hidden_cases": [{"input": {}, "expected": {}, "note": "private-canary"}]}).encode()
        (directory / "v1.json").write_bytes(data)
        payload["problems"].append(dict(problem_id=snapshot.problem_id, split="smoke",
                                        statement_sha256=sha256(b"public").hexdigest(),
                                        cases_sha256=sha256(data).hexdigest(), case_version="v1"))
    manifest = ExperimentManifest.model_validate(payload)
    output = tmp_path / "output"
    calls = []

    class Provider:
        async def complete_with_metadata(self, prompt):
            assert "private-canary" not in prompt
            calls.append("generate")
            if status == "exception":
                raise KeyError("private-canary")
            if status == "cancel":
                import asyncio
                raise asyncio.CancelledError()
            if status == "drift":
                for case in (output / "cases").glob("*/*.json"):
                    case.chmod(0o600)
                    case.write_text("{}")
            return CompletionResult(text=json.dumps({"language": "python", "source": "print(1)"}))

    class Judge:
        async def evaluate(self, problem_id, slug, code, cases):
            calls.append("evaluate")
            if status == "controller":
                from app.judges.client import ControllerUnavailableError
                raise ControllerUnavailableError("private-canary")
            if status == "judge-cancel":
                import asyncio
                raise asyncio.CancelledError()
            return JudgeResult(problem_id=problem_id, problem_slug=slug, language="python",
                               status=status, case_version=cases.version, case_count=1,
                               executed_count=1, passed_count=int(status == "AC"), summary="controlled")

    records = await runner.run_experiment(
        manifest, snapshots=snapshots, case_dir=source, output_dir=output,
        strategy_factory=lambda name: B0Strategy(Provider()),
        evaluator_factory=lambda runtime: Judge(),
    )
    saved = [RunRecord.model_validate_json(line) for line in (output / "runs.jsonl").read_text().splitlines()]
    assert {r.key for r in saved} == {r.key for r in records}
    assert len(records) == 4
    if status in {"exception", "drift", "cancel", "judge-cancel"}:
        assert calls == (["generate", "evaluate"] if status == "judge-cancel" else ["generate"])
        assert sum(r.terminal_state == "NOT_RUN" for r in records) == 3
        started = next(r for r in records if r.terminal_state != "NOT_RUN")
        assert started.reason == {"exception": "UNKNOWN_ERROR", "drift": "VERSION_DRIFT",
                                  "cancel": "CANCELLED", "judge-cancel": "CANCELLED"}[status]
        assert started.calls == 1
    elif status == "controller":
        assert next(r for r in records if r.terminal_state != "NOT_RUN").reason == "CONTROLLER_ERROR"
        assert sum(r.terminal_state == "NOT_RUN" for r in records) == 3
    else:
        assert calls.count("generate") == calls.count("evaluate") == 4
        assert {r.judge_status for r in records} == {status}
    report = (output / "report.md").read_text()
    assert "不能用于能力结论" in report
    assert "不可重放" in report
    assert "private-canary" not in report + (output / "runs.jsonl").read_text()
    assert "print(1)" not in report + (output / "runs.jsonl").read_text()
    assert not list(output.glob("*.sqlite3"))

    if status == "AC":
        import asyncio

        cli_payload = manifest.model_dump(mode="json")
        backend_root = __import__("pathlib").Path(__file__).resolve().parents[2]
        cli_payload.update({
            "source_snapshot_sha256": runner.source_snapshot_sha256(
                backend_root, cli_payload["source_files"]),
            "checker_sha256": sha256((backend_root / "app/judges/evaluator.py").read_bytes()).hexdigest(),
            "image_digest": "sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534",
            "execution_limits": {"wall_time_ms": 5000, "memory_mb": 128,
                                 "memory_swap_mb": 128, "pids_limit": 32,
                                 "max_source_bytes": 65536, "max_input_bytes": 65536,
                                 "max_output_bytes": 65536},
        })
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(cli_payload))
        problem_file = tmp_path / "problems.json"
        problem_file.write_text(json.dumps([p.model_dump(mode="json") for p in snapshots]))
        cli_output = tmp_path / "cli-output"
        assert await asyncio.to_thread(runner.main, [
            "--manifest", str(manifest_file), "--problems", str(problem_file),
            "--case-dir", str(source), "--output-dir", str(cli_output),
        ]) == 0
        cli_records = [RunRecord.model_validate_json(line) for line in
                       (cli_output / "runs.jsonl").read_text().splitlines()]
        assert len(cli_records) == 4
        assert {r.reason for r in cli_records} == {"JUDGE_UKE"}
        assert (cli_output / "report.md").exists()


@controller_required
@pytest.mark.asyncio
async def test_benchmark_runner_uses_real_controller_only_when_explicitly_enabled(tmp_path):
    """真实 Docker 评测门禁：必须由用户单独授权，默认跳过。"""
    from app.config import Settings
    from app.judges.client import PYTHON_RUNTIME_V1
    from tests.integration.test_submission_evaluation_flow import PYTHON_TWO_SUM_CORRECT

    case_root = __import__("pathlib").Path(__file__).resolve().parents[2] / "judge_cases"
    async with temporary_benchmark_database(tmp_path) as database:
        async with database.session_factory() as session:
            owner = Account(subject_type=SubjectType.AGENT, name="benchmark-controller-gate")
            problem = Problem(id=1, slug="two-sum", title="Two Sum", description="public")
            session.add_all([owner, problem])
            await session.flush()
            session.add(ProblemSubmissionPermission(account_id=owner.id, problem_id=problem.id))
            await session.commit()

            class Strategy:
                async def generate(self, _problem, _budget):
                    from app.services.candidate_generation import CandidateGeneration
                    return runner.StrategyResult(
                        candidate=CandidateGeneration.from_payload({"language": "python", "source": PYTHON_TWO_SUM_CORRECT}),
                        calls=0, usage_calls=0,
                    )

            record = await runner.run_candidate(
                experiment_id="controller-gate", strategy_id="B0", repeat_index=0, split="smoke",
                problem=ProblemSnapshot(problem_id=1, slug="two-sum", title="Two Sum",
                                        statement="public", allowed_languages=("python",)),
                budget=BudgetConfig(max_calls=1, max_output_tokens_per_call=100, timeout_seconds=10),
                strategy=Strategy(), subject=owner, submissions=SubmissionService(session),
                evaluations=SubmissionEvaluationService(
                    session,
                    settings=Settings(_env_file=None, sandbox_controller_url="http://127.0.0.1:8001",
                                      sandbox_controller_timeout_seconds=10),
                    case_catalog=CaseCatalog(case_root),
                ),
            )
    assert record.terminal_state == "AC"
    assert record.judge_status == "AC"
    assert record.evaluation_id is not None
    assert record.source_sha256 == sha256(PYTHON_TWO_SUM_CORRECT.encode()).hexdigest()
    assert PYTHON_RUNTIME_V1 == "python-3.11-v1"
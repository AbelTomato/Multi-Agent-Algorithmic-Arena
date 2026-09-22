"""离线 Benchmark 策略适配及隔离快照、临时数据库基础设施。"""

import asyncio
import argparse
from hashlib import sha256
import json
import random
from pathlib import Path
from tempfile import NamedTemporaryFile
from contextlib import asynccontextmanager
import time
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.benchmarks.contracts import (
    BudgetConfig,
    ExperimentManifest,
    ProblemSnapshot,
    RunRecord,
    StrategyResult,
)
from app.providers.base import CompletionResult, MeteredProvider
from app.services.candidate_generation import CandidateGeneration, CandidateOutput
from app.database import Base
from app.auth.models import Account, SubjectType
from app.judges.catalog import CaseCatalog
from app.judges.client import ControllerError
from app.benchmarks.report import summarize, render_markdown
from app.models.evaluation import Evaluation  # noqa: F401
from app.models.permission import ProblemSubmissionPermission  # noqa: F401
from app.models.problem import Problem  # noqa: F401
from app.models.submission import Submission  # noqa: F401
from app.services.submissions import SubmissionService
from app.services.submission_evaluations import SubmissionEvaluationService


def prepare_output_dir(path: Path) -> Path:
    """创建新的实验目录，拒绝覆盖任何已有路径。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    return path


def validate_run_mode(mode: str, *, cost_cap: float | None, usage_is_reliable: bool) -> None:
    if mode not in {"mock", "real"}:
        raise ValueError("mode must be mock or real")
    if mode == "real" and (cost_cap is None or cost_cap <= 0 or not usage_is_reliable):
        raise ValueError("real mode requires a positive cost boundary and reliable usage")


def snapshot_hashes(statement: str, cases: bytes) -> dict[str, str]:
    return {
        "statement_sha256": sha256(statement.encode("utf-8")).hexdigest(),
        "cases_sha256": sha256(cases).hexdigest(),
    }


def validate_snapshot_hashes(statement: str, cases: bytes, expected: dict[str, str]) -> None:
    if snapshot_hashes(statement, cases) != expected:
        raise ValueError("snapshot drift")


def source_snapshot_sha256(project_root: Path, source_files: list[str] | tuple[str, ...]) -> str:
    """计算受限相对源码列表的稳定哈希，不扫描仓库外路径或符号链接。"""
    root = Path(project_root).resolve()
    digest = sha256()
    for relative in sorted(source_files):
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not relative or path.name != path.parts[-1]:
            raise ValueError("invalid source snapshot path")
        resolved = (root / path).resolve()
        if root not in resolved.parents or not resolved.is_file() or (root / path).is_symlink():
            raise ValueError("invalid source snapshot path")
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        data = resolved.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def validate_manifest_fingerprints(
    manifest: ExperimentManifest, *, project_root: Path, checker_file: str,
) -> None:
    """在任何输出/数据库副作用前，核验明确冻结的本地实验条件。"""
    root = Path(project_root).resolve()
    if source_snapshot_sha256(root, manifest.source_files) != manifest.source_snapshot_sha256:
        raise ValueError("source snapshot drift")
    checker = (root / checker_file).resolve()
    if root not in checker.parents or not checker.is_file() or (root / checker_file).is_symlink():
        raise ValueError("invalid checker fingerprint path")
    if sha256(checker.read_bytes()).hexdigest() != manifest.checker_sha256:
        raise ValueError("checker fingerprint drift")
    python_runtime = {
        "image_digest": "sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534",
        "execution_limits": {
            "wall_time_ms": 5000, "memory_mb": 128, "memory_swap_mb": 128,
            "pids_limit": 32, "max_source_bytes": 64 * 1024,
            "max_input_bytes": 64 * 1024, "max_output_bytes": 64 * 1024,
        },
    }
    if manifest.runtime_id != "python-3.11-v1" or manifest.image_digest != python_runtime["image_digest"]:
        raise ValueError("runtime fingerprint drift")
    if manifest.execution_limits != python_runtime["execution_limits"]:
        raise ValueError("execution limits fingerprint drift")


def freeze_case_snapshot(
    source_dir: Path,
    destination_dir: Path,
    cases: list[tuple[str, str, str]],
) -> Path:
    """复制清单指定的用例文件，并拒绝源或既有目标快照漂移。"""
    source_dir = Path(source_dir).resolve()
    destination_dir = Path(destination_dir).resolve()
    for slug, version, expected_hash in cases:
        relative = Path(slug) / f"{version}.json"
        if (
            not slug
            or not version
            or Path(slug).name != slug
            or Path(version).name != version
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            raise ValueError("invalid case path")
        source = (source_dir / relative).resolve()
        target = (destination_dir / relative).resolve()
        if destination_dir not in target.parents or target == source:
            raise ValueError("invalid case path")
        if source_dir not in source.parents or not source.is_file():
            raise ValueError("case snapshot source missing")
        source_bytes = source.read_bytes()
        if sha256(source_bytes).hexdigest() != expected_hash:
            raise ValueError("case snapshot source drift")
        if target.exists() and target.read_bytes() != source_bytes:
            raise ValueError("snapshot drift")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as handle:
                handle.write(source_bytes)
        target.chmod(0o444)
    return destination_dir


class TemporaryBenchmarkDatabase:
    def __init__(self, path: Path, engine, session_factory) -> None:
        self.path = path
        self.engine = engine
        self.session_factory = session_factory


async def run_candidate(
    *, experiment_id: str, strategy_id: str, repeat_index: int, split: str,
    problem: ProblemSnapshot, budget: BudgetConfig, strategy,
    subject: Account, submissions: SubmissionService,
    evaluations: SubmissionEvaluationService,
    verify_snapshot=None,
) -> RunRecord:
    """单次候选经正式权限服务评测；引用仅对当次临时库有效。

    本函数不负责快照或清单验证；调用方必须先冻结并核验实验条件。
    """
    started = time.monotonic()
    result = await strategy.generate(problem, budget)
    generated = time.monotonic()
    if result.candidate is None:
        return strategy_failure_record(
            experiment_id=experiment_id, strategy_id=strategy_id,
            problem_id=problem.problem_id, repeat_index=repeat_index, split=split,
            result=result, duration_ms=(generated - started) * 1000,
        )
    facts = dict(
        experiment_id=experiment_id, strategy_id=strategy_id, problem_id=problem.problem_id,
        repeat_index=repeat_index, split=split, calls=result.calls, usage_calls=result.usage_calls,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        generation_ms=(generated - started) * 1000,
        source_sha256=sha256(result.candidate.source.encode("utf-8")).hexdigest(),
    )
    try:
        submission = await submissions.create(
            subject, problem_id=problem.problem_id,
            language=result.candidate.language, source=result.candidate.source,
        )
        facts["submission_id"] = str(submission.id)
        if verify_snapshot is not None:
            await verify_snapshot()
        evaluation = await evaluations.evaluate(subject, submission.id)
        facts["evaluation_id"] = str(evaluation.id)
        status = evaluation.judge_status
        if status == "AC":
            terminal, reason = "AC", None
        elif status == "UKE":
            terminal, reason = "INFRA_UNRESOLVED", "JUDGE_UKE"
        elif status in {"WA", "RE", "TLE", "MLE", "OLE"}:
            terminal, reason = "STRATEGY_FAILURE", "JUDGE_REJECTED"
        else:
            status = None
            terminal, reason = "INFRA_UNRESOLVED", "UNKNOWN_ERROR"
    except SnapshotDrift:
        status = None
        terminal, reason = "INFRA_UNRESOLVED", "VERSION_DRIFT"
    except asyncio.CancelledError:
        status = None
        terminal, reason = "INFRA_UNRESOLVED", "CANCELLED"
    except ControllerError:
        status = None
        terminal, reason = "INFRA_UNRESOLVED", "CONTROLLER_ERROR"
    except Exception:
        status = None
        terminal, reason = "INFRA_UNRESOLVED", "UNKNOWN_ERROR"
    finished = time.monotonic()
    return RunRecord(
        **facts, terminal_state=terminal, reason=reason, judge_status=status,
        duration_ms=(finished - started) * 1000,
        evaluation_ms=(finished - generated) * 1000,
    )


@asynccontextmanager
async def temporary_benchmark_database(parent_dir: Path):
    """创建仅供一次实验使用的 SQLite，并在退出时释放文件。"""
    with NamedTemporaryFile(dir=parent_dir, prefix="benchmark-", suffix=".sqlite3") as temporary:
        path = Path(temporary.name)
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        try:
            session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            yield TemporaryBenchmarkDatabase(path, engine, session_factory)
        finally:
            await engine.dispose()


def append_jsonl(path: Path, record: RunRecord) -> None:
    """只追加公开运行事实；RunRecord 不包含候选正文或原始响应。"""
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json() + "\n")


def load_manifest(path: Path) -> ExperimentManifest:
    """读取并严格校验冻结清单；不接受数据库 URL 或凭据字段。"""
    try:
        return ExperimentManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("invalid benchmark manifest") from error


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline benchmark harness")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("mock", "real"), default="mock")
    parser.add_argument("--problems", type=Path)
    parser.add_argument("--case-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_cli_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)
    validate_run_mode(
        args.mode,
        cost_cap=manifest.experiment_cost_cap,
        # 当前清单没有把 usage 可靠性作为独立冻结字段；real 必须显式扩展契约后再启用。
        usage_is_reliable=args.mode == "mock",
    )
    if args.problems is None or args.case_dir is None:
        raise ValueError("problem snapshots and case directory are required")
    validate_manifest_fingerprints(
        manifest,
        project_root=Path(__file__).resolve().parents[2],
        checker_file="app/judges/evaluator.py",
    )
    snapshots = [ProblemSnapshot.model_validate(item) for item in
                 json.loads(args.problems.read_text(encoding="utf-8"))]
    asyncio.run(run_experiment(
        manifest, snapshots=snapshots, case_dir=args.case_dir, output_dir=args.output_dir,
        strategy_factory=lambda name: {"B0": B0Strategy, "B1": B1Strategy}[name](MockProvider()),
        evaluator_factory=lambda runtime: MockJudge(),
    ))
    return 0


def strategy_failure_record(
    *, experiment_id: str, strategy_id: str, problem_id: int, repeat_index: int,
    split: str, result: StrategyResult, duration_ms: float,
) -> RunRecord:
    """把策略阶段事实转换为受控终态；不把未评测候选标成 AC。"""
    infra_reasons = {"PROVIDER_ERROR", "UNKNOWN_ERROR", "CANCELLED"}
    terminal_state = "INFRA_UNRESOLVED" if result.reason in infra_reasons else "STRATEGY_FAILURE"
    return RunRecord(
        experiment_id=experiment_id,
        strategy_id=strategy_id,
        problem_id=problem_id,
        repeat_index=repeat_index,
        split=split,
        terminal_state=terminal_state,
        reason=result.reason,
        duration_ms=duration_ms,
        generation_ms=duration_ms,
        calls=result.calls,
        usage_calls=result.usage_calls,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


class MetadataProvider(Protocol):
    async def complete_with_metadata(self, prompt: str) -> CompletionResult:
        ...


def _prompt(problem: ProblemSnapshot, previous: CandidateOutput | None = None) -> str:
    payload = {
        "title": problem.title,
        "statement": problem.statement,
        "allowed_languages": list(problem.allowed_languages),
    }
    if previous is not None:
        payload["previous_candidate"] = previous.model_dump(mode="json")
        payload["instruction"] = "检查并修订你自己的候选；只返回结构化 JSON。"
    else:
        payload["instruction"] = "生成一个候选；只返回结构化 JSON。"
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class B0Strategy:
    """单 Agent、单次生成，无修复调用。"""

    def __init__(self, provider: MetadataProvider) -> None:
        self.provider = provider

    async def generate(self, problem: ProblemSnapshot, budget: BudgetConfig) -> StrategyResult:
        if budget.max_calls < 1:
            return StrategyResult(reason="BUDGET_EXHAUSTED")
        return await _single_call(MeteredProvider(self.provider), problem, budget)


class B1Strategy:
    """同预算单 Agent 自检；只保留最后一个成功解析的候选。"""

    def __init__(self, provider: MetadataProvider) -> None:
        self.provider = provider

    async def generate(self, problem: ProblemSnapshot, budget: BudgetConfig) -> StrategyResult:
        candidate = None
        meter = MeteredProvider(self.provider)
        reason = "FORMAT_ERROR"
        calls = usage_calls = input_tokens = output_tokens = 0
        deadline = time.monotonic() + budget.timeout_seconds
        for _ in range(budget.max_calls):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _result_failure(calls, usage_calls, input_tokens, output_tokens, "STRATEGY_TIMEOUT")
            try:
                result = await asyncio.wait_for(
                    meter.complete_with_metadata(_prompt(problem, candidate)),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                return _result_failure(calls + 1, usage_calls, input_tokens, output_tokens, "STRATEGY_TIMEOUT")
            except asyncio.CancelledError:
                return _result_failure(calls + 1, usage_calls, input_tokens, output_tokens, "CANCELLED")
            except RuntimeError:
                return _result_failure(calls + 1, usage_calls, input_tokens, output_tokens, "PROVIDER_ERROR")
            except Exception:
                return _result_failure(meter.calls, usage_calls, input_tokens, output_tokens, "UNKNOWN_ERROR")
            calls += 1
            usage_calls, input_tokens, output_tokens = _usage_totals(
                result, usage_calls, input_tokens, output_tokens
            )
            if result.usage and result.usage.output_tokens > budget.max_output_tokens_per_call:
                return _result_failure(calls, usage_calls, input_tokens, output_tokens, "BUDGET_EXHAUSTED")
            try:
                revision = CandidateGeneration.from_payload(json.loads(result.text))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if revision.language != "python" or revision.language not in problem.allowed_languages:
                reason = "LANGUAGE_MISMATCH"
                continue
            candidate = revision
        if candidate is None:
            return _result_failure(calls, usage_calls, input_tokens, output_tokens, reason)
        return StrategyResult(
            candidate=candidate, calls=calls, usage_calls=usage_calls,
            input_tokens=input_tokens if usage_calls == calls else None,
            output_tokens=output_tokens if usage_calls == calls else None,
        )


async def _single_call(provider, problem, budget) -> StrategyResult:
    try:
        result = await asyncio.wait_for(
            provider.complete_with_metadata(_prompt(problem)), timeout=budget.timeout_seconds
        )
    except asyncio.TimeoutError:
        return _result_failure(1, 0, 0, 0, "STRATEGY_TIMEOUT")
    except asyncio.CancelledError:
        return _result_failure(1, 0, 0, 0, "CANCELLED")
    except RuntimeError:
        return _result_failure(1, 0, 0, 0, "PROVIDER_ERROR")
    except Exception:
        return _result_failure(1, 0, 0, 0, "UNKNOWN_ERROR")
    usage_calls, input_tokens, output_tokens = _usage_totals(result, 0, 0, 0)
    if result.usage and result.usage.output_tokens > budget.max_output_tokens_per_call:
        return _result_failure(1, usage_calls, input_tokens, output_tokens, "BUDGET_EXHAUSTED")
    try:
        candidate = CandidateGeneration.from_payload(json.loads(result.text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return _result_failure(1, usage_calls, input_tokens, output_tokens, "FORMAT_ERROR")
    if candidate.language != "python" or candidate.language not in problem.allowed_languages:
        return _result_failure(1, usage_calls, input_tokens, output_tokens, "LANGUAGE_MISMATCH")
    return StrategyResult(
        candidate=candidate, calls=1, usage_calls=usage_calls,
        input_tokens=input_tokens if usage_calls == 1 else None,
        output_tokens=output_tokens if usage_calls == 1 else None,
    )


def _usage_totals(result, usage_calls, input_tokens, output_tokens):
    if result.usage is None:
        return usage_calls, input_tokens, output_tokens
    return (
        usage_calls + 1,
        input_tokens + result.usage.input_tokens,
        output_tokens + result.usage.output_tokens,
    )


def _result_failure(calls, usage_calls, input_tokens, output_tokens, reason):
    complete = usage_calls == calls
    return StrategyResult(
        reason=reason, calls=calls, usage_calls=usage_calls,
        input_tokens=input_tokens if complete else None,
        output_tokens=output_tokens if complete else None,
    )


class SnapshotDrift(ValueError):
    """冻结题面、版本或用例发生变化。"""


async def run_experiment(
    manifest: ExperimentManifest, *, snapshots: list[ProblemSnapshot],
    case_dir: Path, output_dir: Path, strategy_factory, evaluator_factory,
) -> list[RunRecord]:
    """隔离的 mock 集成协调器；依赖必须显式注入，不自动连接外部服务。"""
    problems = {p.problem_id: p for p in snapshots}
    if len(problems) != len(snapshots) or set(problems) != {p.problem_id for p in manifest.problems}:
        raise ValueError("problem snapshots do not match manifest")
    if any(s.strategy_id not in {"B0", "B1"} for s in manifest.strategies):
        raise ValueError("unsupported benchmark strategy")
    for entry in manifest.problems:
        snapshot = problems[entry.problem_id]
        if sha256(snapshot.statement.encode()).hexdigest() != entry.statement_sha256:
            raise SnapshotDrift("statement snapshot drift")
    output_dir = prepare_output_dir(output_dir)
    (output_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    frozen = freeze_case_snapshot(case_dir, output_dir / "cases", [
        (problems[p.problem_id].slug, p.case_version, p.cases_sha256) for p in manifest.problems
    ])
    budget = BudgetConfig(max_calls=manifest.max_calls,
                          max_output_tokens_per_call=manifest.max_output_tokens_per_call,
                          timeout_seconds=manifest.strategy_timeout_seconds)
    records = []
    stopped = False
    rng = random.Random(manifest.scheduling_seed)
    async with temporary_benchmark_database(output_dir) as database:
        async with database.session_factory() as session:
            owners = {}
            for strategy in manifest.strategies:
                owner = Account(subject_type=SubjectType.AGENT, name=strategy.strategy_id)
                session.add(owner)
                owners[strategy.strategy_id] = owner
            for entry in manifest.problems:
                snapshot = problems[entry.problem_id]
                session.add(Problem(id=snapshot.problem_id, slug=snapshot.slug, title=snapshot.title,
                                    description=snapshot.statement,
                                    allowed_languages=list(snapshot.allowed_languages),
                                    active_case_version=entry.case_version))
            await session.flush()
            for owner in owners.values():
                for entry in manifest.problems:
                    session.add(ProblemSubmissionPermission(account_id=owner.id, problem_id=entry.problem_id))
            await session.commit()
            for entry in manifest.problems:
                snapshot = problems[entry.problem_id]

                async def verify():
                    current = await session.get(Problem, snapshot.problem_id, populate_existing=True)
                    path = frozen / snapshot.slug / f"{entry.case_version}.json"
                    try:
                        if (current is None or current.active_case_version != entry.case_version
                                or current.slug != snapshot.slug or current.title != snapshot.title
                                or tuple(current.allowed_languages) != snapshot.allowed_languages
                                or path.is_symlink() or frozen not in path.resolve().parents):
                            raise ValueError("snapshot drift")
                        validate_snapshot_hashes(current.description, path.read_bytes(), {
                            "statement_sha256": entry.statement_sha256,
                            "cases_sha256": entry.cases_sha256,
                        })
                    except (OSError, ValueError) as error:
                        raise SnapshotDrift("snapshot drift") from error

                for repeat in range(manifest.repeats):
                    strategies = list(manifest.strategies)
                    rng.shuffle(strategies)
                    for strategy in strategies:
                        if stopped:
                            continue
                        started = time.monotonic()
                        try:
                            await verify()
                            record = await run_candidate(
                                experiment_id=manifest.experiment_id, strategy_id=strategy.strategy_id,
                                repeat_index=repeat, split=entry.split, problem=snapshot, budget=budget,
                                strategy=strategy_factory(strategy.strategy_id), subject=owners[strategy.strategy_id],
                                submissions=SubmissionService(session),
                                evaluations=SubmissionEvaluationService(
                                    session, case_catalog=CaseCatalog(frozen), evaluator_factory=evaluator_factory),
                                verify_snapshot=verify,
                            )
                            await session.commit()
                        except Exception as error:
                            await session.rollback()
                            record = RunRecord(
                                experiment_id=manifest.experiment_id, strategy_id=strategy.strategy_id,
                                problem_id=entry.problem_id, repeat_index=repeat, split=entry.split,
                                terminal_state="INFRA_UNRESOLVED",
                                reason="VERSION_DRIFT" if isinstance(error, SnapshotDrift) else "UNKNOWN_ERROR",
                                duration_ms=(time.monotonic() - started) * 1000,
                            )
                        records.append(record)
                        append_jsonl(output_dir / "runs.jsonl", record)
                        stopped = record.reason in {"UNKNOWN_ERROR", "VERSION_DRIFT", "CANCELLED", "CONTROLLER_ERROR"}
    complete = manifest.materialize(records)
    for record in complete:
        if record.terminal_state == "NOT_RUN":
            append_jsonl(output_dir / "runs.jsonl", record)
    sections = ["# Mock 链路验证", "不执行候选程序，不代表真实模型或 Judge 能力；不能用于能力结论。",
                "Submission/Evaluation ID 仅为临时库引用，实验结束后不可重放。",
                "usage 缺失时禁止等 token 结论；成本 unknown。版本指纹见 manifest.json。"]
    for strategy in manifest.strategies:
        for split in sorted({p.split for p in manifest.problems}):
            sections.append(render_markdown(summarize([
                r for r in complete if r.strategy_id == strategy.strategy_id and r.split == split
            ])))
    (output_dir / "report.md").write_text("\n\n".join(sections), encoding="utf-8")
    return complete


class MockProvider:
    """无网络固定响应；不读取隐藏用例，也不执行源码。"""

    async def complete_with_metadata(self, prompt: str) -> CompletionResult:
        return CompletionResult(text=json.dumps({"language": "python", "source": "print(1)"}))


class MockJudge:
    """仅验证服务编排，固定返回未决，绝不伪造真实 AC。"""

    async def evaluate(self, problem_id, slug, source, cases):
        from app.judges.base import JudgeResult

        return JudgeResult(problem_id=problem_id, problem_slug=slug, language="python",
                           status="UKE", case_version=cases.version,
                           case_count=len(cases.all_cases), executed_count=0, passed_count=0,
                           summary="Mock Judge: candidate was not executed")


if __name__ == "__main__":
    raise SystemExit(main())
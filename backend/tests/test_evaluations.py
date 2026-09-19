"""阶段 3 评测服务与 API 契约测试。"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.factory import get_agent
from app.api.evaluations import get_evaluation_service
from app.config import Settings, get_settings
from app.database import Base, get_db
from app.judges.base import EvaluationStatus, JudgeResult
from app.judges.catalog import CaseNotFoundError
from app.judges.client import (
    ControllerBusyError,
    ControllerResponseError,
    ControllerTimeoutError,
    ControllerUnavailableError,
)
from app.main import app
from app.models.evaluation_run import EvaluationErrorCategory, EvaluationRun, EvaluationRunStatus
from app.models.problem import Problem
from app.schemas.evaluation import EvaluationCreateResponse
from app.services.evaluations import (
    AgentEvaluationError,
    EvaluationDisabledError,
    EvaluationService,
    EvaluationTimeoutError,
    build_evaluation_prompt,
)


SESSION_HASH = "a" * 64


CORRECT_TWO_SUM_CODE = '''import json
import sys

data = json.loads(sys.stdin.read())
seen = {}
for index, number in enumerate(data["nums"]):
    complement = data["target"] - number
    if complement in seen:
        print(json.dumps({"indices": [seen[complement], index]}))
        break
    seen[number] = index
'''


class RecordingAgent:
    def __init__(self, response: str, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.response


class RecordingCatalog:
    def __init__(self, cases: object | Exception) -> None:
        self.cases = cases
        self.calls: list[tuple[str, str]] = []

    def load(self, problem_slug: str, version: str = "v1") -> object:
        self.calls.append((problem_slug, version))
        if isinstance(self.cases, Exception):
            raise self.cases
        return self.cases


class RecordingEvaluator:
    def __init__(self, result: JudgeResult | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def evaluate(
        self,
        problem_id: int,
        problem_slug: str,
        code: str,
        cases: object,
    ) -> JudgeResult:
        self.calls.append(
            {
                "problem_id": problem_id,
                "problem_slug": problem_slug,
                "code": code,
                "cases": cases,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def evaluation_response(code: str = CORRECT_TWO_SUM_CODE) -> str:
    import json

    return json.dumps({"language": "python", "code": code, "explanation": "线性扫描"})


def judge_result(status: EvaluationStatus = EvaluationStatus.AC) -> JudgeResult:
    return JudgeResult(
        problem_id=1,
        problem_slug="two-sum",
        language="python",
        status=status,
        case_version="v1",
        case_count=9,
        executed_count=9,
        passed_count=9,
        failed_case_index=None,
        summary="通过当前版本评测用例",
    )


@pytest.fixture
async def session(tmp_path) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evaluations.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as database_session:
        database_session.add(
            Problem(
                slug="two-sum",
                title="Two Sum",
                description="# Two Sum\nFind two numbers whose sum equals target.",
            )
        )
        await database_session.commit()
        yield database_session
    await engine.dispose()


def service(
    session: AsyncSession,
    agent: RecordingAgent,
    catalog: RecordingCatalog,
    evaluator: RecordingEvaluator,
    **settings_overrides: object,
) -> EvaluationService:
    settings = Settings(_env_file=None, evaluation_enabled=True, **settings_overrides)
    return EvaluationService(
        session=session,
        agent=agent,
        settings=settings,
        case_catalog=catalog,
        evaluator_factory=lambda: evaluator,
    )


class TestEvaluationPrompt:
    def test_includes_only_problem_public_cases_and_protocol(self) -> None:
        problem = Problem(id=1, slug="two-sum", title="Two Sum", description="题面")
        prompt = build_evaluation_prompt(
            problem,
            [
                {
                    "input": {"nums": [2, 7], "target": 9},
                    "expected": {"indices": [0, 1]},
                }
            ],
        )

        assert "题面" in prompt
        assert '"nums":[2,7]' in prompt
        assert "json-stdio-v1" in prompt
        assert "隐藏" not in prompt
        assert "完整可执行 Python 程序" in prompt


class TestEvaluationService:
    async def test_evaluates_strict_agent_output_and_keeps_hidden_expected_out_of_prompt(
        self, session: AsyncSession
    ) -> None:
        from app.judges.base import JudgeCases

        secret_expected = {"indices": [91, 92]}
        cases = JudgeCases.model_validate(
            {
                "problem_slug": "two-sum",
                "version": "v1",
                "protocol_version": "json-stdio-v1",
                "public_cases": [
                    {
                        "input": {"nums": [2, 7], "target": 9},
                        "expected": {"indices": [0, 1]},
                    }
                ],
                "hidden_cases": [
                    {
                        "input": {"nums": [4, 5], "target": 9},
                        "expected": secret_expected,
                        "note": "hidden",
                    }
                ],
            }
        )
        agent = RecordingAgent(evaluation_response())
        evaluator = RecordingEvaluator(judge_result())

        result = await service(session, agent, RecordingCatalog(cases), evaluator).evaluate(
            1, SESSION_HASH
        )

        assert result.problem_id == judge_result().problem_id
        assert result.status == EvaluationStatus.AC
        assert result.run_status == "SUCCEEDED"
        assert result.duration_ms >= 0
        assert len(agent.prompts) == 1
        assert "91" not in agent.prompts[0]
        assert "92" not in agent.prompts[0]
        assert "hidden" not in agent.prompts[0]
        assert evaluator.calls[0]["code"] == CORRECT_TWO_SUM_CODE
        saved = (await session.scalars(select(EvaluationRun))).one()
        assert saved.id == result.evaluation_id
        assert saved.run_status == EvaluationRunStatus.SUCCEEDED.value
        assert saved.judge_status == EvaluationStatus.AC.value
        assert CORRECT_TWO_SUM_CODE not in (saved.summary or "")
        assert "91" not in (saved.summary or "")

    @pytest.mark.parametrize(
        "agent_response",
        [
            "not json",
            '{"language":"python","code":"print(1)"}',
            '{"language":"python","code":"","explanation":""}',
            '{"language":"javascript","code":"print(1)","explanation":""}',
            '{"language":"python","code":"print(1)","explanation":"","extra":true}',
        ],
    )
    async def test_rejects_invalid_structured_agent_output(
        self, session: AsyncSession, agent_response: str
    ) -> None:
        from app.judges.base import JudgeCases

        cases = JudgeCases.model_validate(
            {
                "problem_slug": "two-sum",
                "version": "v1",
                "protocol_version": "json-stdio-v1",
                "public_cases": [
                    {"input": {"nums": [2, 7], "target": 9}, "expected": {"indices": [0, 1]}}
                ],
                "hidden_cases": [],
            }
        )
        evaluator = RecordingEvaluator(judge_result())

        with pytest.raises(AgentEvaluationError):
            await service(
                session,
                RecordingAgent(agent_response),
                RecordingCatalog(cases),
                evaluator,
            ).evaluate(1, SESSION_HASH)

        assert evaluator.calls == []
        saved = (await session.scalars(select(EvaluationRun))).one()
        assert saved.run_status == EvaluationRunStatus.FAILED.value
        assert saved.error_category == EvaluationErrorCategory.AGENT_ERROR.value
        assert saved.summary == "Agent 未能生成可执行候选程序"

    async def test_maps_catalog_and_controller_failures_without_turning_them_into_candidate_errors(
        self, session: AsyncSession
    ) -> None:
        agent = RecordingAgent(evaluation_response())
        catalog = RecordingCatalog(CaseNotFoundError("not configured"))

        with pytest.raises(CaseNotFoundError):
            await service(session, agent, catalog, RecordingEvaluator(judge_result())).evaluate(
                1, SESSION_HASH
            )
        assert await session.scalar(select(func.count()).select_from(EvaluationRun)) == 0

        for error, expected_status, expected_category in (
            (ControllerBusyError(), EvaluationRunStatus.REJECTED, EvaluationErrorCategory.CONTROLLER_BUSY),
            (
                ControllerUnavailableError(),
                EvaluationRunStatus.FAILED,
                EvaluationErrorCategory.CONTROLLER_UNAVAILABLE,
            ),
            (
                ControllerTimeoutError(),
                EvaluationRunStatus.TIMED_OUT,
                EvaluationErrorCategory.CONTROLLER_TIMEOUT,
            ),
            (
                ControllerResponseError(),
                EvaluationRunStatus.FAILED,
                EvaluationErrorCategory.CONTROLLER_RESPONSE_ERROR,
            ),
        ):
            from app.judges.base import JudgeCases

            cases = JudgeCases.model_validate(
                {
                    "problem_slug": "two-sum",
                    "version": "v1",
                    "protocol_version": "json-stdio-v1",
                    "public_cases": [
                        {"input": {"nums": [2, 7], "target": 9}, "expected": {"indices": [0, 1]}}
                    ],
                    "hidden_cases": [],
                }
            )
            with pytest.raises(type(error)):
                await service(
                    session,
                    RecordingAgent(evaluation_response()),
                    RecordingCatalog(cases),
                    RecordingEvaluator(error),
                ).evaluate(1, SESSION_HASH)
            saved = (
                await session.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()))
            ).first()
            assert saved is not None
            assert saved.run_status == expected_status.value
            assert saved.error_category == expected_category.value
            assert "secret" not in (saved.summary or "")

    async def test_rejects_when_disabled_and_when_total_deadline_expires(self, session: AsyncSession) -> None:
        disabled = EvaluationService(
            session=session,
            agent=RecordingAgent(evaluation_response()),
            settings=Settings(_env_file=None, evaluation_enabled=False),
        )
        with pytest.raises(EvaluationDisabledError):
            await disabled.evaluate(1, SESSION_HASH)
        assert await session.scalar(select(func.count()).select_from(EvaluationRun)) == 0

        enabled = service(
            session,
            RecordingAgent(evaluation_response()),
            RecordingCatalog(CaseNotFoundError("missing hidden case")),
            RecordingEvaluator(judge_result()),
        )
        with pytest.raises(LookupError):
            await enabled.evaluate(999, SESSION_HASH)
        assert await session.scalar(select(func.count()).select_from(EvaluationRun)) == 0

        from app.judges.base import JudgeCases

        cases = JudgeCases.model_validate(
            {
                "problem_slug": "two-sum",
                "version": "v1",
                "protocol_version": "json-stdio-v1",
                "public_cases": [
                    {"input": {"nums": [2, 7], "target": 9}, "expected": {"indices": [0, 1]}}
                ],
                "hidden_cases": [],
            }
        )

        class SlowAgent(RecordingAgent):
            async def generate(self, prompt: str) -> str:
                await asyncio.sleep(0.01)
                return await super().generate(prompt)

        with pytest.raises(EvaluationTimeoutError):
            await service(
                session,
                SlowAgent(evaluation_response()),
                RecordingCatalog(cases),
                RecordingEvaluator(judge_result()),
                evaluation_total_timeout_seconds=0.001,
            ).evaluate(1, SESSION_HASH)
        timed_out = (await session.scalars(select(EvaluationRun))).one()
        assert timed_out.run_status == EvaluationRunStatus.TIMED_OUT.value
        assert timed_out.error_category == EvaluationErrorCategory.EVALUATION_TIMEOUT.value


@pytest.fixture
def api_client(tmp_path) -> AsyncGenerator[TestClient, None]:
    database_path = tmp_path / "evaluations_api.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def setup_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as database_session:
            database_session.add(
                Problem(slug="two-sum", title="Two Sum", description="Two Sum description")
            )
            await database_session.commit()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as database_session:
            yield database_session

    import asyncio as asyncio_module

    asyncio_module.run(setup_database())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, evaluation_enabled=True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        asyncio_module.run(engine.dispose())


def use_evaluation_service(factory: Callable[[], EvaluationService]) -> None:
    app.dependency_overrides[get_evaluation_service] = factory


class TestEvaluationsApi:
    def test_rejects_invalid_request_fields(self, api_client: TestClient) -> None:
        assert api_client.post("/api/evaluations", json={"problem_id": 0}).status_code == 422
        assert api_client.post("/api/evaluations", json={"problem_id": 1, "code": "client code"}).status_code == 422

    @pytest.mark.parametrize(
        ("error", "expected_status", "expected_detail"),
        [
            (LookupError(), 404, "Problem not found"),
            (CaseNotFoundError(), 422, "Evaluation cases are not configured"),
            (AgentEvaluationError(), 502, "Agent failed to generate an executable solution"),
            (ControllerBusyError(), 409, "Evaluation service is busy"),
            (ControllerUnavailableError(), 503, "Evaluation controller is unavailable"),
            (ControllerTimeoutError(), 503, "Evaluation controller is unavailable"),
            (ControllerResponseError(), 503, "Evaluation controller is unavailable"),
            (EvaluationDisabledError(), 503, "Evaluation is disabled"),
            (EvaluationTimeoutError(), 504, "Evaluation request timed out"),
        ],
    )
    def test_maps_failures_to_sanitized_api_responses(
        self,
        api_client: TestClient,
        error: Exception,
        expected_status: int,
        expected_detail: str,
    ) -> None:
        class FailingService:
            async def evaluate(self, problem_id: int, session_key_hash: str) -> EvaluationCreateResponse:
                assert len(session_key_hash) == 64
                raise error

        use_evaluation_service(lambda: FailingService())
        response = api_client.post("/api/evaluations", json={"problem_id": 1})

        assert response.status_code == expected_status
        assert response.json() == {"detail": expected_detail}
        assert "secret" not in response.text

    def test_returns_only_evaluation_summary(self, api_client: TestClient) -> None:
        class SuccessfulService:
            async def evaluate(
                self, problem_id: int, session_key_hash: str
            ) -> EvaluationCreateResponse:
                assert len(session_key_hash) == 64
                now = datetime(2026, 9, 19, 4, 30, tzinfo=timezone.utc)
                summary_result = judge_result(EvaluationStatus.WA).model_copy(
                    update={
                        "executed_count": 2,
                        "passed_count": 1,
                        "failed_case_index": 1,
                        "summary": "第 2 个用例答案错误",
                    }
                )
                return EvaluationCreateResponse(
                    **summary_result.model_dump(),
                    evaluation_id=UUID("11111111-1111-4111-8111-111111111111"),
                    run_status="SUCCEEDED",
                    created_at=now,
                    finished_at=now,
                    duration_ms=12,
                )

        use_evaluation_service(lambda: SuccessfulService())
        response = api_client.post("/api/evaluations", json={"problem_id": 1})

        assert response.status_code == 200
        assert response.json() == {
            "problem_id": 1,
            "problem_slug": "two-sum",
            "language": "python",
            "status": "WA",
            "case_version": "v1",
            "case_count": 9,
            "executed_count": 2,
            "passed_count": 1,
            "failed_case_index": 1,
            "summary": "第 2 个用例答案错误",
            "evaluation_id": "11111111-1111-4111-8111-111111111111",
            "run_status": "SUCCEEDED",
            "created_at": "2026-09-19T04:30:00Z",
            "finished_at": "2026-09-19T04:30:00Z",
            "duration_ms": 12,
        }
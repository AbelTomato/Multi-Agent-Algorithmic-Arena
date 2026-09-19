"""Agent 生成候选程序并交由可信 Judge 评测的业务编排。"""

import asyncio
import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.config import Settings
from app.judges.base import JudgeCases, JudgeResult
from app.judges.catalog import CaseCatalog
from app.judges.client import (
    ControllerBusyError,
    ControllerResponseError,
    ControllerTimeoutError,
    ControllerUnavailableError,
    SandboxClient,
)
from app.judges.evaluator import Evaluator
from app.models.evaluation_run import EvaluationErrorCategory, EvaluationRunStatus
from app.models.problem import Problem
from app.schemas.evaluation import (
    AgentEvaluationOutput,
    EvaluationCreateResponse,
    MAX_AGENT_RESPONSE_BYTES,
)
from app.services.evaluation_runs import EvaluationRunRepository


EVALUATION_SYSTEM_PROMPT = """你是一名算法题候选程序生成 Agent。

只针对给定题目生成完整、可执行的 Python 3.11 程序。程序从标准输入读取一个 JSON 对象，并只向标准输出写入一个 JSON 对象后退出。
必须使用 json-stdio-v1 协议。不要输出 Markdown、代码围栏、额外说明或任何非 JSON 字符。
你的整个回复必须是且只能是以下 JSON 对象：
{"language":"python","code":"完整可执行 Python 程序","explanation":"简短说明"}
language 必须为 python；禁止额外字段。"""


class EvaluationDisabledError(Exception):
    """本地评测功能未显式启用。"""


class AgentEvaluationError(Exception):
    """Agent 调用失败或未返回有效的结构化候选程序。"""


class EvaluationTimeoutError(Exception):
    """整个评测编排超过总期限。"""


class EvaluationPersistenceError(Exception):
    """运行记录未能可靠写入。"""


def build_evaluation_prompt(problem: Problem, public_cases: list[dict[str, Any]]) -> str:
    """只向 Agent 暴露题面、公开样例和固定输出协议。"""

    serialized_public_cases = json.dumps(public_cases, ensure_ascii=False, separators=(",", ":"))
    return f"""{EVALUATION_SYSTEM_PROMPT}

## 题目标题
{problem.title}

## 题目描述
{problem.description}

## 公开样例
{serialized_public_cases}

## 候选程序协议
每次执行只会收到一个 JSON 输入对象。候选程序必须输出一个 JSON 对象，且不得打印调试信息。
"""


class EvaluationService:
    """编排题目读取、受控 Agent 生成、Judge 用例加载和真实执行。"""

    def __init__(
        self,
        session: AsyncSession,
        agent: Agent,
        settings: Settings,
        case_catalog: CaseCatalog | None = None,
        evaluator_factory: Callable[[], Evaluator] | None = None,
    ) -> None:
        self.session = session
        self.agent = agent
        self.settings = settings
        self.case_catalog = case_catalog or CaseCatalog()
        self.evaluator_factory = evaluator_factory or self._create_evaluator
        self.runs = EvaluationRunRepository(session)

    def _create_evaluator(self) -> Evaluator:
        return Evaluator(
            SandboxClient(
                base_url=self.settings.sandbox_controller_url,
                timeout=self.settings.sandbox_controller_timeout_seconds,
            )
        )

    async def evaluate(self, problem_id: int, session_key_hash: str) -> EvaluationCreateResponse:
        if not self.settings.evaluation_enabled:
            raise EvaluationDisabledError

        problem = await self.session.get(Problem, problem_id)
        if problem is None:
            raise LookupError("Problem not found")
        loaded_problem = Problem(
            id=problem.id,
            slug=problem.slug,
            title=problem.title,
            description=problem.description,
        )
        await self.session.rollback()
        cases = self.case_catalog.load(loaded_problem.slug)
        run = await self.runs.create_running(
            session_key_hash,
            loaded_problem,
            cases.version,
            len(cases.all_cases),
        )
        monotonic_started = time.monotonic()
        try:
            async with asyncio.timeout(self.settings.evaluation_total_timeout_seconds):
                result = await self._execute(loaded_problem, cases)
        except TimeoutError as error:
            await self._persist_failure(
                run.id,
                EvaluationRunStatus.TIMED_OUT,
                EvaluationErrorCategory.EVALUATION_TIMEOUT,
                monotonic_started,
            )
            raise EvaluationTimeoutError from error
        except AgentEvaluationError:
            await self._persist_failure(
                run.id, EvaluationRunStatus.FAILED, EvaluationErrorCategory.AGENT_ERROR, monotonic_started
            )
            raise
        except ControllerBusyError:
            await self._persist_failure(
                run.id,
                EvaluationRunStatus.REJECTED,
                EvaluationErrorCategory.CONTROLLER_BUSY,
                monotonic_started,
            )
            raise
        except ControllerTimeoutError:
            await self._persist_failure(
                run.id,
                EvaluationRunStatus.TIMED_OUT,
                EvaluationErrorCategory.CONTROLLER_TIMEOUT,
                monotonic_started,
            )
            raise
        except ControllerUnavailableError:
            await self._persist_failure(
                run.id,
                EvaluationRunStatus.FAILED,
                EvaluationErrorCategory.CONTROLLER_UNAVAILABLE,
                monotonic_started,
            )
            raise
        except ControllerResponseError:
            await self._persist_failure(
                run.id,
                EvaluationRunStatus.FAILED,
                EvaluationErrorCategory.CONTROLLER_RESPONSE_ERROR,
                monotonic_started,
            )
            raise
        except Exception:
            await self._persist_failure(
                run.id,
                EvaluationRunStatus.FAILED,
                EvaluationErrorCategory.INTERNAL_ERROR,
                monotonic_started,
            )
            raise

        finished_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((time.monotonic() - monotonic_started) * 1000))
        try:
            changed = await self.runs.mark_succeeded(run.id, result, finished_at, duration_ms)
            if not changed:
                raise EvaluationPersistenceError("evaluation run is no longer running")
            await self.session.commit()
        except Exception as error:
            await self.session.rollback()
            if isinstance(error, EvaluationPersistenceError):
                raise
            raise EvaluationPersistenceError("failed to persist evaluation result") from error
        return EvaluationCreateResponse(
            **result.model_dump(),
            evaluation_id=run.id,
            run_status="SUCCEEDED",
            created_at=run.created_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def _execute(self, loaded_problem: Problem, cases: JudgeCases) -> JudgeResult:
        prompt = build_evaluation_prompt(
            loaded_problem,
            [case.model_dump(mode="json") for case in cases.public_cases],
        )
        output = await self._generate_candidate(prompt)
        evaluator = self.evaluator_factory()
        try:
            return await evaluator.evaluate(
                loaded_problem.id,
                loaded_problem.slug,
                output.code,
                cases,
            )
        finally:
            client = getattr(evaluator, "client", None)
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()

    async def _persist_failure(
        self,
        run_id,
        run_status: EvaluationRunStatus,
        category: EvaluationErrorCategory,
        monotonic_started: float,
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((time.monotonic() - monotonic_started) * 1000))
        try:
            changed = await self.runs.mark_failed(
                run_id,
                run_status,
                category,
                "",
                finished_at,
                duration_ms,
            )
            if not changed:
                raise EvaluationPersistenceError("evaluation run is no longer running")
            await self.session.commit()
        except Exception as error:
            await self.session.rollback()
            if isinstance(error, EvaluationPersistenceError):
                raise
            raise EvaluationPersistenceError("failed to persist evaluation failure") from error

    async def _generate_candidate(self, prompt: str) -> AgentEvaluationOutput:
        last_error: Exception | None = None
        for _ in range(1 + self.settings.agent_retry_count):
            try:
                response = await self.agent.generate(prompt)
                if len(response.encode("utf-8")) > MAX_AGENT_RESPONSE_BYTES:
                    raise AgentEvaluationError("Agent response exceeds byte limit")
                payload = json.loads(response)
                return AgentEvaluationOutput.model_validate(payload)
            except AgentEvaluationError:
                raise
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
                raise AgentEvaluationError("Agent response is not valid evaluation JSON") from error
            except Exception as error:  # noqa: BLE001 - sanitize provider failures at the boundary
                last_error = error

        raise AgentEvaluationError("Agent generation failed") from last_error
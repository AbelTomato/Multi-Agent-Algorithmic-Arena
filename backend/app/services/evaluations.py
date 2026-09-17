"""Agent 生成候选程序并交由可信 Judge 评测的业务编排。"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.config import Settings
from app.judges.base import JudgeCases, JudgeResult
from app.judges.catalog import CaseCatalog
from app.judges.client import SandboxClient
from app.judges.evaluator import Evaluator
from app.models.problem import Problem
from app.schemas.evaluation import AgentEvaluationOutput, MAX_AGENT_RESPONSE_BYTES


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

    def _create_evaluator(self) -> Evaluator:
        return Evaluator(
            SandboxClient(
                base_url=self.settings.sandbox_controller_url,
                timeout=self.settings.sandbox_controller_timeout_seconds,
            )
        )

    async def evaluate(self, problem_id: int) -> JudgeResult:
        if not self.settings.evaluation_enabled:
            raise EvaluationDisabledError

        try:
            async with asyncio.timeout(self.settings.evaluation_total_timeout_seconds):
                return await self._evaluate(problem_id)
        except TimeoutError as error:
            raise EvaluationTimeoutError from error

    async def _evaluate(self, problem_id: int) -> JudgeResult:
        problem = await self.session.get(Problem, problem_id)
        if problem is None:
            raise LookupError("Problem not found")

        # 题目实体已读取到内存，释放数据库事务，避免 Agent 与逐用例执行期间占用连接。
        loaded_problem = Problem(
            id=problem.id,
            slug=problem.slug,
            title=problem.title,
            description=problem.description,
        )
        await self.session.rollback()
        cases = self.case_catalog.load(loaded_problem.slug)
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
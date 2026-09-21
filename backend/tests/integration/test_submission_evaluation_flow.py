from collections.abc import AsyncGenerator
import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, SubjectType
from app.config import Settings
from app.database import Base
from app.judges.base import EvaluationStatus, JudgeResult
from app.judges.client import CPP_RUNTIME_V1, PYTHON_RUNTIME_V1
from app.models.permission import ProblemSubmissionPermission
from app.models.problem import Problem
from app.services.candidate_generation import CandidateGeneration
from app.services.submission_evaluations import SubmissionEvaluationService
from app.services.submissions import SubmissionService


controller_required = pytest.mark.skipif(
    os.getenv("ARENA_SANDBOX_INTEGRATION") != "1",
    reason="需要设置 ARENA_SANDBOX_INTEGRATION=1 并启动 Go 执行控制器",
)


PYTHON_TWO_SUM_CORRECT = """import json
import sys

data = json.loads(sys.stdin.read())
seen = {}
for index, number in enumerate(data["nums"]):
    complement = data["target"] - number
    if complement in seen:
        print(json.dumps({"indices": [seen[complement], index]}))
        break
    seen[number] = index
"""


PYTHON_TWO_SUM_WRONG = """import json
print(json.dumps({"indices": [0, 1]}))
"""


CPP_TWO_SUM_CORRECT = r"""#include <cctype>
#include <iostream>
#include <iterator>
#include <string>
#include <unordered_map>
#include <vector>

int main() {
    const std::string input(
        (std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
    std::vector<int> values;
    for (std::size_t index = 0; index < input.size();) {
        if (input[index] != '-' && !std::isdigit(static_cast<unsigned char>(input[index]))) {
            ++index;
            continue;
        }
        int sign = 1;
        if (input[index] == '-') {
            sign = -1;
            ++index;
        }
        int value = 0;
        while (index < input.size() && std::isdigit(static_cast<unsigned char>(input[index]))) {
            value = value * 10 + (input[index] - '0');
            ++index;
        }
        values.push_back(sign * value);
    }
    if (values.size() < 3) {
        return 1;
    }

    const int target = values.back();
    values.pop_back();
    std::unordered_map<int, int> seen;
    for (int index = 0; index < static_cast<int>(values.size()); ++index) {
        const int complement = target - values[index];
        const auto match = seen.find(complement);
        if (match != seen.end()) {
            std::cout << "{\"indices\":[" << match->second << "," << index << "]}";
            return 0;
        }
        seen[values[index]] = index;
    }
    return 1;
}
"""


CPP_TWO_SUM_WRONG = r"""#include <iostream>

int main() {
    std::cout << "{\"indices\":[0,1]}";
    return 0;
}
"""


class IntegrationCatalog:
    def __init__(self, cases: object) -> None:
        self.cases = cases
        self.calls: list[tuple[str, str]] = []

    def load(self, problem_slug: str, version: str):
        self.calls.append((problem_slug, version))
        return self.cases


class IntegrationEvaluator:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str, object]] = []

    async def evaluate(self, problem_id: int, problem_slug: str, source: str, cases) -> JudgeResult:
        self.calls.append((problem_id, problem_slug, source, cases))
        return JudgeResult(
            problem_id=problem_id,
            problem_slug=problem_slug,
            language="python",
            status=EvaluationStatus.AC,
            case_version="v1",
            case_count=1,
            executed_count=1,
            passed_count=1,
            failed_case_index=None,
            summary="passed",
        )


@pytest.fixture
async def integration_database(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'submission-flow.db'}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_candidate_generation_submission_and_pure_evaluation_flow(integration_database) -> None:
    async with integration_database() as session:
        subject = Account(subject_type=SubjectType.AGENT, name="generated-agent")
        problem = Problem(
            slug="two-sum",
            title="Two Sum",
            description="description",
            allowed_languages=["python"],
            active_case_version="v1",
        )
        session.add_all([subject, problem])
        await session.flush()
        session.add(ProblemSubmissionPermission(account_id=subject.id, problem_id=problem.id))
        await session.commit()

        candidate = CandidateGeneration.from_payload(
            {"language": "python", "source": "print(1)"}
        )
        submission = await SubmissionService(session).create(
            subject,
            problem_id=problem.id,
            language=candidate.language,
            source=candidate.source,
        )
        await session.commit()

        evaluator = IntegrationEvaluator()
        catalog = IntegrationCatalog(cases=object())
        saved = await SubmissionEvaluationService(
            session,
            case_catalog=catalog,
            evaluator_factory=lambda runtime_id: evaluator,
        ).evaluate(subject, submission.id)
        await session.commit()

        assert catalog.calls == [("two-sum", "v1")]
        assert evaluator.calls == [(problem.id, "two-sum", "print(1)", catalog.cases)]
        assert saved.submission_id == submission.id
        assert saved.judge_status == "AC"
        assert saved.source_sha256 == submission.source_sha256


@controller_required
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("python_source", "cpp_source", "expected_status"),
    [
        (PYTHON_TWO_SUM_CORRECT, CPP_TWO_SUM_CORRECT, EvaluationStatus.AC),
        (PYTHON_TWO_SUM_WRONG, CPP_TWO_SUM_WRONG, EvaluationStatus.WA),
    ],
    ids=["equivalent-ac", "equivalent-wa"],
)
async def test_python_and_cpp_submissions_share_real_checker_semantics(
    integration_database,
    python_source: str,
    cpp_source: str,
    expected_status: EvaluationStatus,
) -> None:
    async with integration_database() as session:
        subject = Account(subject_type=SubjectType.AGENT, name="multi-language-agent")
        problem = Problem(
            slug="two-sum",
            title="Two Sum",
            description="description",
            allowed_languages=["python", "cpp"],
            active_case_version="v1",
        )
        session.add_all([subject, problem])
        await session.flush()
        session.add(ProblemSubmissionPermission(account_id=subject.id, problem_id=problem.id))
        await session.commit()

        submissions = []
        for language, source in (("python", python_source), ("cpp", cpp_source)):
            candidate = CandidateGeneration.from_payload({"language": language, "source": source})
            submissions.append(
                await SubmissionService(session).create(
                    subject,
                    problem_id=problem.id,
                    language=candidate.language,
                    source=candidate.source,
                )
            )
        await session.commit()

        evaluations = []
        for submission in submissions:
            evaluation = await SubmissionEvaluationService(
                session,
                settings=Settings(
                    _env_file=None,
                    sandbox_controller_url="http://127.0.0.1:8001",
                    sandbox_controller_timeout_seconds=10,
                ),
            ).evaluate(subject, submission.id)
            await session.commit()
            evaluations.append(evaluation)

        assert [submission.runtime_id for submission in submissions] == [
            PYTHON_RUNTIME_V1,
            CPP_RUNTIME_V1,
        ]
        assert [evaluation.judge_status for evaluation in evaluations] == [
            expected_status.value,
            expected_status.value,
        ]
        assert evaluations[0].case_version == evaluations[1].case_version == "v1"
        assert evaluations[0].case_count == evaluations[1].case_count == 9
        assert evaluations[0].executed_count == evaluations[1].executed_count
        assert evaluations[0].failed_case_index == evaluations[1].failed_case_index
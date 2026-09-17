"""阶段 2 Judge 契约、语义与执行错误映射测试。"""

import json

import httpx
import pytest
from pydantic import ValidationError

from app.judges.base import EvaluationStatus, JudgeCases, TestCase
from app.judges.catalog import CaseCatalog
from app.judges.client import (
    ControllerBusyError,
    ControllerResponseError,
    ControllerTimeoutError,
    ControllerUnavailableError,
    SandboxClient,
    ExecutionResult,
)
from app.judges.evaluator import Evaluator


def case_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "problem_slug": "two-sum",
        "version": "v1",
        "protocol_version": "json-stdio-v1",
        "public_cases": [
            {"input": {"nums": [2, 7], "target": 9}, "expected": {"indices": [0, 1]}}
        ],
        "hidden_cases": [],
    }
    document.update(overrides)
    return document


class TestJudgeCases:
    def test_rejects_unknown_case_document_fields(self) -> None:
        with pytest.raises(ValidationError):
            JudgeCases.model_validate(case_document(unexpected=True))

    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            ({"protocol_version": "wrong"}, "protocol_version"),
            ({"public_cases": [], "hidden_cases": []}, "至少包含一个"),
            ({"public_cases": [case_document()["public_cases"][0]] * 33}, "最多包含 32"),
        ],
    )
    def test_rejects_invalid_case_collection(self, overrides: dict[str, object], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            JudgeCases.model_validate(case_document(**overrides))

    def test_rejects_case_input_larger_than_utf8_limit(self) -> None:
        oversized_input = {"s": "你" * (64 * 1024)}
        with pytest.raises(ValidationError, match="64 KiB"):
            JudgeCases.model_validate(
                case_document(
                    public_cases=[{"input": oversized_input, "expected": {"indices": [0, 1]}}]
                )
            )

    def test_catalog_rejects_damaged_json_and_slug_version_mismatch(self, tmp_path) -> None:
        case_dir = tmp_path / "two-sum"
        case_dir.mkdir()
        case_file = case_dir / "v1.json"
        catalog = CaseCatalog(base_dir=tmp_path)

        case_file.write_text("{", encoding="utf-8")
        with pytest.raises(ValueError, match="JSON 损坏"):
            catalog.load("two-sum")

        case_file.write_text(json.dumps(case_document(problem_slug="another-problem")), encoding="utf-8")
        with pytest.raises(ValueError, match="slug 不匹配"):
            catalog.load("two-sum")

        case_file.write_text(json.dumps(case_document(version="v2")), encoding="utf-8")
        with pytest.raises(ValueError, match="版本不匹配"):
            catalog.load("two-sum")


class TestEvaluatorJudgment:
    def setup_method(self) -> None:
        self.evaluator = Evaluator(object())

    def test_two_sum_accepts_any_semantically_valid_pair_not_fixed_expected_indices(self) -> None:
        case_input = {"nums": [3, 3, 3, 3], "target": 6}

        assert self.evaluator._judge_output(
            problem_slug="two-sum",
            stdout='{"indices": [2, 3]}',
            expected={"indices": [0, 1]},
            case_input=case_input,
        ) == EvaluationStatus.AC

    @pytest.mark.parametrize(
        ("stdout", "status"),
        [
            ('{"indices": [0, 0]}', EvaluationStatus.WA),
            ('{"indices": [0, 3]}', EvaluationStatus.WA),
            ('{"indices": [0, true]}', EvaluationStatus.RE),
            ('{"indices": [0]}', EvaluationStatus.RE),
            ('{"indices": [0, 1], "extra": 1}', EvaluationStatus.RE),
        ],
    )
    def test_two_sum_enforces_strict_output_shape_and_input_semantics(
        self, stdout: str, status: EvaluationStatus
    ) -> None:
        assert self.evaluator._judge_output(
            problem_slug="two-sum",
            stdout=stdout,
            expected={"indices": [0, 1]},
            case_input={"nums": [2, 7, 11], "target": 9},
        ) == status

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("execution", "expected_status"),
        [
            ({"exit_reason": "non_zero_exit", "exit_code": 1}, EvaluationStatus.RE),
            ({"exit_reason": "timeout", "exit_code": None}, EvaluationStatus.TLE),
            ({"exit_reason": "output_limit_exceeded", "exit_code": None}, EvaluationStatus.OLE),
            ({"exit_reason": "memory_limit_exceeded", "exit_code": 137, "oom_killed": True}, EvaluationStatus.MLE),
            ({"exit_reason": "docker_error", "exit_code": None}, EvaluationStatus.UKE),
            ({"exit_reason": "unknown_error", "exit_code": None}, EvaluationStatus.UKE),
            ({"exit_reason": "memory_limit_exceeded", "exit_code": 137, "oom_killed": False}, EvaluationStatus.UKE),
        ],
    )
    async def test_evaluator_preserves_execution_failure_classification(
        self, execution: dict[str, object], expected_status: EvaluationStatus
    ) -> None:
        class StubClient:
            async def execute(self, *, code: str, stdin_input: str):
                return expected_status, {"stdout": "", **execution}

        cases = JudgeCases.model_validate(case_document())
        result = await Evaluator(StubClient()).evaluate(1, "two-sum", "code", cases)

        assert result.status == expected_status
        assert result.executed_count == 1
        assert result.passed_count == 0
        assert result.failed_case_index == 0

    @pytest.mark.asyncio
    async def test_programmatic_empty_cases_cannot_be_accepted(self) -> None:
        empty_cases = JudgeCases.model_construct(
            problem_slug="two-sum",
            version="v1",
            protocol_version="json-stdio-v1",
            public_cases=[],
            hidden_cases=[],
        )

        result = await Evaluator(object()).evaluate(1, "two-sum", "code", empty_cases)

        assert result.status == EvaluationStatus.UKE
        assert result.executed_count == 0
        assert result.passed_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [ControllerBusyError("busy"), ControllerUnavailableError("unavailable")],
    )
    async def test_evaluator_preserves_controller_error_for_api_mapping(
        self, error: Exception
    ) -> None:
        class FailingClient:
            async def execute(self, *, code: str, stdin_input: str):
                raise error

        with pytest.raises(type(error)):
            await Evaluator(FailingClient()).evaluate(
                1, "two-sum", "code", JudgeCases.model_validate(case_document())
            )

    @pytest.mark.asyncio
    async def test_hidden_expected_value_is_not_sent_to_execution_controller(self) -> None:
        secret_expected = {"result": False}
        cases = JudgeCases.model_validate(
            {
                "problem_slug": "valid-parentheses",
                "version": "v1",
                "protocol_version": "json-stdio-v1",
                "public_cases": [],
                "hidden_cases": [
                    {"input": {"s": "("}, "expected": secret_expected, "note": "hidden"}
                ],
            }
        )

        class RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, str]] = []

            async def execute(self, *, code: str, stdin_input: str):
                self.calls.append({"code": code, "stdin_input": stdin_input})
                return EvaluationStatus.AC, ExecutionResult(
                    exit_reason="completed",
                    exit_code=0,
                    stdout='{"result": false}',
                    stderr="",
                    wall_time_ms=1,
                    oom_killed=False,
                )

        client = RecordingClient()
        result = await Evaluator(client).evaluate(1, "valid-parentheses", "candidate", cases)

        assert result.status == EvaluationStatus.AC
        assert client.calls == [{"code": "candidate", "stdin_input": '{"s":"("}'}]
        assert json.dumps(secret_expected) not in json.dumps(client.calls)


class TestSandboxClient:
    @pytest.mark.asyncio
    async def test_sends_only_frozen_execution_request_without_expected_or_task_id(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={
                    "exit_reason": "completed",
                    "exit_code": 0,
                    "stdout": "{}",
                    "stderr": "",
                    "wall_time_ms": 1,
                    "oom_killed": False,
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            client = SandboxClient(client=transport)
            status, _ = await client.execute(code="print(1)", stdin_input='{"s":"("}')

        assert status == EvaluationStatus.AC
        assert captured[0].url.path == "/execute"
        assert json.loads(captured[0].content) == {
            "code": "print(1)",
            "stdin_input": '{"s":"("}',
            "protocol_version": "json-stdio-v1",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "exception_type"),
        [(409, ControllerBusyError), (500, ControllerUnavailableError), (503, ControllerUnavailableError)],
    )
    async def test_preserves_controller_http_failures(
        self, status_code: int, exception_type: type[Exception]
    ) -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status_code, json={"detail": "internal"})
            )
        ) as transport:
            client = SandboxClient(client=transport)
            with pytest.raises(exception_type):
                await client.execute(code="print(1)", stdin_input="{}")

    @pytest.mark.asyncio
    async def test_preserves_timeout_and_malformed_response_failures(self) -> None:
        def timeout_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler)) as transport:
            with pytest.raises(ControllerTimeoutError):
                await SandboxClient(client=transport).execute(code="print(1)", stdin_input="{}")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"exit_reason": "completed"})
            )
        ) as transport:
            with pytest.raises(ControllerResponseError):
                await SandboxClient(client=transport).execute(code="print(1)", stdin_input="{}")
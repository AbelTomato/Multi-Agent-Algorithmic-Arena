import json

import httpx
import pytest

from app.agents.factory import get_agent
from app.agents.provider import ProviderAgent
from app.config import Settings
from app.providers.openai_compatible import OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_openai_compatible_provider_posts_chat_completion_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "## 解题思路\nanswer"}}]},
        )

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://llm.example.test/v1/",
        model="test-model",
        timeout_seconds=7.5,
        max_tokens=512,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.complete("solve this problem")

    assert result == "## 解题思路\nanswer"
    assert captured == {
        "url": "https://llm.example.test/v1/chat/completions",
        "authorization": "Bearer test-key",
        "body": {
            "model": "test-model",
            "messages": [{"role": "user", "content": "solve this problem"}],
            "max_tokens": 512,
        },
    }


@pytest.mark.asyncio
async def test_openai_compatible_provider_disables_environment_proxies(monkeypatch) -> None:
    captured: dict[str, object] = {}
    original_async_client = httpx.AsyncClient

    def recording_async_client(*args, **kwargs):
        captured["trust_env"] = kwargs["trust_env"]
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", recording_async_client)

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        model="test-model",
        timeout_seconds=7.5,
        max_tokens=512,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "answer"}}]},
            )
        ),
    )

    assert await provider.complete("solve this problem") == "answer"
    assert captured == {"trust_env": False}


@pytest.mark.asyncio
async def test_openai_compatible_provider_hides_upstream_error_details() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="upstream secret response")

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        model="test-model",
        timeout_seconds=7.5,
        max_tokens=512,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="status 429") as error:
        await provider.complete("solve this problem")

    assert "upstream secret response" not in str(error.value)
    assert "test-key" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 500])
async def test_openai_compatible_provider_hides_error_details_for_upstream_failures(
    status_code: int,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="upstream secret response")

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        model="test-model",
        timeout_seconds=7.5,
        max_tokens=512,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match=f"status {status_code}") as error:
        await provider.complete("solve this problem")

    assert "upstream secret response" not in str(error.value)
    assert "test-key" not in str(error.value)


@pytest.mark.asyncio
async def test_openai_compatible_provider_hides_transport_error_details() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream timeout with secret details")

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        model="test-model",
        timeout_seconds=7.5,
        max_tokens=512,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="OpenAI Compatible request failed") as error:
        await provider.complete("solve this problem")

    assert "upstream timeout with secret details" not in str(error.value)
    assert "test-key" not in str(error.value)


@pytest.mark.asyncio
async def test_openai_compatible_provider_rejects_invalid_response_format() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        model="test-model",
        timeout_seconds=7.5,
        max_tokens=512,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="invalid format"):
        await provider.complete("solve this problem")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_error"),
    [
        (httpx.Response(200, text="not-json"), "invalid format"),
        (httpx.Response(200, json=None), "invalid format"),
        (httpx.Response(200, json=[]), "invalid format"),
        (httpx.Response(200, json="not-an-object"), "invalid format"),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
            "empty content",
        ),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}),
            "empty content",
        ),
    ],
)
async def test_openai_compatible_provider_rejects_invalid_or_empty_content(
    response: httpx.Response,
    expected_error: str,
) -> None:
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        model="test-model",
        timeout_seconds=7.5,
        max_tokens=512,
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(RuntimeError, match=expected_error):
        await provider.complete("solve this problem")


def test_factory_builds_openai_compatible_agent_when_configured() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_api_key="test-key",
        llm_base_url="https://llm.example.test/v1",
        llm_model="test-model",
        llm_timeout_seconds=7.5,
        llm_max_tokens=512,
    )

    agent = get_agent(settings)

    assert isinstance(agent, ProviderAgent)
    assert agent.provider.api_key.get_secret_value() == "test-key"
    assert agent.provider.base_url == "https://llm.example.test/v1"


def test_factory_keeps_mock_agent_as_default() -> None:
    settings = Settings(_env_file=None)

    agent = get_agent(settings)

    assert agent.__class__.__name__ == "MockAgent"


def test_factory_requires_api_key_for_openai_compatible_agent() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_api_key=None,
    )

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        get_agent(settings)


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,expected", [
    ({"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}, (12, 7)),
    ({"prompt_tokens": 0, "completion_tokens": 0}, (0, 0)),
    (None, None), ({}, None), ([], None),
    ({"prompt_tokens": -1, "completion_tokens": 7}, None),
    ({"prompt_tokens": True, "completion_tokens": 7}, None),
    ({"prompt_tokens": "12", "completion_tokens": 7}, None),
    ({"prompt_tokens": 12}, None),
])
async def test_metadata_preserves_text_and_validates_usage(usage, expected):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "answer"}}], "usage": usage,
        })

    provider = OpenAICompatibleProvider(
        api_key="test-key", base_url="https://llm.example.test/v1", model="test-model",
        timeout_seconds=1, max_tokens=100, transport=httpx.MockTransport(handler),
    )
    result = await provider.complete_with_metadata("prompt")
    assert result.text == "answer"
    actual = None if result.usage is None else (result.usage.input_tokens, result.usage.output_tokens)
    assert actual == expected
    assert len(requests) == 1
    assert await provider.complete("prompt") == "answer"
    assert len(requests) == 2
    assert "test-key" not in repr(result)


@pytest.mark.asyncio
async def test_meter_counts_failed_calls_and_keeps_unknown_tokens():
    from app.providers.base import CompletionResult, MeteredProvider, TokenUsage

    class FakeProvider:
        async def complete_with_metadata(self, prompt):
            if prompt == "fail":
                raise RuntimeError("private failure")
            return CompletionResult(text="answer", usage=TokenUsage(input_tokens=4, output_tokens=2))

    meter = MeteredProvider(FakeProvider())
    assert (await meter.complete_with_metadata("ok")).text == "answer"
    with pytest.raises(RuntimeError):
        await meter.complete_with_metadata("fail")
    assert meter.calls == 2
    assert meter.usage_calls == 1
    assert meter.input_tokens is None and meter.output_tokens is None
    assert "private failure" not in repr(meter)


@pytest.mark.asyncio
async def test_meter_records_cancellation_without_swallowing_it():
    import asyncio
    from app.providers.base import MeteredProvider

    class CancelledProvider:
        async def complete_with_metadata(self, prompt):
            raise asyncio.CancelledError()

    meter = MeteredProvider(CancelledProvider())
    with pytest.raises(asyncio.CancelledError):
        await meter.complete_with_metadata("prompt")
    assert meter.calls == 1 and meter.usage_calls == 0
    assert meter.input_tokens is None


def test_text_only_provider_remains_compatible():
    from app.providers.base import Provider

    class TextOnly:
        async def complete(self, prompt):
            return "answer"

    assert isinstance(TextOnly(), Provider)


@pytest.mark.asyncio
async def test_meter_accumulates_known_usage_and_isolates_runs():
    from app.providers.base import CompletionResult, MeteredProvider, TokenUsage

    class FakeProvider:
        async def complete_with_metadata(self, prompt):
            usage = None if prompt == "unknown" else TokenUsage(input_tokens=4, output_tokens=2)
            return CompletionResult(text="answer", usage=usage)

    provider = FakeProvider()
    first, second = MeteredProvider(provider), MeteredProvider(provider)
    await first.complete_with_metadata("known")
    await first.complete_with_metadata("known")
    assert (first.calls, first.usage_calls, first.input_tokens, first.output_tokens) == (2, 2, 8, 4)
    assert (second.calls, second.usage_calls) == (0, 0)
    await first.complete_with_metadata("unknown")
    assert (first.calls, first.usage_calls) == (3, 2)
    assert first.input_tokens is first.output_tokens is None


def test_metadata_models_reject_extra_fields_and_hide_text_in_repr():
    from pydantic import ValidationError
    from app.providers.base import CompletionResult, TokenUsage

    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=1, output_tokens=2, source="not allowed")
    with pytest.raises(ValidationError):
        CompletionResult(text="answer", credentials="not allowed")
    assert "private candidate body" not in repr(CompletionResult(text="private candidate body"))


def test_factory_rejects_empty_api_key_for_openai_compatible_agent() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_api_key="  ",
        llm_model="test-model",
    )

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        get_agent(settings)
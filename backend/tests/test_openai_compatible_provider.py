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


def test_factory_rejects_empty_api_key_for_openai_compatible_agent() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_api_key="  ",
        llm_model="test-model",
    )

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        get_agent(settings)
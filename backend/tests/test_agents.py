import inspect

import pytest

from app.agents import Agent, MockAgent, ProviderAgent, get_agent


@pytest.mark.asyncio
async def test_mock_agent_implements_agent_protocol() -> None:
    agent = MockAgent()

    assert isinstance(agent, Agent)
    assert inspect.iscoroutinefunction(agent.generate)


@pytest.mark.asyncio
async def test_mock_agent_returns_required_markdown_sections() -> None:
    result = await MockAgent().generate("server generated prompt")

    required_sections = (
        "## 解题思路",
        "## 算法步骤",
        "## 正确性说明",
        "## 时间复杂度",
        "## 空间复杂度",
        "## Python 代码",
        "```python",
    )
    assert all(section in result for section in required_sections)


def test_agent_factory_returns_mock_agent_by_default() -> None:
    assert isinstance(get_agent(), MockAgent)


@pytest.mark.asyncio
async def test_provider_agent_delegates_generation_to_provider() -> None:
    class RecordingProvider:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def complete(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return "provider result"

    provider = RecordingProvider()

    result = await ProviderAgent(provider).generate("server prompt")

    assert result == "provider result"
    assert provider.prompts == ["server prompt"]
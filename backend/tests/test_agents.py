import inspect

import pytest

from app.agents import Agent, MockAgent, get_agent


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
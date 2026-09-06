from app.agents.base import Agent
from app.agents.mock import MockAgent


def get_agent() -> Agent:
    """返回当前配置的 Agent 实现，MVP 默认使用 MockAgent。"""

    return MockAgent()
from typing import Protocol, runtime_checkable


@runtime_checkable
class Agent(Protocol):
    """面向业务层的统一 Agent 接口。"""

    async def generate(self, prompt: str) -> str:
        """根据服务端生成的 Prompt 返回 Markdown 解题结果。"""
        ...
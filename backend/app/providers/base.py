from typing import Protocol, runtime_checkable


@runtime_checkable
class Provider(Protocol):
    """未来真实模型 Provider 适配器应实现的最小协议。"""

    async def complete(self, prompt: str) -> str:
        """调用 Provider 并返回原始文本结果。"""
        ...
from app.agents.base import Agent
from app.providers.base import Provider


class ProviderAgent:
    """将通用 Provider 适配为业务层使用的 Agent 接口。"""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    async def generate(self, prompt: str) -> str:
        return await self.provider.complete(prompt)
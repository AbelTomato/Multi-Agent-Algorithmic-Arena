from fastapi import Depends

from app.agents.base import Agent
from app.agents.mock import MockAgent
from app.agents.provider import ProviderAgent
from app.config import Settings, get_settings
from app.providers.openai_compatible import OpenAICompatibleProvider


def get_agent(settings: Settings = Depends(get_settings)) -> Agent:
    """根据配置返回 Agent，未配置真实 Provider 时使用 MockAgent。"""

    if not isinstance(settings, Settings):
        settings = get_settings()

    if settings.llm_provider == "mock":
        return MockAgent()

    if settings.llm_provider != "openai_compatible":
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")

    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value().strip():
        raise ValueError("LLM_API_KEY is required for openai_compatible provider")
    if not settings.llm_model.strip():
        raise ValueError("LLM_MODEL is required for openai_compatible provider")

    return ProviderAgent(
        OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
        )
    )
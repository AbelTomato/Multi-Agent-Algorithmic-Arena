from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)


class CompletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(repr=False)
    usage: TokenUsage | None = None


@runtime_checkable
class MetadataProvider(Protocol):
    async def complete_with_metadata(self, prompt: str) -> CompletionResult:
        ...


class MeteredProvider:
    """每次策略运行独占一个实例；调用前记账，不保留 Prompt、响应或异常。"""

    def __init__(self, provider: MetadataProvider) -> None:
        self.provider = provider
        self.calls = 0
        self.usage_calls = 0
        self._input_tokens = 0
        self._output_tokens = 0

    async def complete_with_metadata(self, prompt: str) -> CompletionResult:
        self.calls += 1
        result = await self.provider.complete_with_metadata(prompt)
        if result.usage is not None:
            self.usage_calls += 1
            self._input_tokens += result.usage.input_tokens
            self._output_tokens += result.usage.output_tokens
        return result

    @property
    def input_tokens(self) -> int | None:
        return self._input_tokens if self.calls == self.usage_calls else None

    @property
    def output_tokens(self) -> int | None:
        return self._output_tokens if self.calls == self.usage_calls else None


@runtime_checkable
class Provider(Protocol):
    """未来真实模型 Provider 适配器应实现的最小协议。"""

    async def complete(self, prompt: str) -> str:
        """调用 Provider 并返回原始文本结果。"""
        ...
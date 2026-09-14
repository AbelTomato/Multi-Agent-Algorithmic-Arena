import httpx
from pydantic import SecretStr


class OpenAICompatibleProvider:
    """调用 OpenAI Chat Completions 兼容接口的最小 Provider。"""

    def __init__(
        self,
        *,
        api_key: SecretStr | str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.transport = transport

    async def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_seconds,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.post("/chat/completions", json=payload)
        except httpx.HTTPError as error:
            raise RuntimeError("OpenAI Compatible request failed") from error

        if response.is_error:
            raise RuntimeError(
                f"OpenAI Compatible request failed with status {response.status_code}"
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError("OpenAI Compatible response has an invalid format") from error

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenAI Compatible response has empty content")

        return content
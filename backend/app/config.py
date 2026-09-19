from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置：集中读取环境变量，避免把配置散落在业务代码里。"""

    app_name: str = "Multi-Agent Algorithmic Arena API"
    debug: bool = True
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/multi_agent_arena"
    agent_retry_count: int = Field(default=1, ge=0, le=3)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    llm_provider: str = "mock"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_tokens: int = Field(default=4096, gt=0)
    evaluation_enabled: bool = False
    evaluation_total_timeout_seconds: float = Field(default=210.0, gt=0)
    evaluation_history_enabled: bool = True
    evaluation_history_cookie_secure: bool = False
    evaluation_history_retention_days: int = Field(default=30, ge=1, le=365)
    evaluation_running_stale_minutes: int = Field(default=10, ge=5, le=1440)
    sandbox_controller_url: str = "http://127.0.0.1:8001"
    sandbox_controller_timeout_seconds: float = Field(default=10.0, gt=0)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的来源配置转换为 CORS Middleware 使用的列表。"""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每次请求都重新读取环境变量。"""

    return Settings()
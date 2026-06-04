from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置：集中读取环境变量，避免把配置散落在业务代码里。"""

    app_name: str = "Multi-Agent Algorithmic Arena API"
    debug: bool = True
    database_url: str = "sqlite+aiosqlite:///./arena.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每次请求都重新读取环境变量。"""

    return Settings()
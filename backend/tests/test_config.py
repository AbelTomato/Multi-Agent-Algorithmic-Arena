from app.config import Settings, get_settings


def test_settings_use_default_values() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "Multi-Agent Algorithmic Arena API"
    assert settings.debug is True
    assert settings.database_url == "postgresql+asyncpg://postgres:postgres@localhost:5432/multi_agent_arena"
    assert settings.agent_retry_count == 1
    assert settings.cors_origins == "http://localhost:5173,http://127.0.0.1:5173"
    assert settings.cors_origin_list == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_settings_can_be_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "Test Arena API")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("AGENT_RETRY_COUNT", "2")
    monkeypatch.setenv("CORS_ORIGINS", " https://frontend.example , ,http://localhost:5173 ")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Test Arena API"
    assert settings.debug is False
    assert settings.database_url == "sqlite+aiosqlite:///./test.db"
    assert settings.agent_retry_count == 2
    assert settings.cors_origin_list == ["https://frontend.example", "http://localhost:5173"]


def test_cors_origins_can_be_empty() -> None:
    settings = Settings(_env_file=None, cors_origins="  , ")

    assert settings.cors_origin_list == []


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()


def test_agent_retry_count_must_be_between_zero_and_three() -> None:
    import pytest

    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_retry_count=-1)

    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_retry_count=4)

    first = get_settings()
    second = get_settings()

    assert first is second

    get_settings.cache_clear()
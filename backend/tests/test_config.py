from app.config import Settings, get_settings


def test_settings_use_default_values() -> None:
    settings = Settings()

    assert settings.app_name == "Multi-Agent Algorithmic Arena API"
    assert settings.debug is True
    assert settings.database_url == "sqlite+aiosqlite:///./arena.db"


def test_settings_can_be_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "Test Arena API")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")

    settings = Settings()

    assert settings.app_name == "Test Arena API"
    assert settings.debug is False
    assert settings.database_url == "sqlite+aiosqlite:///./test.db"


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second

    get_settings.cache_clear()
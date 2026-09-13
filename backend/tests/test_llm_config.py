from app.config import Settings


def test_llm_settings_read_provider_configuration_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_API_KEY", "environment-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1/")
    monkeypatch.setenv("LLM_MODEL", "compatible-model")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_api_key.get_secret_value() == "environment-key"
    assert settings.llm_base_url == "https://llm.example.test/v1/"
    assert settings.llm_model == "compatible-model"
    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_max_tokens == 2048
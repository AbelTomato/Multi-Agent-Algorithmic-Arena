import pytest

from app.database import dispose_engine, get_engine, get_session_factory


@pytest.mark.asyncio
async def test_database_engine_and_session_factory_are_cached() -> None:
    first_engine = get_engine()
    second_engine = get_engine()
    first_factory = get_session_factory()
    second_factory = get_session_factory()

    assert first_engine is second_engine
    assert first_factory is second_factory

    await dispose_engine()

    assert get_engine.cache_info().currsize == 0
    assert get_session_factory.cache_info().currsize == 0
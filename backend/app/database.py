from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass

def create_engine() -> AsyncEngine:
    """创建独立数据库 engine，供 seed 等一次性任务使用。"""

    return create_async_engine(get_settings().database_url)


@lru_cache
def get_engine() -> AsyncEngine:
    """按应用复用数据库 engine，避免每个请求重复创建连接池。"""

    return create_engine()


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回绑定到应用级 engine 的 Session factory。"""

    return async_sessionmaker(
        get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """为每个请求创建 Session，并复用应用级 engine 和连接池。"""

    async with get_session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    """释放应用级连接池，并清理缓存，便于应用关闭或测试重置。"""

    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
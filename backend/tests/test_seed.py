from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.problem import Problem
from app.seed import seed_problems


async def test_seed_is_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        first_inserted = await seed_problems(session)
        second_inserted = await seed_problems(session)

        assert first_inserted == 2
        assert second_inserted == 0

        count = await session.scalar(select(func.count()).select_from(Problem))
        assert count == 2

    await engine.dispose()
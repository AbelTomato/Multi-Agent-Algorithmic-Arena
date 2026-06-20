from app.models.problem import Problem

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select

from app.config import get_settings

from app.models.problem import Problem

from app.database import Base


setting = get_settings()


def test_problem_table_metadata():
    assert Problem.__tablename__ == "problems"
    
    column_names = {column.name for column in Problem.__table__.columns}
    
    assert column_names == {
        "id",
        "slug",
        "title",
        "description",
        "created_at",
        "updated_at"
    }
    
    
async def test_can_insert_and_query_problem():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
        
    async with async_session() as session:
        problem = Problem()
        
        problem.slug = "a_plus_b"
        problem.title = "A+B Problem"
        problem.description = "return the result of A+B"
        
        session.add(problem)
        
        await session.commit()
        
        statement = select(Problem).where(Problem.id == 1)
        
        result = await session.execute(statement)
        
        p = result.scalars().first()
        
        assert p.slug == "a_plus_b" and p.title == "A+B Problem" and p.description == "return the result of A+B"
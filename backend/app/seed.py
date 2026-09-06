from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import create_engine
from app.models.problem import Problem


SEED_PROBLEMS: Sequence[dict[str, str]] = (
    {
        "slug": "two-sum",
        "title": "Two Sum",
        "description": """# Two Sum

给定一个整数数组 `nums` 和一个整数 `target`，请返回数组中和为 `target` 的两个元素的下标。

假设每种输入只会对应一个答案，且同一个元素不能使用两次。
""",
    },
    {
        "slug": "valid-parentheses",
        "title": "Valid Parentheses",
        "description": """# Valid Parentheses

给定只包含括号 `()[]{}` 的字符串 `s`，判断字符串中的括号是否有效。

有效字符串要求每个左括号都由相同类型的右括号闭合，且闭合顺序正确。
""",
    },
)


async def seed_problems(session: AsyncSession) -> int:
    """插入缺失的预置题目，返回本次新增数量。"""

    inserted = 0
    for data in SEED_PROBLEMS:
        result = await session.execute(select(Problem).where(Problem.slug == data["slug"]))
        if result.scalar_one_or_none() is not None:
            continue
        session.add(Problem(**data))
        inserted += 1
    await session.commit()
    return inserted


async def run_seed() -> int:
    engine = create_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await seed_problems(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    added = asyncio.run(run_seed())
    print(f"Seed completed: inserted {added} problem(s).")
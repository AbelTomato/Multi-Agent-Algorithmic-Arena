from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.submission import Submission


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def cleanup_expired_submission_sources(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    execute: bool = False,
    clock: Callable[[], datetime] = utc_now,
) -> int:
    """清理到期 Submission 源码，默认 dry-run，且可重复执行。"""

    cutoff = now or clock()
    filters = (
        Submission.retention_expires_at <= cutoff,
        Submission.source_deleted_at.is_(None),
        Submission.source.is_not(None),
    )
    async with session_factory() as session:
        if not execute:
            count = await session.scalar(
                select(func.count()).select_from(Submission).where(*filters)
            )
            return int(count or 0)

        result = await session.execute(
            update(Submission)
            .where(*filters)
            .values(source=None, source_deleted_at=cutoff)
        )
        await session.commit()
        return int(result.rowcount or 0)
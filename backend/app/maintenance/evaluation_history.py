"""清理过期评测历史的安全维护命令。"""

import argparse
import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.models.evaluation_run import EvaluationRun
from app.services.evaluation_runs import TERMINAL_RUN_STATUSES, EvaluationRunRepository


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("retention-days must be >= 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="清理过期评测历史；默认仅 dry-run，不提交任何删除。"
    )
    parser.add_argument(
        "--retention-days",
        type=_positive_integer,
        default=None,
        metavar="N",
        help="保留最近 N 天的终态记录（默认读取 Settings）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="确认执行删除；未提供时只统计并 rollback",
    )
    return parser


async def cleanup_expired_runs(
    session_factory: async_sessionmaker[AsyncSession],
    retention_days: int,
    *,
    execute: bool = False,
    now: datetime | None = None,
) -> int:
    if retention_days < 1:
        raise ValueError("retention_days must be >= 1")

    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days)
    async with session_factory() as session:
        try:
            count_statement = select(func.count()).select_from(EvaluationRun).where(
                EvaluationRun.created_at < cutoff,
                EvaluationRun.run_status.in_(TERMINAL_RUN_STATUSES),
            )
            candidate_count = int(await session.scalar(count_statement) or 0)
            if execute:
                deleted_count = await EvaluationRunRepository(session).delete_expired_runs(cutoff)
                await session.commit()
                count = deleted_count
                mode = "execute"
            else:
                await session.rollback()
                count = candidate_count
                mode = "dry-run"
        except Exception:
            await session.rollback()
            raise

    print(f"mode={mode} cutoff={cutoff.isoformat()} count={count}")
    return count


async def _run(settings: Settings, retention_days: int, execute: bool) -> int:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await cleanup_expired_runs(
            session_factory,
            retention_days,
            execute=execute,
        )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    retention_days = args.retention_days or settings.evaluation_history_retention_days
    asyncio.run(_run(settings, retention_days, args.execute))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
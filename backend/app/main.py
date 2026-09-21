from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.database import dispose_engine, get_session_factory
from app.middleware.evaluation_session import EvaluationSessionMiddleware
from app.services.evaluation_runs import EvaluationRunRepository

from app.api.problems import router as problem_router
from app.api.evaluations import router as evaluation_router
from app.api.solutions import router as solution_router
from app.api.submissions import router as submission_router
from app.api.contests import router as contest_router
settings = get_settings()


async def recover_stale_evaluation_runs(
    session_factory: async_sessionmaker[AsyncSession],
    current_settings: Settings,
    *,
    now: datetime | None = None,
) -> int:
    recovered_at = now or datetime.now(timezone.utc)
    cutoff = recovered_at - timedelta(minutes=current_settings.evaluation_running_stale_minutes)
    async with session_factory() as session:
        try:
            count = await EvaluationRunRepository(
                session,
                clock=lambda: recovered_at,
            ).interrupt_stale_runs(cutoff)
            await session.commit()
            return count
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await recover_stale_evaluation_runs(get_session_factory(), settings)
    yield
    await dispose_engine()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)
app.add_middleware(EvaluationSessionMiddleware, settings=settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(problem_router)
app.include_router(solution_router)
app.include_router(evaluation_router)
app.include_router(submission_router)
app.include_router(contest_router)

@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Multi-Agent Algorithmic Arena API"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
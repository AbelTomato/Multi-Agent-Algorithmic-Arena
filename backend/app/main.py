from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import dispose_engine

from app.api.problems import router as problem_router
from app.api.evaluations import router as evaluation_router
from app.api.solutions import router as solution_router



@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await dispose_engine()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(problem_router)
app.include_router(solution_router)
app.include_router(evaluation_router)

@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Multi-Agent Algorithmic Arena API"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
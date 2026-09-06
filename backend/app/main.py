from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import dispose_engine

from app.api.problems import router as problem_router
from app.api.solutions import router as solution_router



@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用关闭时释放共享数据库连接池。"""

    yield
    await dispose_engine()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)
app.include_router(problem_router)
app.include_router(solution_router)

@app.get("/")
async def root() -> dict[str, str]:
    """最小根路由，用来确认后端服务已经启动。"""

    return {"message": "Multi-Agent Algorithmic Arena API"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """健康检查接口，后续 Docker 和部署环境会用它判断服务是否可用。"""

    return {"status": "ok"}
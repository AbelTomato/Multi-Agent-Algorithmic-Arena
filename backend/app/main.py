from fastapi import FastAPI

from app.config import get_settings


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)


@app.get("/")
async def root() -> dict[str, str]:
    """最小根路由，用来确认后端服务已经启动。"""

    return {"message": "Multi-Agent Algorithmic Arena API"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """健康检查接口，后续 Docker 和部署环境会用它判断服务是否可用。"""

    return {"status": "ok"}
"""执行控制器 HTTP 入口

仅绑定 loopback，限制并发。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from app.protocol import ExecutionRequest, ExecutionResult
from app.runner import DockerRunner

# 全局并发控制
_execution_lock = False
_runner = DockerRunner()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期"""
    print("✅ 执行控制器启动")
    yield
    print("🛑 执行控制器关闭")


app = FastAPI(
    title="Arena Sandbox Execution Controller",
    description="安全的代码执行控制器",
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "sandbox"}


@app.post("/execute", response_model=ExecutionResult)
async def execute_code(request: ExecutionRequest):
    """执行代码

    限制并发为 1，忙碁时返回 409。
    """
    global _execution_lock

    # 并发控制
    if _execution_lock:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="执行槽已占用，请稍后重试"
        )

    try:
        _execution_lock = True
        result = _runner.execute(request)
        return result
    finally:
        _execution_lock = False


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    """通用异常处理"""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "执行控制器内部错误",
            "error": str(exc)
        }
    )

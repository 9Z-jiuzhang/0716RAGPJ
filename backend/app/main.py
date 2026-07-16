"""FastAPI 应用入口。"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import close_db, init_db
from app.schemas.common import BaseResponse

_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库，关闭时释放连接池。"""
    print(f"[启动] {settings.APP_NAME} v{settings.APP_VERSION}")
    try:
        await init_db()
        print("[启动] 数据库连接池已初始化")
    except Exception as exc:
        # 开发阶段允许无库启动（仅加载路由契约）
        print(f"[警告] 数据库初始化失败（可稍后启动 Postgres）: {exc}")
    yield
    await close_db()
    print("[关闭] 资源已释放")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", tags=["健康检查"])
async def root():
    """根路径健康检查。"""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "uptime_seconds": int(time.time() - _start_time),
    }


@app.get("/metrics", tags=["监控"])
async def metrics():
    """Prometheus 指标端点。"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTP 异常统一为 BaseResponse。"""
    from uuid import uuid4

    rid = request.headers.get("X-Request-Id") or str(uuid4())
    return JSONResponse(
        status_code=exc.status_code,
        content=BaseResponse(
            code=exc.status_code, message=str(exc.detail), data=None, request_id=rid
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 校验失败。"""
    from uuid import uuid4

    rid = request.headers.get("X-Request-Id") or str(uuid4())
    return JSONResponse(
        status_code=422,
        content=BaseResponse(
            code=422,
            message="请求参数校验失败",
            data={"errors": exc.errors()},
            request_id=rid,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """全局 500。"""
    from uuid import uuid4

    rid = request.headers.get("X-Request-Id") or str(uuid4())
    return JSONResponse(
        status_code=500,
        content=BaseResponse(
            code=500, message="服务器内部错误", data={"error": str(exc)}, request_id=rid
        ).model_dump(),
    )


"""系统监控与健康检查：探测 PostgreSQL、Redis、Chroma 连通性。"""
from fastapi import APIRouter
from sqlalchemy import text

from app.core.chroma import ping_chroma
from app.core.config import settings
from app.core.database import engine
from app.core.redis import ping_redis

router = APIRouter(prefix="/monitor", tags=["系统监控"])


async def _check_postgres() -> dict:
    """探测 PostgreSQL 是否可执行简单查询。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/health")
async def health_check():
    """
    综合健康检查端点。

    供 Docker healthcheck 与运维探活使用：
    - overall=ok：所有依赖均正常
    - overall=degraded：部分依赖异常，HTTP 仍返回 200 以便定位具体组件
    """
    postgres = await _check_postgres()
    redis = {"status": "ok" if await ping_redis() else "error"}
    chroma = {"status": "ok" if ping_chroma() else "error"}

    components = {
        "postgres": postgres,
        "redis": redis,
        "chroma": chroma,
    }
    overall = "ok" if all(c.get("status") == "ok" for c in components.values()) else "degraded"

    return {
        "status": overall,
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "components": components,
    }

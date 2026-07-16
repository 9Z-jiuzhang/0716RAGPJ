"""系统监控服务：健康检查与统计概览。"""

from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine
from app.core.metrics import (
    active_sessions,
    doc_total,
    kb_total,
    users_registered,
    vectorize_queue_size,
)
from app.models.document import Document
from app.models.identity import User
from app.models.knowledge_base import KnowledgeBase
from app.models.vectorize_task import VectorizeTask
from app.schemas.monitor import HealthCheckItem, HealthResponse, SystemStatsResponse
from app.services.langfuse_service import get_langfuse

logger = logging.getLogger(__name__)

_APP_STARTED_AT = time.time()


class MonitorService:
    def __init__(self, db: Optional[AsyncSession] = None) -> None:
        self.db = db

    async def health(self) -> HealthResponse:
        checks: dict[str, HealthCheckItem] = {}
        overall = "healthy"

        # Postgres
        try:
            t0 = time.perf_counter()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = HealthCheckItem(
                status="healthy",
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except Exception:
            logger.exception("postgres health check failed")
            checks["postgres"] = HealthCheckItem(status="unhealthy")
            overall = "unhealthy"

        # Redis（优先走 lifespan 初始化的客户端）
        redis_status, redis_latency = await self._check_redis()
        checks["redis"] = HealthCheckItem(status=redis_status, latency_ms=redis_latency)
        if redis_status == "unhealthy" and overall == "healthy":
            overall = "degraded"

        # Chroma
        chroma_status, chroma_latency = self._check_chroma()
        checks["chroma"] = HealthCheckItem(status=chroma_status, latency_ms=chroma_latency)
        if chroma_status == "unhealthy" and overall == "healthy":
            overall = "degraded"

        # Langfuse
        lf_status, lf_latency = await get_langfuse().health_probe()
        checks["langfuse"] = HealthCheckItem(status=lf_status, latency_ms=lf_latency)
        if lf_status in ("unhealthy", "degraded") and overall == "healthy":
            overall = "degraded"

        return HealthResponse(
            status=overall,
            version=settings.APP_VERSION,
            uptime_seconds=int(time.time() - _APP_STARTED_AT),
            checks=checks,
        )

    async def _check_redis(self) -> tuple[str, Optional[float]]:
        try:
            from app.core.redis import ping_redis

            t0 = time.perf_counter()
            ok = await ping_redis()
            latency = round((time.perf_counter() - t0) * 1000, 2)
            return ("healthy" if ok else "unhealthy"), latency
        except Exception:
            logger.warning("redis health check failed", exc_info=True)
            return "unhealthy", None

    def _check_chroma(self) -> tuple[str, Optional[float]]:
        try:
            from app.core.chroma import ping_chroma

            t0 = time.perf_counter()
            ok = ping_chroma()
            latency = round((time.perf_counter() - t0) * 1000, 2)
            return ("healthy" if ok else "unhealthy"), latency
        except Exception:
            logger.warning("chroma health check failed", exc_info=True)
            return "unhealthy", None

    async def stats(self) -> SystemStatsResponse:
        assert self.db is not None
        user_count = int(await self.db.scalar(select(func.count()).select_from(User)) or 0)
        try:
            kb_count = int(
                await self.db.scalar(
                    select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.status != "deleted")
                )
                or 0
            )
        except Exception:
            kb_count = 0
        try:
            document_count = int(await self.db.scalar(select(func.count()).select_from(Document)) or 0)
        except Exception:
            document_count = 0
        try:
            queue_size = int(
                await self.db.scalar(
                    select(func.count())
                    .select_from(VectorizeTask)
                    .where(VectorizeTask.status.in_(["pending", "running", "queued"]))
                )
                or 0
            )
        except Exception:
            queue_size = 0

        # 活跃会话：统计未关闭的问答会话
        sessions = 0
        try:
            from app.models.qa import QASession

            sessions = int(
                await self.db.scalar(
                    select(func.count()).select_from(QASession).where(QASession.status == "active")
                )
                or 0
            )
        except Exception:
            sessions = 0

        users_registered.set(user_count)
        kb_total.set(kb_count)
        doc_total.set(document_count)
        vectorize_queue_size.set(queue_size)
        active_sessions.set(sessions)

        return SystemStatsResponse(
            user_count=user_count,
            kb_count=kb_count,
            doc_count=document_count,
            active_sessions=sessions,
            task_queue_size=queue_size,
        )

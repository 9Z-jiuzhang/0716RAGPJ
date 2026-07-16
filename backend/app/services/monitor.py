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

        # Redis
        redis_status, redis_latency = await self._check_redis()
        checks["redis"] = HealthCheckItem(status=redis_status, latency_ms=redis_latency)
        if redis_status == "unhealthy" and overall == "healthy":
            overall = "degraded"

        # Langfuse
        lf_status, lf_latency = await get_langfuse().health_probe()
        checks["langfuse"] = HealthCheckItem(status=lf_status, latency_ms=lf_latency)
        if lf_status == "unhealthy" and overall == "healthy":
            overall = "degraded"
        elif lf_status == "degraded" and overall == "healthy":
            overall = "degraded"

        return HealthResponse(
            status=overall,
            version=settings.APP_VERSION,
            uptime_seconds=int(time.time() - _APP_STARTED_AT),
            checks=checks,
        )

    async def _check_redis(self) -> tuple[str, Optional[float]]:
        try:
            import redis.asyncio as redis

            t0 = time.perf_counter()
            client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
            try:
                await client.ping()
            finally:
                await client.aclose()
            return "healthy", round((time.perf_counter() - t0) * 1000, 2)
        except ImportError:
            # 未安装 redis 包时退化为 TCP 探活
            import asyncio

            try:
                t0 = time.perf_counter()
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(settings.REDIS_HOST, settings.REDIS_PORT),
                    timeout=2.0,
                )
                writer.close()
                await writer.wait_closed()
                return "healthy", round((time.perf_counter() - t0) * 1000, 2)
            except Exception:
                logger.warning("redis TCP probe failed", exc_info=True)
                return "unhealthy", None
        except Exception:
            logger.warning("redis health check failed", exc_info=True)
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

        # 活跃会话：问答模块未落地前固定为 0，指标仍暴露
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

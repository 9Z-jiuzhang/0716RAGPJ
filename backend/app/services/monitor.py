"""系统监控服务：健康检查与统计概览。"""

from __future__ import annotations

import logging
import time

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
    def __init__(self, db: AsyncSession | None = None) -> None:
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

    async def _check_redis(self) -> tuple[str, float | None]:
        try:
            from app.core.redis import ping_redis

            t0 = time.perf_counter()
            ok = await ping_redis()
            latency = round((time.perf_counter() - t0) * 1000, 2)
            return ("healthy" if ok else "unhealthy"), latency
        except Exception:
            logger.warning("redis health check failed", exc_info=True)
            return "unhealthy", None

    def _check_chroma(self) -> tuple[str, float | None]:
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

        # 活跃会话：未关闭且未闲置过期的问答会话
        sessions = 0
        try:
            from app.models.qa import QASession

            sessions = int(
                await self.db.scalar(select(func.count()).select_from(QASession).where(QASession.status == "active"))
                or 0
            )
        except Exception:
            sessions = 0

        users_registered.set(user_count)
        kb_total.set(kb_count)
        doc_total.set(document_count)
        vectorize_queue_size.set(queue_size)
        active_sessions.set(sessions)

        guard_stats = await self._guard_stats()
        return SystemStatsResponse(
            user_count=user_count,
            kb_count=kb_count,
            doc_count=document_count,
            active_sessions=sessions,
            task_queue_size=queue_size,
            qa_trend_7d=await self._qa_trend_7d(),
            hit_rate_trend_7d=await self._hit_rate_trend_7d(),
            guard_blocked_24h=guard_stats["blocked_24h"],
            guard_blocked_7d=guard_stats["blocked_7d"],
            guard_recent_events=guard_stats["recent_events"],
        )

    async def _guard_stats(self) -> dict[str, object]:
        """统计最近恶意访问阻拦次数；返回内容不包含用户问题正文。"""
        from datetime import timedelta

        from app.models.base import utcnow
        from app.models.guard import GuardBlockedEvent

        now = utcnow()
        try:
            blocked_24h = int(
                await self.db.scalar(
                    select(func.count())
                    .select_from(GuardBlockedEvent)
                    .where(GuardBlockedEvent.created_at >= now - timedelta(hours=24))
                )
                or 0
            )
            blocked_7d = int(
                await self.db.scalar(
                    select(func.count())
                    .select_from(GuardBlockedEvent)
                    .where(GuardBlockedEvent.created_at >= now - timedelta(days=7))
                )
                or 0
            )
            rows = list(
                (
                    await self.db.scalars(
                        select(GuardBlockedEvent).order_by(GuardBlockedEvent.created_at.desc()).limit(10)
                    )
                ).all()
            )
            recent_events = [
                {
                    "intent": row.intent,
                    "reason_code": row.reason_code,
                    "detector": row.detector,
                    "confidence": round(row.confidence, 4),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
            return {
                "blocked_24h": blocked_24h,
                "blocked_7d": blocked_7d,
                "recent_events": recent_events,
            }
        except Exception:
            logger.warning("guard stats query failed", exc_info=True)
            return {"blocked_24h": 0, "blocked_7d": 0, "recent_events": []}

    async def _qa_trend_7d(self) -> list[int]:
        """近 7 天每日用户提问数（含今天，按日升序）。"""
        from datetime import datetime, timedelta, timezone

        from app.models.qa import QAMessage

        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=6)
        try:
            rows = (
                await self.db.execute(
                    select(
                        func.date(QAMessage.created_at).label("d"),
                        func.count().label("c"),
                    )
                    .where(
                        QAMessage.role == "user",
                        QAMessage.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
                    )
                    .group_by(func.date(QAMessage.created_at))
                )
            ).all()
            counts = {str(r.d): int(r.c) for r in rows}
        except Exception:
            logger.warning("qa_trend_7d query failed", exc_info=True)
            counts = {}
        out: list[int] = []
        for i in range(7):
            day = start + timedelta(days=i)
            out.append(counts.get(str(day), 0))
        return out

    async def _hit_rate_trend_7d(self) -> list[float]:
        """近 7 天每日命中率（completed runs 的 hit_count/total_questions）。"""
        from datetime import datetime, timedelta, timezone

        from app.models.hit_tests import TestRuns

        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=6)
        try:
            rows = (
                await self.db.execute(
                    select(
                        func.date(TestRuns.completed_at).label("d"),
                        func.coalesce(func.sum(TestRuns.hit_count), 0).label("hits"),
                        func.coalesce(func.sum(TestRuns.total_questions), 0).label("total"),
                    )
                    .where(
                        TestRuns.status == "completed",
                        TestRuns.completed_at.is_not(None),
                        TestRuns.completed_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
                    )
                    .group_by(func.date(TestRuns.completed_at))
                )
            ).all()
            rates = {str(r.d): (float(r.hits) / float(r.total) if int(r.total) > 0 else 0.0) for r in rows}
        except Exception:
            logger.warning("hit_rate_trend_7d query failed", exc_info=True)
            rates = {}
        out: list[float] = []
        for i in range(7):
            day = start + timedelta(days=i)
            out.append(round(rates.get(str(day), 0.0), 4))
        return out

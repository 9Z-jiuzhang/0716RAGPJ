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

        # MinIO 对象存储
        minio_status, minio_latency = self._check_minio()
        checks["minio"] = HealthCheckItem(status=minio_status, latency_ms=minio_latency)
        if minio_status == "unhealthy" and overall == "healthy":
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

    def _check_minio(self) -> tuple[str, float | None]:
        """探测 MinIO 连通性与鉴权（list_buckets）。"""
        try:
            from app.services.storage import get_minio_client

            t0 = time.perf_counter()
            get_minio_client().list_buckets()
            latency = round((time.perf_counter() - t0) * 1000, 2)
            return "healthy", latency
        except Exception:
            logger.warning("minio health check failed", exc_info=True)
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
        qa_30 = await self._qa_trend(30)
        hit_30 = await self._hit_rate_trend(30)
        err_hourly = await self._error_hourly(48)
        # 近 24h 拆成 4 段（每段 6h），兼容旧前端
        err_24 = []
        last_24 = err_hourly[-24:] if len(err_hourly) >= 24 else ([0] * (24 - len(err_hourly)) + err_hourly)
        for i in range(4):
            chunk = last_24[i * 6 : (i + 1) * 6]
            err_24.append(sum(chunk))
        return SystemStatsResponse(
            user_count=user_count,
            kb_count=kb_count,
            doc_count=document_count,
            active_sessions=sessions,
            task_queue_size=queue_size,
            qa_trend_7d=qa_30[-7:] if len(qa_30) >= 7 else qa_30,
            hit_rate_trend_7d=hit_30[-7:] if len(hit_30) >= 7 else hit_30,
            qa_trend_30d=qa_30,
            hit_rate_trend_30d=hit_30,
            error_24h=err_24,
            error_hourly_48h=err_hourly,
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
                    "id": str(row.id),
                    "intent": row.intent,
                    "reason_code": row.reason_code,
                    "detector": row.detector,
                    "confidence": round(row.confidence, 4),
                    "created_at": row.created_at.isoformat(),
                    "actor_label": getattr(row, "actor_label", None) or ("访客" if row.user_id is None else "-"),
                    "client_ip": getattr(row, "client_ip", None),
                    "user_id": str(row.user_id) if row.user_id else None,
                    "is_registered": row.user_id is not None,
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

    async def list_guard_events(self, *, page: int = 1, page_size: int = 50) -> dict[str, object]:
        """分页列出 Guard 阻拦事件（含账号与 IP，不含完整问题原文）。"""
        from datetime import timedelta

        from app.models.base import utcnow
        from app.models.guard import GuardBlockedEvent

        page = max(1, int(page or 1))
        page_size = max(1, min(100, int(page_size or 50)))
        now = utcnow()
        try:
            total = int(await self.db.scalar(select(func.count()).select_from(GuardBlockedEvent)) or 0)
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
                        select(GuardBlockedEvent)
                        .order_by(GuardBlockedEvent.created_at.desc())
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                ).all()
            )
            items = [
                {
                    "id": str(row.id),
                    "created_at": row.created_at.isoformat(),
                    "intent": row.intent,
                    "reason_code": row.reason_code,
                    "detector": row.detector,
                    "confidence": round(float(row.confidence or 0), 4),
                    "actor_label": (getattr(row, "actor_label", None) or "").strip()
                    or ("访客" if row.user_id is None else "-"),
                    "client_ip": getattr(row, "client_ip", None),
                    "user_id": str(row.user_id) if row.user_id else None,
                    "is_registered": row.user_id is not None,
                    "question_preview": row.question_preview,
                }
                for row in rows
            ]
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "blocked_24h": blocked_24h,
                "blocked_7d": blocked_7d,
            }
        except Exception:
            logger.warning("guard events list failed", exc_info=True)
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "blocked_24h": 0,
                "blocked_7d": 0,
            }

    async def _qa_trend_7d(self) -> list[int]:
        """近 7 天每日用户提问数（含今天，按日升序）。"""
        return await self._qa_trend(7)

    async def _qa_trend(self, days: int = 7) -> list[int]:
        """近 N 天每日用户提问数（含今天，按日升序）。"""
        from datetime import datetime, timedelta, timezone

        from app.models.qa import QAMessage

        days = max(1, min(int(days), 90))
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days - 1)
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
            logger.warning("qa_trend query failed", exc_info=True)
            counts = {}
        out: list[int] = []
        for i in range(days):
            day = start + timedelta(days=i)
            out.append(counts.get(str(day), 0))
        return out

    async def _hit_rate_trend_7d(self) -> list[float]:
        """近 7 天每日命中率（completed runs 的 hit_count/total_questions）。"""
        return await self._hit_rate_trend(7)

    async def _hit_rate_trend(self, days: int = 7) -> list[float]:
        """近 N 天每日命中率（completed runs 的 hit_count/total_questions）。"""
        from datetime import datetime, timedelta, timezone

        from app.models.hit_tests import TestRuns

        days = max(1, min(int(days), 90))
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days - 1)
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
            logger.warning("hit_rate_trend query failed", exc_info=True)
            rates = {}
        out: list[float] = []
        for i in range(days):
            day = start + timedelta(days=i)
            out.append(round(rates.get(str(day), 0.0), 4))
        return out

    async def _error_hourly(self, hours: int = 48) -> list[int]:
        """近 N 小时每小时错误量：文档失败 + 向量化失败（旧→新）。"""
        from datetime import datetime, timedelta, timezone

        hours = max(1, min(int(hours), 168))
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(hours=hours - 1)
        counts: dict[str, int] = {}

        def _hour_key(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")

        try:
            doc_rows = (
                await self.db.execute(
                    select(Document.updated_at).where(
                        Document.status == "failed",
                        Document.updated_at >= start,
                    )
                )
            ).all()
            for (ts,) in doc_rows:
                if ts is None:
                    continue
                key = _hour_key(ts)
                counts[key] = counts.get(key, 0) + 1
        except Exception:
            logger.warning("error_hourly document query failed", exc_info=True)

        try:
            task_rows = (
                await self.db.execute(
                    select(VectorizeTask.updated_at).where(
                        VectorizeTask.status == "failed",
                        VectorizeTask.updated_at >= start,
                    )
                )
            ).all()
            for (ts,) in task_rows:
                if ts is None:
                    continue
                key = _hour_key(ts)
                counts[key] = counts.get(key, 0) + 1
        except Exception:
            logger.warning("error_hourly vectorize query failed", exc_info=True)

        out: list[int] = []
        for i in range(hours):
            slot = start + timedelta(hours=i)
            out.append(counts.get(slot.strftime("%Y-%m-%dT%H"), 0))
        return out

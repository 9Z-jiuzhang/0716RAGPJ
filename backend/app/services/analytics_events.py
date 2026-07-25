"""问答事件与反馈写入服务（失败仅记日志，不抛向用户链路）。"""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analytics import QAFeedbackEvent, QARequestEvent
from app.schemas.optimization_contracts import QAFeedbackUpsert, QARequestEventCreate

logger = logging.getLogger(__name__)


def actor_hash_for(user_id: str | None, guest_id: str | None) -> str:
    raw = f"u:{user_id or ''}|g:{guest_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def question_hash(text: str) -> str:
    normalized = " ".join((text or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


class AnalyticsEventService:
    """异步友好的事件写入；调用方可用 create_task 包装。"""

    async def record_request(self, db: AsyncSession, payload: QARequestEventCreate) -> None:
        if not settings.ANALYTICS_PIPELINE_V2_ENABLED:
            return
        try:
            row = QARequestEvent(
                request_id=payload.request_id,
                trace_id=payload.trace_id,
                conversation_id=payload.conversation_id,
                message_id=payload.message_id,
                actor_hash=payload.actor_hash,
                tenant_id=payload.tenant_id,
                role_ids=payload.role_ids,
                question_hash=payload.question_hash,
                question_preview=(payload.question_preview or "")[:240] or None,
                route_intent=payload.route_intent,
                route_confidence=payload.route_confidence,
                should_retrieve=payload.should_retrieve,
                top_k=payload.top_k,
                rewrite_enabled=payload.rewrite_enabled,
                cache_level=payload.cache_level,
                cache_hit_id=payload.cache_hit_id,
                normalized_similarity=payload.normalized_similarity,
                miss_reason=payload.miss_reason,
                retrieval_hit_count=payload.retrieval_hit_count,
                citation_count=payload.citation_count,
                model_snapshot_id=payload.model_snapshot_id,
                latency_ms=payload.latency_ms,
                result_status=payload.result_status,
                error_code=payload.error_code,
                detail=payload.detail or {},
            )
            db.add(row)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("qa_request_event write failed request_id=%s", payload.request_id)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    async def upsert_feedback(self, db: AsyncSession, payload: QAFeedbackUpsert) -> dict[str, Any]:
        stmt = insert(QAFeedbackEvent).values(
            message_id=payload.message_id,
            actor_hash=payload.actor_hash,
            rating=payload.rating,
            reason=payload.reason,
            comment=payload.comment,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_qa_feedback_message_actor",
            set_={
                "rating": payload.rating,
                "reason": payload.reason,
                "comment": payload.comment,
            },
        ).returning(QAFeedbackEvent.id, QAFeedbackEvent.rating)
        result = await db.execute(stmt)
        await db.commit()
        row = result.first()
        return {"id": str(row[0]) if row else None, "rating": payload.rating}

    async def feedback_summary(self, db: AsyncSession, *, days: int = 14) -> dict[str, Any]:
        """反馈汇总 + 路由/缓存分布 + 近 N 日趋势（供管理端图表）。"""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import cast, Date, func

        useful_n = await db.scalar(
            select(func.count()).select_from(QAFeedbackEvent).where(QAFeedbackEvent.rating == "useful")
        )
        useless_n = await db.scalar(
            select(func.count()).select_from(QAFeedbackEvent).where(QAFeedbackEvent.rating == "useless")
        )
        total_events = await db.scalar(select(func.count()).select_from(QARequestEvent))
        actor_n = await db.scalar(
            select(func.count(func.distinct(QARequestEvent.actor_hash))).select_from(QARequestEvent)
        )
        session_n = await db.scalar(
            select(func.count(func.distinct(QARequestEvent.conversation_id))).select_from(QARequestEvent)
        )
        avg_latency = await db.scalar(select(func.avg(QARequestEvent.latency_ms)).select_from(QARequestEvent))

        route_rows = (
            await db.execute(
                select(QARequestEvent.route_intent, func.count())
                .group_by(QARequestEvent.route_intent)
                .order_by(func.count().desc())
                .limit(12)
            )
        ).all()
        cache_rows = (
            await db.execute(
                select(QARequestEvent.cache_level, func.count())
                .group_by(QARequestEvent.cache_level)
                .order_by(func.count().desc())
                .limit(12)
            )
        ).all()

        since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))
        day_col = cast(QARequestEvent.created_at, Date)
        trend_req = (
            await db.execute(
                select(day_col.label("d"), func.count())
                .where(QARequestEvent.created_at >= since)
                .group_by(day_col)
                .order_by(day_col)
            )
        ).all()
        fb_day = cast(QAFeedbackEvent.created_at, Date)
        trend_fb = (
            await db.execute(
                select(fb_day.label("d"), QAFeedbackEvent.rating, func.count())
                .where(QAFeedbackEvent.created_at >= since)
                .group_by(fb_day, QAFeedbackEvent.rating)
                .order_by(fb_day)
            )
        ).all()

        # 补齐日期轴，避免折线断层
        day_keys: list[str] = []
        cursor = since.date()
        end = datetime.now(timezone.utc).date()
        while cursor <= end:
            day_keys.append(cursor.isoformat())
            cursor += timedelta(days=1)
        req_map = {str(r[0]): int(r[1]) for r in trend_req}
        useful_map: dict[str, int] = {}
        useless_map: dict[str, int] = {}
        for d, rating, n in trend_fb:
            key = str(d)
            if rating == "useful":
                useful_map[key] = int(n)
            elif rating == "useless":
                useless_map[key] = int(n)

        feedback_total = int(useful_n or 0) + int(useless_n or 0)
        request_total = int(total_events or 0)
        return {
            "useful": int(useful_n or 0),
            "useless": int(useless_n or 0),
            "request_events": request_total,
            "unique_actors": int(actor_n or 0),
            "unique_conversations": int(session_n or 0),
            "feedback_rate": round(feedback_total / request_total, 4) if request_total else 0.0,
            "avg_latency_ms": int(round(float(avg_latency))) if avg_latency is not None else None,
            "route_distribution": [
                {"label": (r[0] or "unknown"), "count": int(r[1])} for r in route_rows
            ],
            "cache_distribution": [
                {"label": (r[0] or "none"), "count": int(r[1])} for r in cache_rows
            ],
            "trend_days": days,
            "trend": [
                {
                    "date": d,
                    "requests": req_map.get(d, 0),
                    "useful": useful_map.get(d, 0),
                    "useless": useless_map.get(d, 0),
                }
                for d in day_keys
            ],
            "privacy": "aggregate_only",
        }


analytics_event_service = AnalyticsEventService()

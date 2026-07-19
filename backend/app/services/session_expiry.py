"""闲置会话过期：将超时未活跃的问答会话标为 expired，并清理 Redis 热缓存。

不影响历史功能：
- 历史列表/消息查询仍按 status != deleted，expired 会话可见可读；
- 用户从历史继续提问时由流水线重新激活为 active，并从 PG 回填上下文。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.memory.session_store import session_store
from app.models.base import utcnow
from app.models.qa import QASession

logger = logging.getLogger(__name__)


async def expire_idle_sessions(db: AsyncSession, *, batch_size: int = 200) -> int:
    """
    将 last_active_at 超过闲置阈值的 active 会话标记为 expired，并删除 Redis 热键。

    Returns:
        本轮过期的会话数量。
    """
    idle_minutes = max(1, int(settings.QA_SESSION_IDLE_EXPIRE_MINUTES))
    cutoff = utcnow() - timedelta(minutes=idle_minutes)

    sessions = list(
        (
            await db.scalars(
                select(QASession)
                .where(
                    QASession.status == "active",
                    QASession.last_active_at < cutoff,
                )
                .order_by(QASession.last_active_at.asc())
                .limit(batch_size)
            )
        ).all()
    )
    if not sessions:
        return 0

    for session in sessions:
        session.status = "expired"
        try:
            await session_store.delete_session_cache(session.id, guest_id=session.guest_id)
        except Exception:
            logger.warning("清理过期会话 Redis 失败 session_id=%s", session.id, exc_info=True)

    await db.commit()
    logger.info("闲置会话已过期 count=%s idle_minutes=%s", len(sessions), idle_minutes)
    return len(sessions)


async def run_session_expiry_once() -> int:
    """独立 DB 会话执行一轮过期扫描（供后台循环调用）。"""
    async with SessionLocal() as db:
        return await expire_idle_sessions(db)


async def session_expiry_loop(stop_event: asyncio.Event) -> None:
    """后台循环：按配置间隔扫描并过期闲置会话。"""
    interval = max(30, int(settings.QA_SESSION_EXPIRE_SWEEP_SECONDS))
    # 启动后稍等，避免与种子/建表抢连接
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=min(15, interval))
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            expired = await run_session_expiry_once()
            # 若本轮打满批次，缩短间隔尽快扫完积压
            if expired >= 200:
                wait = 5
            else:
                wait = interval
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("闲置会话过期扫描失败")
            wait = interval

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait)
            break
        except asyncio.TimeoutError:
            continue

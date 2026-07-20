"""问答历史保留服务：7 天物理删除、每个身份最多保留最近 20 轮。

这里的“身份”同时覆盖注册用户与访客：
- 注册用户按 ``qa_sessions.user_id`` 聚合；
- 访客按 ``qa_sessions.guest_id`` 聚合；
- 一轮对话按当前数据模型中的 user + assistant 两条消息计算。

删除消息后会清空相关会话摘要与 Redis 热缓存，避免已经删除的内容仍被后续问答读取。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.memory.session_store import session_store
from app.models.base import utcnow
from app.models.qa import QAMessage, QASession

logger = logging.getLogger(__name__)


@dataclass
class HistoryRetentionResult:
    """一次保留策略执行结果，便于测试、日志和流水线判断是否需要重建缓存。"""

    deleted_messages: int = 0
    deleted_sessions: int = 0
    affected_session_ids: set[uuid.UUID] = field(default_factory=set)


def _identity_filter(
    user_id: uuid.UUID | None,
    guest_id: str | None,
) -> tuple[object, ...]:
    """构造单个注册用户或访客的 SQL 过滤条件。"""
    if user_id is not None:
        return (QASession.user_id == user_id,)
    if guest_id:
        return (
            QASession.user_id.is_(None),
            QASession.guest_id == guest_id,
        )
    return ()


async def enforce_history_retention(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    guest_id: str | None = None,
    batch_size: int = 500,
    commit: bool = True,
) -> HistoryRetentionResult:
    """执行历史物理删除与轮次裁剪。

    传入 user_id 或 guest_id 时只处理该身份，适合每轮问答持久化后立即执行；
    两者都不传时扫描所有身份，供后台周期任务使用。
    """
    retention_days = max(1, int(settings.QA_HISTORY_RETENTION_DAYS))
    max_turns = max(1, int(settings.QA_HISTORY_MAX_TURNS))
    max_messages = max_turns * 2
    cutoff = utcnow() - timedelta(days=retention_days)
    scope = _identity_filter(user_id, guest_id)
    result = HistoryRetentionResult()

    # 第一阶段：会话最后活跃时间已超过 7 天时整会话物理删除，依赖外键级联清理消息。
    expired_sessions = list(
        (
            await db.scalars(
                select(QASession)
                .where(QASession.last_active_at < cutoff, *scope)
                .order_by(QASession.last_active_at.asc())
                .limit(batch_size)
            )
        ).all()
    )
    removed_session_ids = {session.id for session in expired_sessions}
    for session in expired_sessions:
        try:
            await session_store.delete_session_cache(session.id, guest_id=session.guest_id)
        except Exception:
            logger.warning("清理超期历史缓存失败 session_id=%s", session.id, exc_info=True)
        await db.delete(session)
    result.deleted_sessions += len(expired_sessions)

    # 第二阶段：活跃会话内也可能混有超过 7 天的旧轮次，逐条物理删除。
    stale_messages = list(
        (
            await db.scalars(
                select(QAMessage)
                .join(QASession, QASession.id == QAMessage.session_id)
                .where(
                    QAMessage.created_at < cutoff,
                    QASession.id.notin_(removed_session_ids) if removed_session_ids else True,
                    *scope,
                )
                .order_by(QAMessage.created_at.asc())
                .limit(batch_size)
            )
        ).all()
    )
    for message in stale_messages:
        result.affected_session_ids.add(message.session_id)
        await db.delete(message)
    result.deleted_messages += len(stale_messages)
    await db.flush()

    # 第三阶段：按身份跨会话裁剪，只保留时间最新的 20 轮（正常结构下即 40 条消息）。
    if scope:
        identities = [(user_id, guest_id)]
    else:
        identities = list(
            (
                await db.execute(
                    select(QASession.user_id, QASession.guest_id)
                    .where(QASession.status != "deleted")
                    .distinct()
                    .limit(batch_size)
                )
            ).all()
        )

    for identity_user_id, identity_guest_id in identities:
        identity_scope = _identity_filter(identity_user_id, identity_guest_id)
        if not identity_scope:
            # 不完整的匿名会话没有稳定身份，仍由 7 天规则清理，但不与其他匿名会话混合裁剪。
            continue
        messages = list(
            (
                await db.scalars(
                    select(QAMessage)
                    .join(QASession, QASession.id == QAMessage.session_id)
                    .where(
                        QASession.status != "deleted",
                        *identity_scope,
                    )
                    .order_by(QAMessage.created_at.desc(), QAMessage.id.desc())
                    .limit(max_messages + batch_size)
                )
            ).all()
        )
        overflow = messages[max_messages:]
        for message in overflow:
            result.affected_session_ids.add(message.session_id)
            await db.delete(message)
        result.deleted_messages += len(overflow)

    if result.affected_session_ids:
        await db.flush()
        affected_sessions = list(
            (await db.scalars(select(QASession).where(QASession.id.in_(result.affected_session_ids)))).all()
        )
        for session in affected_sessions:
            # 摘要可能包含刚删除的旧消息，因此必须同步清空，不能只更新 message_count。
            session.summary = None
            session.message_count = int(
                await db.scalar(select(func.count()).select_from(QAMessage).where(QAMessage.session_id == session.id))
                or 0
            )
            try:
                await session_store.delete_session_cache(session.id, guest_id=session.guest_id)
            except Exception:
                logger.warning("清理裁剪历史缓存失败 session_id=%s", session.id, exc_info=True)

        # 删除已无消息的空会话，避免历史列表残留空壳。
        empty_sessions = [session for session in affected_sessions if session.message_count == 0]
        for session in empty_sessions:
            await db.delete(session)
            result.deleted_sessions += 1
            result.affected_session_ids.discard(session.id)

    if commit:
        await db.commit()
    else:
        await db.flush()
    return result


async def run_history_retention_once() -> HistoryRetentionResult:
    """使用独立数据库会话执行一轮后台历史清理。"""
    async with SessionLocal() as db:
        return await enforce_history_retention(db)


async def history_retention_loop(stop_event: asyncio.Event) -> None:
    """后台周期任务：按配置间隔持续执行 7 天/20 轮保留策略。"""
    interval = max(60, int(settings.QA_HISTORY_RETENTION_SWEEP_SECONDS))
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=min(20, interval))
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            result = await run_history_retention_once()
            if result.deleted_messages or result.deleted_sessions:
                logger.info(
                    "问答历史保留清理完成 deleted_messages=%s deleted_sessions=%s",
                    result.deleted_messages,
                    result.deleted_sessions,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("问答历史保留扫描失败")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            continue

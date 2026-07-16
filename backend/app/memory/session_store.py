"""Redis 会话热状态管理：短期上下文、摘要缓存、TTL 与访客映射。

Redis Key 约定：
- qa:session:{session_id}:context   — 最近 N 轮对话 JSON 数组
- qa:session:{session_id}:summary   — 长期摘要文本（与 PG qa_sessions.summary 同步）
- qa:session:{session_id}:meta      — 归属信息 {user_id, guest_id}，用于隔离校验
- qa:guest:{guest_id}               — 访客当前 session_id

TTL：
- 注册用户会话：QA_SESSION_TTL_MINUTES
- 访客会话：QA_GUEST_SESSION_TTL_MINUTES
每次读写续期，闲置超时后 Redis 键自动过期；访客映射同步失效。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import get_redis_client
from app.memory.models import ContextMessage, SessionMemory
from app.memory.summarizer import conversation_summarizer
from app.models.qa import QASession

logger = logging.getLogger(__name__)


class SessionAccessError(Exception):
    """会话归属校验失败（跨用户/跨访客读取）。"""


class SessionStore:
    """会话记忆 Redis 读写门面。"""

    def _context_key(self, session_id: str | uuid.UUID) -> str:
        return f"qa:session:{session_id}:context"

    def _summary_key(self, session_id: str | uuid.UUID) -> str:
        return f"qa:session:{session_id}:summary"

    def _meta_key(self, session_id: str | uuid.UUID) -> str:
        return f"qa:session:{session_id}:meta"

    def _guest_key(self, guest_id: str) -> str:
        return f"qa:guest:{guest_id}"

    def _ttl_seconds(self, *, is_guest: bool) -> int:
        minutes = (
            settings.QA_GUEST_SESSION_TTL_MINUTES
            if is_guest
            else settings.QA_SESSION_TTL_MINUTES
        )
        return max(60, int(minutes) * 60)

    @property
    def max_messages(self) -> int:
        """上下文窗口对应的最大消息条数（每轮 user+assistant 共 2 条）。"""
        return max(2, settings.QA_CONTEXT_WINDOW * 2)

    async def bind_session_owner(
        self,
        session_id: uuid.UUID,
        *,
        user_id: Optional[uuid.UUID] = None,
        guest_id: Optional[str] = None,
    ) -> None:
        """写入会话归属元数据，供后续请求校验隔离。"""
        redis = get_redis_client()
        meta = {
            "user_id": str(user_id) if user_id else None,
            "guest_id": guest_id,
        }
        is_guest = guest_id is not None and user_id is None
        ttl = self._ttl_seconds(is_guest=is_guest)
        sid = str(session_id)
        await redis.set(self._meta_key(sid), json.dumps(meta, ensure_ascii=False), ex=ttl)
        if guest_id:
            await redis.set(self._guest_key(guest_id), sid, ex=ttl)

    async def get_guest_session_id(self, guest_id: str) -> Optional[str]:
        """获取访客当前绑定的 session_id。"""
        redis = get_redis_client()
        value = await redis.get(self._guest_key(guest_id))
        return value or None

    async def assert_session_access(
        self,
        session_id: uuid.UUID,
        *,
        user_id: Optional[uuid.UUID] = None,
        guest_id: Optional[str] = None,
    ) -> None:
        """
        校验当前身份有权访问该会话。

        规则：
        - 注册用户：meta.user_id 必须匹配
        - 访客：meta.guest_id 必须匹配
        - meta 不存在时（Redis 过期但 PG 仍有记录）由上层 PG 再校验
        """
        redis = get_redis_client()
        raw = await redis.get(self._meta_key(session_id))
        if not raw:
            return
        meta = json.loads(raw)
        if user_id is not None:
            if meta.get("user_id") != str(user_id):
                raise SessionAccessError("无权访问该会话")
            return
        if guest_id is not None:
            if meta.get("guest_id") != guest_id:
                raise SessionAccessError("无权访问该访客会话")
            return
        raise SessionAccessError("缺少身份标识，无法访问会话")

    async def load_memory(
        self,
        session_id: uuid.UUID,
        *,
        pg_summary: Optional[str] = None,
    ) -> SessionMemory:
        """从 Redis 加载热记忆；摘要优先 Redis，缺失时回退 PG 字段。"""
        redis = get_redis_client()
        sid = str(session_id)

        context_raw = await redis.get(self._context_key(sid))
        summary_raw = await redis.get(self._summary_key(sid))
        meta_raw = await redis.get(self._meta_key(sid))

        messages: list[ContextMessage] = []
        if context_raw:
            try:
                items = json.loads(context_raw)
                messages = [ContextMessage.from_dict(x) for x in items if isinstance(x, dict)]
            except json.JSONDecodeError:
                logger.warning("会话 %s context JSON 损坏，已忽略", sid)

        summary = summary_raw or pg_summary
        user_id = guest_id = None
        if meta_raw:
            meta = json.loads(meta_raw)
            user_id = meta.get("user_id")
            guest_id = meta.get("guest_id")

        return SessionMemory(
            session_id=sid,
            summary=summary,
            messages=messages,
            user_id=user_id,
            guest_id=guest_id,
        )

    async def save_summary(
        self,
        session_id: uuid.UUID,
        summary: str,
        *,
        is_guest: bool = False,
    ) -> None:
        """写入 Redis 摘要缓存并续期。"""
        redis = get_redis_client()
        sid = str(session_id)
        ttl = self._ttl_seconds(is_guest=is_guest)
        await redis.set(self._summary_key(sid), summary, ex=ttl)
        await self._refresh_ttl(sid, is_guest=is_guest, guest_id=None)

    async def append_turn(
        self,
        session_id: uuid.UUID,
        *,
        user_message: ContextMessage,
        assistant_message: ContextMessage,
        is_guest: bool = False,
        db: Optional[AsyncSession] = None,
        pg_session: Optional[QASession] = None,
    ) -> SessionMemory:
        """
        追加一轮对话到热上下文，并在超窗时触发摘要压缩。

        流程：
        1. 读取现有 context + summary
        2. 追加 user/assistant 两条消息
        3. 若超出 QA_CONTEXT_WINDOW，将溢出部分压缩进 summary
        4. 写回 Redis；若提供 db，同步 summary 至 PG
        """
        redis = get_redis_client()
        sid = str(session_id)
        ttl = self._ttl_seconds(is_guest=is_guest)

        memory = await self.load_memory(
            session_id,
            pg_summary=pg_session.summary if pg_session else None,
        )
        memory.messages.extend([user_message, assistant_message])

        overflow: list[ContextMessage] = []
        max_msgs = self.max_messages
        if len(memory.messages) > max_msgs:
            overflow = memory.messages[: len(memory.messages) - max_msgs]
            memory.messages = memory.messages[-max_msgs:]

        if overflow:
            try:
                new_summary = await conversation_summarizer.summarize(
                    existing_summary=memory.summary,
                    messages=overflow,
                )
                memory.summary = new_summary
                await redis.set(self._summary_key(sid), new_summary, ex=ttl)
                if db and pg_session is not None:
                    pg_session.summary = new_summary
            except Exception as exc:
                logger.error("会话 %s 摘要压缩失败，保留截断上下文：%s", sid, exc)

        await redis.set(
            self._context_key(sid),
            json.dumps([m.to_dict() for m in memory.messages], ensure_ascii=False),
            ex=ttl,
        )
        await self._refresh_ttl(sid, is_guest=is_guest, guest_id=memory.guest_id)
        return memory

    async def replace_context(
        self,
        session_id: uuid.UUID,
        messages: list[ContextMessage],
        *,
        is_guest: bool = False,
    ) -> None:
        """全量覆盖热上下文（从 PG 恢复 Redis 时使用）。"""
        redis = get_redis_client()
        sid = str(session_id)
        trimmed = messages[-self.max_messages :]
        ttl = self._ttl_seconds(is_guest=is_guest)
        await redis.set(
            self._context_key(sid),
            json.dumps([m.to_dict() for m in trimmed], ensure_ascii=False),
            ex=ttl,
        )
        await self._refresh_ttl(sid, is_guest=is_guest, guest_id=None)

    async def delete_session_cache(self, session_id: uuid.UUID, *, guest_id: Optional[str] = None) -> None:
        """删除会话全部 Redis 键（用户删除会话或访客过期清理）。"""
        redis = get_redis_client()
        sid = str(session_id)
        await redis.delete(
            self._context_key(sid),
            self._summary_key(sid),
            self._meta_key(sid),
        )
        if guest_id:
            await redis.delete(self._guest_key(guest_id))

    async def _refresh_ttl(
        self,
        session_id: str,
        *,
        is_guest: bool,
        guest_id: Optional[str],
    ) -> None:
        """续期 context/summary/meta（及访客映射）TTL。"""
        redis = get_redis_client()
        ttl = self._ttl_seconds(is_guest=is_guest)
        for key in (self._context_key(session_id), self._summary_key(session_id), self._meta_key(session_id)):
            await redis.expire(key, ttl)
        if guest_id:
            await redis.expire(self._guest_key(guest_id), ttl)

    async def touch(self, session_id: uuid.UUID, *, is_guest: bool = False, guest_id: Optional[str] = None) -> None:
        """请求开始时续期，防止活跃会话被误过期。"""
        await self._refresh_ttl(str(session_id), is_guest=is_guest, guest_id=guest_id)


session_store = SessionStore()

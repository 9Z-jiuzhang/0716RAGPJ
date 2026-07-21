"""LLM Guard 阻拦事件模型，只保存脱敏摘要与指纹。"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GuardBlockedEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """被规则或 LLM 意图分类器阻拦的恶意访问审计记录。"""

    __tablename__ = "guard_blocked_events"
    __table_args__ = (Index("ix_guard_blocked_events_created_intent", "created_at", "intent"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="注册用户 ID；访客为空",
    )
    guest_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="访客",
        server_default="访客",
        comment="攻击账号快照：注册用户名为 username，否则为「访客」",
    )
    client_ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="攻击来源 IP（优先 X-Forwarded-For）",
    )
    intent: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="识别出的意图分类")
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True, comment="稳定阻拦原因码")
    detector: Mapped[str] = mapped_column(String(20), nullable=False, comment="rule 或 llm")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    question_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="问题文本 SHA-256 指纹，不可还原原文",
    )
    question_preview: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        comment="已遮蔽疑似密钥、令牌和密码的短摘要",
    )

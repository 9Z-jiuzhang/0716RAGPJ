"""智能问答会话与消息 ORM 模型（产品手册 5.6）。

设计要点：
- 注册用户通过 user_id 绑定会话，可跨设备查看历史；
- 访客通过 guest_id（匿名临时标识）绑定当前会话，过期后清理；
- 长期摘要 summary 存于会话表，短期上下文由 Redis 热缓存维护；
- 消息表持久化问答内容、引用片段与检索元数据，供历史回看与可观测分析。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class QASession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """问答会话表：用户/访客维度的多轮对话容器。"""

    __tablename__ = "qa_sessions"
    __table_args__ = (
        # 必须归属注册用户或访客之一，禁止无主会话
        CheckConstraint(
            "user_id IS NOT NULL OR guest_id IS NOT NULL",
            name="ck_qa_sessions_owner",
        ),
        Index("ix_qa_sessions_user_last_active", "user_id", "last_active_at"),
        Index("ix_qa_sessions_guest_last_active", "guest_id", "last_active_at"),
        {"comment": "智能问答会话"},
    )

    # 注册用户 ID；访客会话时为空
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="注册用户 ID，访客会话为空",
    )
    # 访客匿名临时标识（前端生成或服务端下发）
    guest_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="访客匿名标识，注册用户会话为空",
    )
    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="新会话",
        comment="会话标题，可由首问自动生成或用户重命名",
    )
    # 超过上下文窗口后由摘要模块压缩写入，随请求注入 LLM 提示
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="长期记忆摘要（超窗历史压缩结果）",
    )
    # active=进行中 / expired=闲置过期 / deleted=用户删除（软删标记）
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True,
        comment="会话状态: active/expired/deleted",
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        index=True,
        comment="最后活跃时间，用于闲置过期判断",
    )
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="消息条数（含 user/assistant）",
    )
    # 该会话曾限定检索的知识库 ID 列表，便于列表页展示 kb_names
    kb_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=True,
        comment="会话关联的知识库 ID 列表",
    )

    messages: Mapped[list[QAMessage]] = relationship(
        "QAMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="noload",
        order_by="QAMessage.created_at",
    )


class QAMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """问答消息表：单轮 user/assistant 消息及检索溯源信息。"""

    __tablename__ = "qa_messages"
    __table_args__ = (
        Index("ix_qa_messages_session_created", "session_id", "created_at"),
        {"comment": "智能问答消息"},
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("qa_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属会话 ID",
    )
    # user / assistant / system
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="消息角色: user/assistant/system",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="消息正文",
    )
    # 引用列表结构对齐 CitationResponse：doc_id/doc_name/chunk_index/content/score
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="回答引用来源片段列表",
    )
    # 检索策略、命中数、各阶段耗时、改写后的查询等可观测字段
    retrieval_meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="检索与生成元数据（strategy/scores/latency 等）",
    )
    token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="大致 token 消耗（可选）",
    )
    request_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="请求追踪 ID，与日志/SSE done 事件对齐",
    )
    strategy: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="本轮实际使用的检索策略: vector/fulltext/hybrid",
    )
    latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="本轮端到端耗时（毫秒）",
    )

    session: Mapped[QASession] = relationship("QASession", back_populates="messages")

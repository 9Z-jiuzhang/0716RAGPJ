"""问答事件与反馈事实表（R6 骨架）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class QARequestEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """单次问答请求的可追溯事件，写入失败不得阻塞用户问答。"""

    __tablename__ = "qa_request_events"
    __table_args__ = (
        Index("ix_qa_request_events_request_id", "request_id"),
        Index("ix_qa_request_events_conversation_id", "conversation_id"),
        Index("ix_qa_request_events_created_at", "created_at"),
        Index("ix_qa_request_events_route_intent", "route_intent"),
        {"comment": "问答请求事件"},
    )

    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    role_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    question_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_preview: Mapped[str | None] = mapped_column(String(240), nullable=True)
    route_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    should_retrieve: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    top_k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rewrite_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cache_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cache_hit_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    miss_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retrieval_hit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class QAFeedbackEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """点赞/点踩事实；同一消息与操作者唯一，重复提交 Upsert。"""

    __tablename__ = "qa_feedback_events"
    __table_args__ = (
        UniqueConstraint("message_id", "actor_hash", name="uq_qa_feedback_message_actor"),
        Index("ix_qa_feedback_events_rating", "rating"),
        {"comment": "问答反馈"},
    )

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    actor_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class QATopicCluster(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """问题主题簇（分析用）。"""

    __tablename__ = "qa_topic_clusters"
    __table_args__ = ({"comment": "问答主题簇"},)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    representative_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cluster_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")


class ModelConfigVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """已发布的不可变模型配置版本。"""

    __tablename__ = "model_config_versions"
    __table_args__ = (
        Index("ix_model_config_versions_model_id", "model_id"),
        {"comment": "模型配置发布版本"},
    )

    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=utcnow)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

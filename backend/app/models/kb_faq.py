"""知识库级 FAQ 缓存模型。

主缓存按知识库隔离：同一 kb + 标准化问题唯一；命中时须再次校验用户授权范围。
向量语义命中为二期能力，本表不依赖 pgvector。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class KBCachedFAQ(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """知识库 FAQ 主表：文档自动生成 / 迁移 / 人工维护。"""

    __tablename__ = "kb_cached_faqs"
    __table_args__ = (
        UniqueConstraint("kb_id", "normalized_question", name="uk_kb_faq_unique"),
        Index("idx_kb_faqs_tenant", "tenant_id"),
        Index("idx_kb_faqs_kb", "kb_id"),
        Index("idx_kb_faqs_status", "status"),
        Index("idx_kb_faqs_normalized", "normalized_question"),
        Index("idx_kb_faqs_active", "is_active", "status"),
        Index("idx_kb_faqs_daily", "kb_id", "created_at"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="default",
        comment="租户标识（当前默认 default）",
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属知识库",
    )
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="展示用问题")
    normalized_question: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="与角色缓存一致的精确匹配键",
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="缓存答案")
    source_document_ids: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
        comment="来源文档 ID 列表",
    )
    chunk_ids: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
        comment="来源分块 ID 列表",
    )
    citations: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
        comment="生成时固化的引用片段",
    )
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="active/disabled/pending_review",
    )
    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="document_auto",
        comment="document_auto/migrated/manual/refined",
    )
    stale_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reject_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sensitivity_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="normal",
        server_default="normal",
        comment="敏感等级 normal/confidential/restricted",
    )
    is_compound: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否疑似一题多问（复合题）",
    )
    split_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="拆分来源父 FAQ id；子条指向父条",
    )
    # 二期语义命中预留：存 JSON 数组或省略；不依赖 VECTOR 类型
    embedding: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)


class FAQAuditLog(Base, UUIDPrimaryKeyMixin):
    """FAQ 管理与命中相关审计。"""

    __tablename__ = "faq_audit_log"
    __table_args__ = (
        Index("idx_faq_audit_tenant", "tenant_id"),
        Index("idx_faq_audit_target", "target_id"),
        Index("idx_faq_audit_time", "created_at"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_ids: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

"""按角色隔离的缓存知识库模型。

角色缓存是独立于文档向量库的精确问答缓存：命中规范化后的相同问题时直接返回已审核来源的答案，
从而跳过 Query 预处理、Embedding、Rerank 与回答生成调用。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RoleCacheConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """每个角色唯一的缓存知识库及其周期配置。"""

    __tablename__ = "role_cache_configs"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
        comment="缓存所属角色 ID",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="缓存知识库显示名称")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否参与缓存命中与周期分析")
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, comment="文档与历史分析周期（天）")
    document_question_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
        comment="每轮从文档生成的缓存问题数量",
    )
    history_question_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        comment="每轮从历史补充的高频问题数量",
    )
    last_document_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次文档分析完成时间",
    )
    last_history_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次历史高频分析完成时间",
    )

    questions: Mapped[list[RoleCachedQuestion]] = relationship(
        "RoleCachedQuestion",
        back_populates="cache",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class RoleCachedQuestion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """缓存问题、答案及来源权限范围。"""

    __tablename__ = "role_cached_questions"
    __table_args__ = (
        UniqueConstraint("role_id", "normalized_question", name="uq_role_cache_normalized_question"),
        Index("ix_role_cached_questions_lookup", "role_id", "normalized_question"),
    )

    cache_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("role_cache_configs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="面向用户展示的原始缓存问题")
    normalized_question: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="Unicode 规范化后的精确匹配键",
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="缓存答案")
    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="来源: document_generated/history_frequent",
    )
    source_kb_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        default=list,
        comment="答案来源知识库范围，命中时必须再次校验用户权限",
    )
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="生成答案所依据的文档片段",
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="历史问题出现次数")
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="缓存命中次数")
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cache: Mapped[RoleCacheConfig] = relationship("RoleCacheConfig", back_populates="questions")

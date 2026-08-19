"""快照模型（产品手册 5.8）。

快照包含知识库元数据、文档版本引用、分段规则、权限配置与 FAQ；
向量数据不直接存入快照，回退时通过元数据重建索引。
"""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase


class Snapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """知识库快照主表。"""

    __tablename__ = "snapshots"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id"),
        index=True,
        nullable=False,
        comment="所属知识库",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="快照名称")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="快照说明")
    trigger: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="触发方式: auto_*/manual/rollback_protection",
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, comment="active/deleted")
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="快照时的知识库元信息、分段规则、权限等"
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, comment="创建人"
    )
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segment_rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase", back_populates="snapshots")
    documents: Mapped[list["SnapshotDocument"]] = relationship(
        "SnapshotDocument",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        # 异步下避免隐式 selectin；需要时用 selectinload / refresh
        lazy="noload",
    )
    faqs: Mapped[list["SnapshotFAQ"]] = relationship(
        "SnapshotFAQ",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class SnapshotDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """快照-文档关联：记录快照时刻的文档状态（文档可能已被删除，故不做外键约束）。"""

    __tablename__ = "snapshot_documents"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="快照时的原始文档 ID（非外键）"
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件名")
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="文件类型")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="分段数")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="内容哈希")
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False, comment="快照时的文档元信息"
    )

    snapshot: Mapped[Snapshot] = relationship("Snapshot", back_populates="documents")


class SnapshotFAQ(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """快照-FAQ：记录快照时刻的 FAQ 全量副本，供回退还原。"""

    __tablename__ = "snapshot_faqs"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    faq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="原始 kb_cached_faqs.id（非外键）"
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(String(1000), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    chunk_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    citations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="document_auto")
    stale_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reject_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sensitivity_level: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    is_compound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    split_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_created_at: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="原 FAQ created_at ISO")
    source_updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="原 FAQ updated_at ISO")

    snapshot: Mapped[Snapshot] = relationship("Snapshot", back_populates="faqs")

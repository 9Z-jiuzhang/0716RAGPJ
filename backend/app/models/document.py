"""文档、分段与知识库分段规则模型。【对齐手册 §5.5 + 快照模块已有结构】"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase

DEFAULT_SEPARATORS = ["\n\n", "\n", "。", ".", " "]
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_SPLIT_MODE = "fixed"


def _default_segment_rules() -> dict[str, Any]:
    return {
        "chunk_size": DEFAULT_CHUNK_SIZE,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "separators": list(DEFAULT_SEPARATORS),
        "split_mode": DEFAULT_SPLIT_MODE,
        # P2迭代开发，当前仅配置存储，不启用语义切分
        "enable_semantic": False,
    }


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """文档表 documents。"""

    __tablename__ = "documents"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False, comment="原始文件名")
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="文件类型")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="文件大小（字节）")
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="MinIO 对象路径")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="分段数量")
    status: Mapped[str] = mapped_column(String(20), default="uploaded", nullable=False, index=True, comment="处理状态")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="内容哈希，用于快照差异对比")
    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # 5.5 流水线内部字段（不进入 DocumentResponse）
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析原文")
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="规范化文本")
    segment_rules: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=_default_segment_rules, comment="文档级分段规则"
    )
    index_version: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="当前索引版本标记")

    knowledge_base: Mapped[KnowledgeBase] = relationship("KnowledgeBase", back_populates="documents")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """文档分段表 document_chunks。"""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="分段序号，从 0 开始")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="分段文本")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="字符数")
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False, comment="标题层级、页码等元信息"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否参与检索")

    document: Mapped[Document] = relationship("Document", back_populates="chunks")


class KbChunkRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """知识库默认分段规则表 kb_chunk_rule。【对齐手册 §5.5.5】"""

    __tablename__ = "kb_chunk_rule"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=DEFAULT_CHUNK_SIZE)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=DEFAULT_CHUNK_OVERLAP)
    separators: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=lambda: list(DEFAULT_SEPARATORS))
    split_mode: Mapped[str] = mapped_column(String(32), nullable=False, default=DEFAULT_SPLIT_MODE)
    # P2迭代开发，当前仅配置存储，不启用语义切分
    enable_semantic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

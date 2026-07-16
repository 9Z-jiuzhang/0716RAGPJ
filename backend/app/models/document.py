"""文档与分段模型。"""

import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """文档表。"""

    __tablename__ = "documents"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False, comment="原始文件名")
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="文件类型")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="文件大小（字节）")
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="MinIO 对象路径")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="分段数量")
    status: Mapped[str] = mapped_column(String(20), default="uploaded", nullable=False, comment="处理状态")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="失败原因")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="内容哈希，用于快照差异对比")
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase", back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan", lazy="noload"
    )


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """文档分段表。"""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), index=True, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="分段序号，从 0 开始")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="分段文本")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="字符数")
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False, comment="标题层级、页码等元信息"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否参与检索")

    document: Mapped[Document] = relationship("Document", back_populates="chunks")
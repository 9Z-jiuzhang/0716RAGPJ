"""知识库与权限模型。"""
import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class KnowledgeBase(TimestampMixin, Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    vector_store_type: Mapped[str] = mapped_column(String(50), default="chroma")
    embeddings_model: Mapped[str | None] = mapped_column(String(200))


class KBPermission(Base):
    __tablename__ = "kb_permissions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    role_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"))
    permission_code: Mapped[str] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("kb_id", "user_id", "role_id", "permission_code"),
    )
"""知识库与知识库权限模型。"""

import uuid
from typing import TYPE_CHECKING, Optional

from datetime import datetime as datetime_type
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.snapshot import Snapshot


class KnowledgeBase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """知识库表：隔离边界与元数据。"""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True, comment="知识库名称")
    type: Mapped[str] = mapped_column(String(50), nullable=False, comment="类型: technical_doc/product_manual/faq/general")
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}", comment="标签列表"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="描述")
    visibility: Mapped[str] = mapped_column(String(20), default="restricted", nullable=False, comment="可见性")
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False, comment="嵌入模型标识")
    chunk_size: Mapped[int] = mapped_column(Integer, default=500, nullable=False, comment="默认分段大小")
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50, nullable=False, comment="分段重叠字符数")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, comment="状态")
    current_index_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="当前生效索引版本号")
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[Optional[datetime_type]] = mapped_column(DateTime, nullable=True)

    documents: Mapped[list["Document"]] = relationship("Document", back_populates="knowledge_base", lazy="selectin")
    snapshots: Mapped[list["Snapshot"]] = relationship("Snapshot", back_populates="knowledge_base", lazy="noload")
    index_versions = relationship("IndexVersion", back_populates="knowledge_base", cascade="all, delete-orphan")
    permissions: Mapped[list["KBPermission"]] = relationship(
        "KBPermission", back_populates="knowledge_base", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("name", "deleted_at", name="uq_kb_name_deleted"),
    )


class KBPermission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """知识库级权限授予（用户或角色）。"""

    __tablename__ = "kb_permissions"
    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR role_id IS NOT NULL",
            name="ck_kb_permissions_user_or_role",
        ),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, comment="用户级授权"
    )
    role_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True, comment="角色级授权"
    )
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False, comment="权限标识")

    knowledge_base: Mapped[KnowledgeBase] = relationship("KnowledgeBase", back_populates="permissions")
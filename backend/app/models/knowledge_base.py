"""知识库与知识库权限模型。"""

from __future__ import annotations

import uuid
from datetime import datetime as datetime_type
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.snapshot import Snapshot


class KnowledgeBase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """知识库表：隔离边界与元数据。"""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True, comment="知识库名称")
    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="类型: technical_doc/product_manual/faq/general",
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}", comment="标签列表")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述")
    visibility: Mapped[str] = mapped_column(String(20), default="restricted", nullable=False, comment="可见性")
    # 兼容字段：多部门关联的权威来源为 kb_departments；本列同步为首选部门（含 GUEST 优先）
    department: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="首选部门编码（兼容旧逻辑；完整列表见 kb_departments）"
    )
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False, comment="嵌入模型标识")
    chunk_size: Mapped[int] = mapped_column(Integer, default=500, nullable=False, comment="默认分段大小")
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50, nullable=False, comment="分段重叠字符数")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, comment="状态")
    faq_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="是否启用该知识库 FAQ 命中与热门列表",
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否置顶（列表优先展示）",
    )
    pinned_at: Mapped[datetime_type | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近置顶时间（同档内按此倒序）",
    )
    default_sensitivity_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="normal",
        server_default="normal",
        comment="库默认敏感等级 normal/confidential/restricted",
    )
    current_index_version: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="当前生效索引版本号")
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime_type | None] = mapped_column(DateTime, nullable=True)

    documents: Mapped[list[Document]] = relationship("Document", back_populates="knowledge_base", lazy="noload")
    snapshots: Mapped[list[Snapshot]] = relationship("Snapshot", back_populates="knowledge_base", lazy="noload")
    index_versions = relationship(
        "IndexVersion",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    permissions: Mapped[list[KBPermission]] = relationship(
        "KBPermission",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    department_links: Mapped[list[KBDepartment]] = relationship(
        "KBDepartment",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    __table_args__ = (
        UniqueConstraint("name", "deleted_at", name="uq_kb_name_deleted"),
        CheckConstraint(
            "default_sensitivity_level IN ('normal', 'confidential', 'restricted')",
            name="ck_kb_default_sensitivity_level",
        ),
    )


class KBDepartment(Base, UUIDPrimaryKeyMixin):
    """知识库 ↔ 部门多对多关联（按部门 code）。"""

    __tablename__ = "kb_departments"
    __table_args__ = (UniqueConstraint("kb_id", "department_code", name="uq_kb_departments_kb_code"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    department_code: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="部门编码，如 GUEST / A / B"
    )
    created_at: Mapped[datetime_type] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    knowledge_base: Mapped[KnowledgeBase] = relationship("KnowledgeBase", back_populates="department_links")


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
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, comment="用户级授权"
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True, comment="角色级授权"
    )
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False, comment="权限标识")

    knowledge_base: Mapped[KnowledgeBase] = relationship("KnowledgeBase", back_populates="permissions")

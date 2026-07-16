"""索引版本模型：发布与回退的原子切换载体。"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IndexVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """索引版本表。

    回退时创建新的恢复版本（不覆盖历史），再原子切换 current_index_version。
    """

    __tablename__ = "index_versions"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), index=True, nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False, comment="版本号，如 v20260716-001")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="该版本分段总数")
    status: Mapped[str] = mapped_column(
        String(20), default="building", nullable=False, comment="building/active/obsolete/failed"
    )
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="构建时的分段规则、embedding 模型等配置"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="若由快照回退产生，记录来源快照 ID"
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="index_versions")
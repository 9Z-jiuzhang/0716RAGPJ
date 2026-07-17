from sqlalchemy import UUID, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from uuid import uuid4

from app.core.database import Base


class KBPermission(Base):
    __tablename__ = "kb_permissions"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, index=True
    )
    kb_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    role_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True
    )
    permission: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="permissions")

    __table_args__ = (
        UniqueConstraint(
            "kb_id", "user_id", "permission", name="uq_kb_user_permission"
        ),
        UniqueConstraint(
            "kb_id", "role_id", "permission", name="uq_kb_role_permission"
        ),
    )

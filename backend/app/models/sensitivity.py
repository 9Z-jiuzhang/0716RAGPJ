"""敏感话题密级：角色上限、用户覆盖与审计。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

SENSITIVITY_LEVELS = ("normal", "confidential", "restricted")
LEVEL_ORDER = {"normal": 0, "confidential": 1, "restricted": 2}
SENSITIVITY_LEVEL_META: list[dict[str, Any]] = [
    {"code": "normal", "label": "普通", "order": 0},
    {"code": "confidential", "label": "机密", "order": 1},
    {"code": "restricted", "label": "极高密", "order": 2},
]

# 方案α：映射现网角色；hr 为可选内置角色（机密）
ROLE_SENSITIVITY_MAPPING = {
    "guest": "normal",
    "staff": "normal",
    "hr": "confidential",
    "admin": "confidential",
    "super_admin": "restricted",
}


def normalize_sensitivity_level(level: str | None) -> str:
    text = (level or "normal").strip().lower()
    return text if text in LEVEL_ORDER else "normal"


def levels_at_or_below(max_level: str | None) -> list[str]:
    """用户最高可读密级对应的可访问 code 列表（含自身及以下）。"""
    max_ord = LEVEL_ORDER.get(normalize_sensitivity_level(max_level), 0)
    return [code for code, order in LEVEL_ORDER.items() if order <= max_ord]


def sensitivity_label(level: str | None) -> str:
    code = normalize_sensitivity_level(level)
    for item in SENSITIVITY_LEVEL_META:
        if item["code"] == code:
            return str(item["label"])
    return "普通"


class RoleSensitivityPermission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """角色默认最高可访问密级（可管理端覆盖映射表）。"""

    __tablename__ = "role_sensitivity_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role", name="uk_role_sensitivity_tenant_role"),
        Index("idx_role_sensitivity_tenant", "tenant_id"),
    )

    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    max_sensitivity_level: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")


class UserSensitivityOverride(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """用户密级特例覆盖。"""

    __tablename__ = "user_sensitivity_overrides"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uk_user_sensitivity_tenant_user"),
        Index("idx_user_sensitivity_tenant", "tenant_id"),
    )

    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    max_sensitivity_level: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SensitivityAuditLog(Base, UUIDPrimaryKeyMixin):
    """敏感访问拒绝审计。"""

    __tablename__ = "sensitivity_audit_log"
    __table_args__ = (
        Index("idx_sensitivity_audit_tenant", "tenant_id"),
        Index("idx_sensitivity_audit_time", "created_at"),
    )

    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sensitivity_level: Mapped[str] = mapped_column(String(20), nullable=False, default="confidential")
    action: Mapped[str] = mapped_column(String(64), nullable=False, default="denied")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="faq")
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


def audit_row_dict(row: SensitivityAuditLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "user_id": str(row.user_id) if row.user_id else None,
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "question": row.question,
        "sensitivity_level": row.sensitivity_level,
        "action": row.action,
        "source": row.source,
        "reason": row.reason,
        "detail": getattr(row, "detail", None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

"""审计日志模型（产品手册 5.8.5）。"""

import uuid
from typing import Any, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """操作审计日志：记录操作者、对象、前后版本、请求标识与结果。"""

    __tablename__ = "audit_logs"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, comment="操作者，系统操作为空"
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="动作标识，如 snapshot.create / snapshot.rollback"
    )
    resource_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="资源类型: kb/doc/user/role/snapshot"
    )
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="资源 ID")
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="操作详情，含变更前后对比"
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True, comment="客户端 IP")
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="User-Agent")
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True, comment="请求标识")
    result: Mapped[str] = mapped_column(String(20), default="success", nullable=False, comment="success/failure")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="失败原因")

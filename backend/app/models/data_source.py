"""外部数据源、开放 API 客户端与幂等记录模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class ExternalDataSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """外部只读数据源配置。连接 URL 仅以密文保存。"""

    __tablename__ = "external_data_sources"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    connector_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="relational")
    dialect: Mapped[str | None] = mapped_column(String(64), nullable=True)
    driver: Mapped[str | None] = mapped_column(String(64), nullable=True)
    connection_url_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    connection_url_masked: Mapped[str] = mapped_column(String(500), nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    access_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="enabled", index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ExternalApiClient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """外部系统 API 客户端；关联现有服务账号并复用 RBAC。"""

    __tablename__ = "external_api_clients"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    linked_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    allowed_data_source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    rate_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalApiIdempotencyRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """外部上传幂等记录。"""

    __tablename__ = "external_api_idempotency_records"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("external_api_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

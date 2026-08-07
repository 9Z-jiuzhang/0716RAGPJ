"""外部 API 客户端管理与鉴权。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import _permission_codes, is_super_admin
from app.models import User
from app.models.base import utcnow
from app.models.data_source import ExternalApiClient, ExternalApiIdempotencyRecord, ExternalDataSource
from app.services.api_key_crypto import generate_api_key, hash_api_key, is_expired, verify_api_key
from app.services.observability import write_audit
from app.utils.exceptions import DocumentError

VALID_SCOPES = {"kb:read", "document:read", "document:upload", "data_source:read"}


class ExternalApiError(Exception):
    def __init__(self, message: str, http_status: int = 401):
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def _client_public(client: ExternalApiClient, *, raw_key: str | None = None) -> dict[str, Any]:
    data = {
        "id": str(client.id),
        "name": client.name,
        "key_prefix": client.key_prefix,
        "scopes": client.scopes or [],
        "linked_user_id": str(client.linked_user_id),
        "allowed_data_source_ids": client.allowed_data_source_ids or [],
        "rate_limit": client.rate_limit,
        "expires_at": client.expires_at.isoformat() if client.expires_at else None,
        "is_enabled": client.is_enabled,
        "created_by": str(client.created_by),
        "created_at": client.created_at.isoformat() if client.created_at else None,
        "updated_at": client.updated_at.isoformat() if client.updated_at else None,
        "last_used_at": client.last_used_at.isoformat() if client.last_used_at else None,
    }
    if raw_key:
        data["api_key"] = raw_key
    return data


async def list_clients(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(ExternalApiClient).order_by(ExternalApiClient.created_at.desc()))).all()
    return [_client_public(r) for r in rows]


async def get_client(db: AsyncSession, client_id: uuid.UUID) -> ExternalApiClient:
    client = await db.scalar(select(ExternalApiClient).where(ExternalApiClient.id == client_id))
    if not client:
        raise ExternalApiError("API 客户端不存在", http_status=404)
    return client


async def create_client(
    db: AsyncSession,
    *,
    user: User,
    name: str,
    linked_user_id: uuid.UUID,
    scopes: list[str],
    allowed_data_source_ids: list[str] | None = None,
    rate_limit: int | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ExternalApiError("名称不能为空", http_status=422)
    existing = await db.scalar(select(ExternalApiClient).where(ExternalApiClient.name == name))
    if existing:
        raise ExternalApiError("API 客户端名称已存在", http_status=409)

    linked = await db.scalar(select(User).where(User.id == linked_user_id))
    if not linked or linked.status != "active":
        raise ExternalApiError("关联服务账号不存在或未启用", http_status=422)

    scope_set = set(scopes or [])
    if not scope_set or not scope_set.issubset(VALID_SCOPES):
        raise ExternalApiError(f"Scope 无效，允许值: {sorted(VALID_SCOPES)}", http_status=422)

    allowed = allowed_data_source_ids or []
    for ds_id in allowed:
        try:
            uid = uuid.UUID(ds_id)
        except ValueError as exc:
            raise ExternalApiError("allowed_data_source_ids 含无效 UUID", http_status=422) from exc
        ds = await db.scalar(select(ExternalDataSource).where(ExternalDataSource.id == uid))
        if not ds:
            raise ExternalApiError(f"数据源不存在: {ds_id}", http_status=422)

    raw, prefix, key_hash = generate_api_key()
    client = ExternalApiClient(
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=sorted(scope_set),
        linked_user_id=linked_user_id,
        allowed_data_source_ids=allowed,
        rate_limit=rate_limit or settings.EXTERNAL_API_DEFAULT_RATE_LIMIT,
        expires_at=expires_at,
        is_enabled=True,
        created_by=user.id,
    )
    db.add(client)
    await db.flush()
    await write_audit(
        db,
        user_id=user.id,
        action="external_api_client.create",
        resource_type="external_api_client",
        resource_id=str(client.id),
        detail={"name": name, "key_prefix": prefix, "scopes": client.scopes},
    )
    await db.commit()
    await db.refresh(client)
    return _client_public(client, raw_key=raw)


async def update_client(
    db: AsyncSession,
    *,
    user: User,
    client_id: uuid.UUID,
    name: str | None = None,
    scopes: list[str] | None = None,
    allowed_data_source_ids: list[str] | None = None,
    rate_limit: int | None = None,
    expires_at: datetime | None = None,
    is_enabled: bool | None = None,
    linked_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    client = await get_client(db, client_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise ExternalApiError("名称不能为空", http_status=422)
        clash = await db.scalar(
            select(ExternalApiClient).where(ExternalApiClient.name == name, ExternalApiClient.id != client_id)
        )
        if clash:
            raise ExternalApiError("API 客户端名称已存在", http_status=409)
        client.name = name
    if scopes is not None:
        scope_set = set(scopes)
        if not scope_set.issubset(VALID_SCOPES):
            raise ExternalApiError(f"Scope 无效，允许值: {sorted(VALID_SCOPES)}", http_status=422)
        client.scopes = sorted(scope_set)
    if allowed_data_source_ids is not None:
        client.allowed_data_source_ids = allowed_data_source_ids
    if rate_limit is not None:
        client.rate_limit = max(1, rate_limit)
    if expires_at is not None:
        client.expires_at = expires_at
    if is_enabled is not None:
        client.is_enabled = is_enabled
    if linked_user_id is not None:
        linked = await db.scalar(select(User).where(User.id == linked_user_id))
        if not linked or linked.status != "active":
            raise ExternalApiError("关联服务账号不存在或未启用", http_status=422)
        client.linked_user_id = linked_user_id
    client.updated_at = utcnow()
    await write_audit(
        db,
        user_id=user.id,
        action="external_api_client.update",
        resource_type="external_api_client",
        resource_id=str(client.id),
        detail={"name": client.name, "is_enabled": client.is_enabled},
    )
    await db.commit()
    await db.refresh(client)
    return _client_public(client)


async def rotate_client_key(db: AsyncSession, *, user: User, client_id: uuid.UUID) -> dict[str, Any]:
    client = await get_client(db, client_id)
    raw, prefix, key_hash = generate_api_key()
    client.key_prefix = prefix
    client.key_hash = key_hash
    client.updated_at = utcnow()
    await write_audit(
        db,
        user_id=user.id,
        action="external_api_client.rotate_key",
        resource_type="external_api_client",
        resource_id=str(client.id),
        detail={"key_prefix": prefix},
    )
    await db.commit()
    await db.refresh(client)
    return _client_public(client, raw_key=raw)


async def delete_client(db: AsyncSession, *, user: User, client_id: uuid.UUID) -> None:
    client = await get_client(db, client_id)
    await write_audit(
        db,
        user_id=user.id,
        action="external_api_client.delete",
        resource_type="external_api_client",
        resource_id=str(client.id),
        detail={"name": client.name, "key_prefix": client.key_prefix},
    )
    await db.delete(client)
    await db.commit()


async def authenticate_api_key(db: AsyncSession, raw_key: str | None) -> tuple[ExternalApiClient, User]:
    if not raw_key:
        raise ExternalApiError("缺少 X-API-Key", http_status=401)
    key_hash = hash_api_key(raw_key)
    client = await db.scalar(select(ExternalApiClient).where(ExternalApiClient.key_hash == key_hash))
    if not client or not verify_api_key(raw_key, client.key_hash):
        raise ExternalApiError("API Key 无效", http_status=401)
    if not client.is_enabled:
        raise ExternalApiError("API 客户端已禁用", http_status=401)
    if is_expired(client.expires_at):
        raise ExternalApiError("API Key 已过期", http_status=401)
    user = await db.scalar(select(User).where(User.id == client.linked_user_id))
    if not user or user.status != "active":
        raise ExternalApiError("关联服务账号不可用", http_status=401)
    client.last_used_at = utcnow()
    await db.commit()
    await db.refresh(client)
    await db.refresh(user)
    return client, user


def require_scope(client: ExternalApiClient, scope: str) -> None:
    if scope not in (client.scopes or []):
        raise ExternalApiError("API Client Scope 不足", http_status=403)


def require_user_permission(user: User, permission: str) -> None:
    if is_super_admin(user):
        return
    codes = _permission_codes(user)
    if "*" in codes or "admin:*" in codes or permission in codes:
        return
    raise ExternalApiError("关联用户权限不足", http_status=403)


def assert_data_source_allowed(client: ExternalApiClient, source_id: uuid.UUID) -> None:
    allowed = set(client.allowed_data_source_ids or [])
    if str(source_id) not in allowed:
        raise ExternalApiError("数据源未授权给该 API 客户端", http_status=403)


async def find_idempotency(
    db: AsyncSession,
    *,
    client_id: uuid.UUID,
    kb_id: uuid.UUID,
    idempotency_key: str,
) -> ExternalApiIdempotencyRecord | None:
    return await db.scalar(
        select(ExternalApiIdempotencyRecord).where(
            ExternalApiIdempotencyRecord.client_id == client_id,
            ExternalApiIdempotencyRecord.kb_id == kb_id,
            ExternalApiIdempotencyRecord.idempotency_key == idempotency_key,
        )
    )


async def save_idempotency(
    db: AsyncSession,
    *,
    client_id: uuid.UUID,
    kb_id: uuid.UUID,
    idempotency_key: str,
    content_hash: str,
    document_id: uuid.UUID,
    response_payload: dict[str, Any],
    ttl_hours: int = 24,
) -> None:
    record = ExternalApiIdempotencyRecord(
        client_id=client_id,
        kb_id=kb_id,
        idempotency_key=idempotency_key,
        content_hash=content_hash,
        document_id=document_id,
        response_payload=response_payload,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
    )
    db.add(record)
    await db.commit()

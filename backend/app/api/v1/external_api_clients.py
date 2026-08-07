"""内部管理：外部 API 客户端。"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models import User
from app.schemas.data_source import ApiClientCreateRequest, ApiClientUpdateRequest
from app.schemas.response import ok
from app.services import external_api_service
from app.services.external_api_service import ExternalApiError

router = APIRouter(prefix="/external-api-clients", tags=["外部API客户端"])


def _raise(exc: ExternalApiError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc


def _uuid(value: str, name: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"无效的 {name}") from exc


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="expires_at 格式无效") from exc


@router.get("")
async def list_clients(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("external_api:manage")),
):
    return ok(await external_api_service.list_clients(db))


@router.post("")
async def create_client(
    body: ApiClientCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("external_api:manage")),
):
    try:
        data = await external_api_service.create_client(
            db,
            user=user,
            name=body.name,
            linked_user_id=_uuid(body.linked_user_id, "linked_user_id"),
            scopes=body.scopes,
            allowed_data_source_ids=body.allowed_data_source_ids,
            rate_limit=body.rate_limit,
            expires_at=_parse_dt(body.expires_at),
        )
    except ExternalApiError as exc:
        _raise(exc)
    return ok(data, message="created")


@router.put("/{client_id}")
async def update_client(
    client_id: str,
    body: ApiClientUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("external_api:manage")),
):
    try:
        data = await external_api_service.update_client(
            db,
            user=user,
            client_id=_uuid(client_id, "client_id"),
            name=body.name,
            scopes=body.scopes,
            allowed_data_source_ids=body.allowed_data_source_ids,
            rate_limit=body.rate_limit,
            expires_at=_parse_dt(body.expires_at) if body.expires_at is not None else None,
            is_enabled=body.is_enabled,
            linked_user_id=_uuid(body.linked_user_id, "linked_user_id") if body.linked_user_id else None,
        )
    except ExternalApiError as exc:
        _raise(exc)
    return ok(data, message="updated")


@router.post("/{client_id}/rotate-key")
async def rotate_key(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("external_api:manage")),
):
    try:
        data = await external_api_service.rotate_client_key(
            db, user=user, client_id=_uuid(client_id, "client_id")
        )
    except ExternalApiError as exc:
        _raise(exc)
    return ok(data, message="rotated")


@router.delete("/{client_id}")
async def delete_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("external_api:manage")),
):
    try:
        await external_api_service.delete_client(db, user=user, client_id=_uuid(client_id, "client_id"))
    except ExternalApiError as exc:
        _raise(exc)
    return ok({"deleted": True})

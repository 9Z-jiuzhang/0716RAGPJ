"""大模型管理 API。【对齐手册 §5.9.1】"""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.core.exceptions import APIException
from app.models import User
from app.schemas.common import APIResponse, PageResponse
from app.schemas.model_config import (
    CreateModelConfigRequest,
    ModelConfigResponse,
    ModelStatusRequest,
    SetDefaultRequest,
    UpdateModelConfigRequest,
)
from app.services.model_config import ModelConfigService

router = APIRouter(prefix="/models", tags=["大模型管理"])


def _raise(exc: APIException) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("", response_model=APIResponse[PageResponse[ModelConfigResponse]])
async def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    model_type: str | None = Query(None, pattern="^(llm|embedding|rerank)$"),
    _: User = Depends(require_permission("model:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await ModelConfigService(db).list_models(
            page=page, page_size=page_size, model_type=model_type
        )
    except APIException as exc:
        _raise(exc)
    return APIResponse(data=data)


@router.post("", response_model=APIResponse[ModelConfigResponse], status_code=201)
async def create_model(
    body: CreateModelConfigRequest = Body(...),
    _: User = Depends(require_permission("model:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await ModelConfigService(db).create(body)
    except APIException as exc:
        _raise(exc)
    return APIResponse(data=data)


@router.put("/{model_id}", response_model=APIResponse[ModelConfigResponse])
async def update_model(
    model_id: UUID = Path(...),
    body: UpdateModelConfigRequest = Body(...),
    _: User = Depends(require_permission("model:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await ModelConfigService(db).update(model_id, body)
    except APIException as exc:
        _raise(exc)
    return APIResponse(data=data)


@router.patch("/{model_id}/status", response_model=APIResponse[ModelConfigResponse])
async def patch_model_status(
    model_id: UUID = Path(...),
    body: ModelStatusRequest = Body(...),
    _: User = Depends(require_permission("model:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await ModelConfigService(db).set_status(model_id, body.is_enabled)
    except APIException as exc:
        _raise(exc)
    return APIResponse(data=data)


@router.put("/{model_id}/default", response_model=APIResponse[ModelConfigResponse])
async def set_model_default(
    model_id: UUID = Path(...),
    body: SetDefaultRequest = Body(SetDefaultRequest()),
    _: User = Depends(require_permission("model:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await ModelConfigService(db).set_default(model_id, body.is_default)
    except APIException as exc:
        _raise(exc)
    return APIResponse(data=data)

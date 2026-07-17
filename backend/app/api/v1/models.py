"""大模型管理 API。【对齐手册 §5.9.1】"""

from uuid import UUID

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
from app.services.model_usage import ModelUsageError, fetch_daily_metrics
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/models", tags=["大模型管理"])


def _raise(exc: APIException) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/usage", response_model=APIResponse[dict])
async def get_model_usage(
    days: int = Query(30, ge=1, le=180, description="统计最近天数"),
    model: str | None = Query(None, description="按模型名过滤（Langfuse 中的 model）"),
    _: User = Depends(require_permission("model:read")),
):
    """从 Langfuse 拉取模型用量（token / 调用次数 / 成本），支持按模型筛选。"""
    try:
        data = await fetch_daily_metrics(days=days, model=model)
    except ModelUsageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return APIResponse(data=data)


@router.get("", response_model=APIResponse[PageResponse[ModelConfigResponse]])
async def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    model_type: str | None = Query(None, pattern="^(llm|embedding|rerank)$"),
    _: User = Depends(require_permission("model:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await ModelConfigService(db).list_models(page=page, page_size=page_size, model_type=model_type)
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

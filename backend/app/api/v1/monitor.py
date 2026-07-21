"""系统监控 API：健康检查、统计概览、指标别名。"""

from app.api.helpers import ok, resolve_request_id
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.schemas.common import BaseResponse
from app.services.monitor import MonitorService
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/monitor", tags=["系统监控"])


@router.get("/health", response_model=BaseResponse, summary="系统健康检查")
async def health(request_id: str = Depends(resolve_request_id)) -> BaseResponse:
    """检查 PostgreSQL / Redis / Chroma / Langfuse 连通性。"""
    body = await MonitorService().health()
    return ok(body, request_id=request_id)


@router.get("/stats", response_model=BaseResponse, summary="系统统计概览")
async def stats(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission("system:read")),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    body = await MonitorService(db).stats()
    return ok(body, request_id=request_id)


@router.get("/guard-events", response_model=BaseResponse, summary="LLM Guard 阻拦事件列表")
async def guard_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission("system:read")),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """分页返回阻拦审计：账号、IP、意图与原因码；不含完整问题原文。"""
    body = await MonitorService(db).list_guard_events(page=page, page_size=page_size)
    return ok(body, request_id=request_id)


@router.get("/metrics", include_in_schema=False, summary="Prometheus 指标（别名）")
async def metrics_alias() -> RedirectResponse:
    """手册路径别名，重定向到根路径 /metrics。"""
    return RedirectResponse(url="/metrics", status_code=307)

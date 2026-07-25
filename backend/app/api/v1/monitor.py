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


@router.get("/analytics/feedback", response_model=BaseResponse, summary="问答反馈汇总")
async def analytics_feedback(
    days: int = Query(14, ge=1, le=90, description="趋势窗口天数"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission("system:read")),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """管理端图表数据：反馈计数、路由/缓存分布与近 N 日趋势。"""
    from app.services.analytics_events import analytics_event_service

    body = await analytics_event_service.feedback_summary(db, days=days)
    return ok(body, request_id=request_id)


@router.get("/analytics/topics", response_model=BaseResponse, summary="问答主题簇列表")
async def analytics_topics(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission("system:read")),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """主题聚类列表；全文明细需更高权限时再扩展。"""
    from sqlalchemy import select

    from app.models.analytics import QATopicCluster

    rows = (await db.scalars(select(QATopicCluster).order_by(QATopicCluster.sample_count.desc()).limit(50))).all()
    items = [
        {
            "id": str(r.id),
            "name": r.name,
            "keywords": r.keywords or [],
            "sample_count": r.sample_count,
            "representative_question": r.representative_question,
            "cluster_version": r.cluster_version,
        }
        for r in rows
    ]
    return ok({"items": items, "privacy": "aggregate_only"}, request_id=request_id)


@router.post("/analytics/topics/rebuild", response_model=BaseResponse, summary="重建主题簇")
async def analytics_topics_rebuild(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission("system:read")),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    from app.services.topic_analytics import topic_analytics_service

    created = await topic_analytics_service.rebuild_from_events(db)
    return ok({"created": created, "privacy": "aggregate_only"}, request_id=request_id)


@router.get("/metrics", include_in_schema=False, summary="Prometheus 指标（别名）")
async def metrics_alias() -> RedirectResponse:
    """手册路径别名，重定向到根路径 /metrics。"""
    return RedirectResponse(url="/metrics", status_code=307)

"""审计日志 API（产品手册 5.8.5）。

路由前缀: /audit
权限: audit:read
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models import User
from app.schemas.audit import AuditLogFilterParams, AuditLogListResponse, AuditLogResponse
from app.schemas.common import BaseResponse
from app.services.audit import AuditService

router = APIRouter(prefix="/audit", tags=["审计日志"])


def _request_id(x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")) -> str:
    return x_request_id or str(uuid4())


@router.get(
    "/logs",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="审计日志列表",
    description="分页查询操作审计日志，支持按用户、动作、资源类型、结果与时间筛选。",
)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None, description="操作者"),
    action: Optional[str] = Query(None, description="动作前缀，如 snapshot."),
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    result: Optional[str] = Query(None, description="success / failure"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("audit:read")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    params = AuditLogFilterParams(
        page=page,
        page_size=page_size,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        start_date=start_date,
        end_date=end_date,
    )
    data: AuditLogListResponse = await AuditService(db).list_logs(params)
    return BaseResponse(data=data.model_dump(mode="json"), request_id=request_id)


@router.get(
    "/logs/{log_id}",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="审计日志详情",
    description="查看单条审计记录的完整详情（含变更前后 JSON）。",
)
async def get_audit_log(
    log_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("audit:read")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    data: AuditLogResponse = await AuditService(db).get_detail(log_id)
    return BaseResponse(data=data.model_dump(mode="json"), request_id=request_id)

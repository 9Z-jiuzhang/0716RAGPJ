"""审计服务：供快照及其他写操作横切调用。"""

from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.repositories.audit import AuditRepository
from app.schemas.audit import AuditLogFilterParams, AuditLogListItem, AuditLogListResponse, AuditLogResponse


class AuditService:
    """审计日志业务服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuditRepository(db)

    async def log(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        user_id: Optional[UUID] = None,
        detail: Optional[dict[str, Any]] = None,
        request_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        result: str = "success",
        error_message: Optional[str] = None,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
            result=result,
            error_message=error_message,
        )
        return await self.repo.create(entry)

    async def get_detail(self, log_id: UUID) -> AuditLogResponse:
        log = await self.repo.get_by_id(log_id)
        if log is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="审计日志不存在")
        return AuditLogResponse.model_validate(log)

    async def list_logs(self, params: AuditLogFilterParams) -> AuditLogListResponse:
        items, total = await self.repo.list_filtered(params)
        return AuditLogListResponse(
            items=[AuditLogListItem.model_validate(i) for i in items],
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

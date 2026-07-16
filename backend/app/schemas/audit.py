"""审计日志 Schema（产品手册 5.8.5）。"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import PaginationParams, PaginationResponse


class AuditLogFilterParams(PaginationParams):
    """审计日志筛选参数。"""

    user_id: Optional[UUID] = Field(default=None, description="操作者用户 ID")
    action: Optional[str] = Field(default=None, description="动作标识，支持前缀匹配")
    resource_type: Optional[str] = Field(default=None, description="资源类型")
    resource_id: Optional[str] = Field(default=None, description="资源 ID")
    result: Optional[str] = Field(default=None, description="success / failure")
    start_date: Optional[datetime] = Field(default=None, description="起始时间")
    end_date: Optional[datetime] = Field(default=None, description="结束时间")


class AuditLogListItem(BaseModel):
    """审计日志列表项。"""

    id: UUID
    user_id: Optional[UUID] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    result: str = "success"
    request_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogResponse(AuditLogListItem):
    """完整审计日志。"""

    detail: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    error_message: Optional[str] = None
    updated_at: Optional[datetime] = None


class AuditLogListResponse(PaginationResponse[AuditLogListItem]):
    """审计日志分页列表。"""

    pass

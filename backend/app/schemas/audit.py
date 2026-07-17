"""审计日志 Schema（产品手册 5.8.5）。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.schemas.common import PaginationParams, PaginationResponse
from pydantic import BaseModel, Field


class AuditLogFilterParams(PaginationParams):
    """审计日志筛选参数。"""

    user_id: UUID | None = Field(default=None, description="操作者用户 ID")
    action: str | None = Field(default=None, description="动作标识，支持前缀匹配")
    resource_type: str | None = Field(default=None, description="资源类型")
    resource_id: str | None = Field(default=None, description="资源 ID")
    result: str | None = Field(default=None, description="success / failure")
    start_date: datetime | None = Field(default=None, description="起始时间")
    end_date: datetime | None = Field(default=None, description="结束时间")


class AuditLogListItem(BaseModel):
    """审计日志列表项。"""

    id: UUID
    user_id: UUID | None = None
    user_name: str | None = Field(
        default=None, description="操作者账号或昵称（便于界面展示）"
    )
    action: str
    resource_type: str
    resource_id: str | None = None
    result: str = "success"
    request_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogResponse(AuditLogListItem):
    """完整审计日志。"""

    detail: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    error_message: str | None = None
    updated_at: datetime | None = None


class AuditLogListResponse(PaginationResponse[AuditLogListItem]):
    """审计日志分页列表。"""

    pass

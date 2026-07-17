"""部门管理 Schema。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, description="部门编码")
    name: str = Field(..., min_length=1, max_length=100, description="部门名称")
    description: str | None = Field(None, description="部门介绍")
    is_enabled: bool = Field(True, description="是否启用")


class DepartmentUpdate(BaseModel):
    code: str | None = Field(None, min_length=1, max_length=50)
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    is_enabled: bool | None = None


class DepartmentMemberBrief(BaseModel):
    id: uuid.UUID
    username: str
    nickname: str | None = None
    email: str | None = None
    status: str | None = None


class DepartmentKbBrief(BaseModel):
    id: uuid.UUID
    name: str
    status: str | None = None
    visibility: str | None = None
    doc_count: int | None = None


class DepartmentListItem(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    is_enabled: bool = True
    member_count: int = 0
    kb_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DepartmentDetail(DepartmentListItem):
    members: list[DepartmentMemberBrief] = Field(default_factory=list)
    knowledge_bases: list[DepartmentKbBrief] = Field(default_factory=list)


class DepartmentListResponse(BaseModel):
    items: list[DepartmentListItem]
    total: int
    page: int
    page_size: int


class DepartmentMembersRequest(BaseModel):
    user_ids: list[uuid.UUID] = Field(..., min_length=1, description="要加入该部门的用户")


class DepartmentKbsRequest(BaseModel):
    kb_ids: list[uuid.UUID] = Field(..., min_length=1, description="要关联到该部门的知识库")

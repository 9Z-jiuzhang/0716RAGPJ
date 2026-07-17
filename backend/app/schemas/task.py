from datetime import datetime

from app.schemas.enums import TaskStatus
from pydantic import UUID4, BaseModel, Field


class TaskResponse(BaseModel):
    id: UUID4 = Field(..., description="任务ID")
    kb_id: UUID4 = Field(..., description="知识库ID")
    task_type: str = Field(..., description="任务类型")
    status: TaskStatus = Field(..., description="任务状态")
    progress: int = Field(0, description="进度百分比")
    processed_count: int = Field(0, description="已处理数量")
    total_count: int = Field(0, description="总数量")
    target_version: str | None = Field(None, description="目标索引版本")
    error_message: str | None = Field(None, description="错误信息")
    started_at: datetime | None = Field(None, description="开始时间")
    completed_at: datetime | None = Field(None, description="完成时间")
    created_at: datetime = Field(..., description="创建时间")


class TaskCreate(BaseModel):
    kb_id: UUID4 = Field(..., description="知识库ID")
    task_type: str = Field(..., description="任务类型")
    payload: dict | None = Field(None, description="任务载荷")


class TaskUpdate(BaseModel):
    status: TaskStatus | None = Field(None, description="任务状态")
    progress: int | None = Field(None, description="进度百分比")
    processed_count: int | None = Field(None, description="已处理数量")
    total_count: int | None = Field(None, description="总数量")
    target_version: str | None = Field(None, description="目标索引版本")
    error_message: str | None = Field(None, description="错误信息")
    started_at: datetime | None = Field(None, description="开始时间")
    completed_at: datetime | None = Field(None, description="完成时间")

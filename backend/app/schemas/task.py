from pydantic import BaseModel, Field, UUID4
from typing import Optional, Dict
from datetime import datetime

from app.schemas.enums import TaskStatus


class TaskResponse(BaseModel):
    id: UUID4 = Field(..., description="任务ID")
    kb_id: UUID4 = Field(..., description="知识库ID")
    task_type: str = Field(..., description="任务类型")
    status: TaskStatus = Field(..., description="任务状态")
    progress: int = Field(0, description="进度百分比")
    processed_count: int = Field(0, description="已处理数量")
    total_count: int = Field(0, description="总数量")
    target_version: Optional[str] = Field(None, description="目标索引版本")
    error_message: Optional[str] = Field(None, description="错误信息")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    created_at: datetime = Field(..., description="创建时间")


class TaskCreate(BaseModel):
    kb_id: UUID4 = Field(..., description="知识库ID")
    task_type: str = Field(..., description="任务类型")
    payload: Optional[Dict] = Field(None, description="任务载荷")


class TaskUpdate(BaseModel):
    status: Optional[TaskStatus] = Field(None, description="任务状态")
    progress: Optional[int] = Field(None, description="进度百分比")
    processed_count: Optional[int] = Field(None, description="已处理数量")
    total_count: Optional[int] = Field(None, description="总数量")
    target_version: Optional[str] = Field(None, description="目标索引版本")
    error_message: Optional[str] = Field(None, description="错误信息")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
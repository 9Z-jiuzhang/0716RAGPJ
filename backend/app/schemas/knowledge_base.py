from pydantic import BaseModel, Field, UUID4
from typing import Optional, List
from datetime import datetime

from app.schemas.enums import KnowledgeBaseStatus, Visibility, KnowledgeBaseType


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., description="知识库名称")
    type: KnowledgeBaseType = Field(..., description="知识库类型")
    tags: List[str] = Field(default=[], description="标签列表")
    description: Optional[str] = Field(None, description="简介/描述")
    visibility: Visibility = Field(..., description="可见性")
    embedding_model: str = Field(..., description="使用的 Embedding 模型名称")
    chunk_size: int = Field(500, description="默认分段大小（字符数）")
    chunk_overlap: int = Field(50, description="默认分段重叠（字符数）")


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, description="知识库名称")
    type: Optional[KnowledgeBaseType] = Field(None, description="知识库类型")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    description: Optional[str] = Field(None, description="简介/描述")
    visibility: Optional[Visibility] = Field(None, description="可见性")
    embedding_model: Optional[str] = Field(None, description="使用的 Embedding 模型名称")
    chunk_size: Optional[int] = Field(None, description="默认分段大小（字符数）")
    chunk_overlap: Optional[int] = Field(None, description="默认分段重叠（字符数）")


class KnowledgeBaseResponse(BaseModel):
    id: UUID4 = Field(..., description="唯一标识")
    name: str = Field(..., description="知识库名称")
    type: KnowledgeBaseType = Field(..., description="知识库类型")
    tags: List[str] = Field(..., description="标签列表")
    description: Optional[str] = Field(None, description="简介/描述")
    visibility: Visibility = Field(..., description="可见性")
    embedding_model: str = Field(..., description="使用的 Embedding 模型名称")
    chunk_size: int = Field(..., description="默认分段大小（字符数）")
    chunk_overlap: int = Field(..., description="默认分段重叠（字符数）")
    status: KnowledgeBaseStatus = Field(..., description="状态")
    current_index_version: Optional[str] = Field(None, description="当前索引版本号")
    document_count: int = Field(0, description="文档数量")
    chunk_count: int = Field(0, description="分段数量")
    creator_id: UUID4 = Field(..., description="创建者")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")


class KBPermissionItem(BaseModel):
    user_id: Optional[UUID4] = Field(None, description="用户ID")
    role_id: Optional[UUID4] = Field(None, description="角色ID")
    permission: str = Field(..., description="权限标识")


class KBPermissionUpdate(BaseModel):
    permissions: List[KBPermissionItem] = Field(..., description="权限列表")


class VectorizeStatusResponse(BaseModel):
    task_id: UUID4 = Field(..., description="任务ID")
    kb_id: UUID4 = Field(..., description="知识库ID")
    status: str = Field(..., description="任务状态")
    progress: int = Field(0, description="进度百分比")
    processed_count: int = Field(0, description="已处理文档数")
    total_count: int = Field(0, description="总文档数")
    error_message: Optional[str] = Field(None, description="错误信息")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")


class KnowledgeBaseFilter(BaseModel):
    name: Optional[str] = Field(None, description="按名称筛选")
    type: Optional[KnowledgeBaseType] = Field(None, description="按类型筛选")
    tag: Optional[str] = Field(None, description="按标签筛选")
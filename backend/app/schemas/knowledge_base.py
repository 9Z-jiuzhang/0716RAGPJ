from datetime import datetime

from app.schemas.enums import KnowledgeBaseStatus, KnowledgeBaseType, Visibility
from pydantic import UUID4, BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., description="知识库名称")
    type: KnowledgeBaseType = Field(..., description="知识库类型")
    tags: list[str] = Field(default=[], description="标签列表")
    description: str | None = Field(None, description="简介/描述")
    # 可见性由部门派生（访客专用 GUEST -> public，其余 -> restricted），此字段可省略
    visibility: Visibility | None = Field(None, description="可见性（由部门派生，可省略）")
    department: str | None = Field(
        None, description="访问范围/所属部门：GUEST=访客专用(所有人)，其余部门=部门隔离，空=私有"
    )
    embedding_model: str = Field(..., description="使用的 Embedding 模型名称")
    chunk_size: int = Field(500, description="默认分段大小（字符数）")
    chunk_overlap: int = Field(50, description="默认分段重叠（字符数）")


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(None, description="知识库名称")
    type: KnowledgeBaseType | None = Field(None, description="知识库类型")
    tags: list[str] | None = Field(None, description="标签列表")
    description: str | None = Field(None, description="简介/描述")
    visibility: Visibility | None = Field(None, description="可见性")
    department: str | None = Field(None, description="所属部门 A/B")
    embedding_model: str | None = Field(None, description="使用的 Embedding 模型名称")
    chunk_size: int | None = Field(None, description="默认分段大小（字符数）")
    chunk_overlap: int | None = Field(None, description="默认分段重叠（字符数）")


class KnowledgeBaseResponse(BaseModel):
    id: UUID4 = Field(..., description="唯一标识")
    name: str = Field(..., description="知识库名称")
    type: KnowledgeBaseType = Field(..., description="知识库类型")
    tags: list[str] = Field(..., description="标签列表")
    description: str | None = Field(None, description="简介/描述")
    visibility: Visibility = Field(..., description="可见性")
    department: str | None = Field(None, description="所属部门")
    embedding_model: str = Field(..., description="使用的 Embedding 模型名称")
    chunk_size: int = Field(..., description="默认分段大小（字符数）")
    chunk_overlap: int = Field(..., description="默认分段重叠（字符数）")
    status: KnowledgeBaseStatus = Field(..., description="状态")
    current_index_version: str | None = Field(None, description="当前索引版本号")
    document_count: int = Field(0, description="文档数量")
    chunk_count: int = Field(0, description="分段数量")
    creator_id: UUID4 = Field(..., description="创建者")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")


class KBPermissionItem(BaseModel):
    user_id: UUID4 | None = Field(None, description="用户ID")
    role_id: UUID4 | None = Field(None, description="角色ID")
    permission: str = Field(..., description="权限标识")


class KBPermissionUpdate(BaseModel):
    permissions: list[KBPermissionItem] = Field(..., description="权限列表")


class VectorizeStatusResponse(BaseModel):
    task_id: UUID4 = Field(..., description="任务ID")
    kb_id: UUID4 = Field(..., description="知识库ID")
    status: str = Field(..., description="任务状态")
    progress: int = Field(0, description="进度百分比")
    processed_count: int = Field(0, description="已处理文档数")
    total_count: int = Field(0, description="总文档数")
    error_message: str | None = Field(None, description="错误信息")
    started_at: datetime | None = Field(None, description="开始时间")
    completed_at: datetime | None = Field(None, description="完成时间")
    target_version: str | None = Field(None, description="目标索引版本")


class ReVectorizeRequest(BaseModel):
    """重新向量化可选参数：可同时更新分段规则后再重建。"""

    chunk_size: int | None = Field(None, ge=100, le=5000, description="分段长度；不传则沿用知识库当前值")
    chunk_overlap: int | None = Field(None, ge=0, le=1000, description="分段重叠；不传则沿用知识库当前值")
    split_mode: str | None = Field(
        None,
        pattern="^(fixed|sliding|paragraph|heading|markdown)$",
        description="分段模式：fixed / sliding / paragraph / heading / markdown",
    )
    separators: list[str] | None = Field(None, description="分隔符列表（fixed 模式）")
    embedding_model: str | None = Field(None, max_length=200, description="可选：切换嵌入模型后重建")
    apply_to_documents: bool = Field(
        True,
        description="是否将分段规则同步到库内全部文档（推荐开启）",
    )
    force_all: bool = Field(
        False,
        description="为 True 时处理全部未删除文档；默认仅 ready/error/pending_segment",
    )


class KnowledgeBaseFilter(BaseModel):
    name: str | None = Field(None, description="按名称筛选")
    type: KnowledgeBaseType | None = Field(None, description="按类型筛选")
    tag: str | None = Field(None, description="按标签筛选")

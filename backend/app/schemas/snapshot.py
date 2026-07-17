"""快照相关请求/响应 Schema（产品手册 5.8 / 框架提示词 4.9）。"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.schemas.common import PaginationResponse
from pydantic import BaseModel, Field, field_validator


class CreateSnapshotRequest(BaseModel):
    """手动创建快照请求。"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="快照名称",
        examples=["发布前备份"],
    )
    description: str | None = Field(default=None, max_length=2000, description="快照说明")


class RollbackRequest(BaseModel):
    """回退请求：必须显式 confirm=true。"""

    confirm: bool = Field(..., description="二次确认，必须为 true 才能执行回退")
    document_ids: list[UUID] | None = Field(
        default=None,
        description="选择性恢复的文档 ID 列表；为空则恢复整个知识库；不可传空列表",
    )

    @field_validator("confirm")
    @classmethod
    def must_confirm(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("回退操作必须将 confirm 设为 true")
        return v

    @field_validator("document_ids")
    @classmethod
    def document_ids_not_empty_list(cls, v: list[UUID] | None) -> list[UUID] | None:
        if v is not None and len(v) == 0:
            raise ValueError("document_ids 不可为空列表；整库恢复请省略该字段")
        return v


class SnapshotDocumentItem(BaseModel):
    """快照内文档摘要。"""

    document_id: UUID = Field(..., description="原始文档 ID")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    chunk_count: int = Field(..., description="分段数")
    content_hash: str | None = Field(default=None, description="内容哈希")
    metadata: dict[str, Any] = Field(default_factory=dict, description="文档元信息")

    model_config = {"from_attributes": True}


class SnapshotListItem(BaseModel):
    """快照列表项。"""

    id: UUID
    kb_id: UUID
    name: str
    description: str | None = None
    trigger: str = Field(..., description="创建方式")
    status: str
    document_count: int = Field(default=0, description="快照包含的文档数")
    total_chunks: int = Field(default=0, description="快照内总分段数")
    creator_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class SnapshotResponse(SnapshotListItem):
    """完整快照信息。"""

    config_snapshot: dict[str, Any] = Field(default_factory=dict, description="配置快照")
    updated_at: datetime | None = None


class SnapshotDetailResponse(SnapshotResponse):
    """快照详情：含文档列表、分段统计、权限配置。"""

    documents: list[SnapshotDocumentItem] = Field(default_factory=list)
    permission_snapshot: list[dict[str, Any]] = Field(default_factory=list, description="快照时的权限配置")
    segment_rules: dict[str, Any] = Field(default_factory=dict, description="分段规则快照")


class AffectedDocument(BaseModel):
    """回退差异中的单条文档变更。"""

    document_id: UUID
    filename: str
    change_type: Literal["added", "removed", "modified", "unchanged"] = Field(
        ..., description="相对当前状态、回退后将发生的变更类型"
    )
    current_chunk_count: int | None = Field(default=None, description="当前分段数")
    snapshot_chunk_count: int | None = Field(default=None, description="快照分段数")
    detail: str | None = Field(default=None, description="变更说明")


class ConfigChangeItem(BaseModel):
    """知识库配置项差异。"""

    field: str
    current: Any = None
    snapshot: Any = None


class RollbackPreviewResponse(BaseModel):
    """回退差异预览。"""

    snapshot_id: UUID
    kb_id: UUID
    snapshot_name: str
    affected_documents: list[AffectedDocument] = Field(default_factory=list)
    config_changes: list[ConfigChangeItem] = Field(default_factory=list, description="分段规则/嵌入模型/权限等配置差异")
    total_changes: int = Field(default=0, description="将发生变更的文档数（不含 unchanged）")
    will_create_protection_snapshot: bool = Field(default=True, description="回退前是否自动创建保护快照")
    rebuild_required: bool = Field(default=True, description="回退后需重建向量索引后才会切换生效版本")


class SnapshotListResponse(PaginationResponse[SnapshotListItem]):
    """快照分页列表。"""

    pass


class RollbackResultResponse(BaseModel):
    """回退执行结果。"""

    protection_snapshot_id: UUID = Field(..., description="回退前保护快照 ID")
    new_index_version: str = Field(..., description="新生成的索引版本号（building，待向量重建后激活）")
    index_status: str = Field(default="building", description="索引版本状态")
    before_version: str | None = Field(default=None, description="回退前生效索引版本")
    after_version: str = Field(..., description="回退后待激活的索引版本")
    restored_document_count: int = Field(..., description="恢复涉及的文档数")
    restored_document_ids: list[UUID] = Field(default_factory=list, description="已恢复文档 ID，供异步重建索引使用")
    selective: bool = Field(default=False, description="是否选择性恢复")
    rebuild_required: bool = Field(default=True, description="是否仍需向量化模块重建并激活索引")
    message: str = Field(default="文档与配置已按快照恢复；索引版本处于 building，待向量重建后原子激活")


class SnapshotCleanupResponse(BaseModel):
    """快照策略清理结果（5.8.4）。"""

    expired_deleted: int = Field(default=0, description="按保留天数清理数量")
    excess_deleted: int = Field(default=0, description="按最大数量清理数量")
    retention_days: int
    max_count: int
    active_remaining: int = Field(default=0, description="清理后仍活跃的快照数（含保护）")

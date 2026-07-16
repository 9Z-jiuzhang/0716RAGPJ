from pydantic import BaseModel, Field, UUID4
from typing import Optional, List, Dict
from datetime import datetime

from app.schemas.enums import DocumentStatus, FileType, SplitMode


class DocumentUploadResponse(BaseModel):
    id: UUID4 = Field(..., description="文档ID")
    filename: str = Field(..., description="文件名")
    file_type: FileType = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小")
    status: DocumentStatus = Field(..., description="处理状态")


class DocumentResponse(BaseModel):
    id: UUID4 = Field(..., description="唯一标识")
    kb_id: UUID4 = Field(..., description="所属知识库")
    filename: str = Field(..., description="原始文件名")
    file_type: FileType = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小（字节）")
    file_path: str = Field(..., description="MinIO 对象存储路径")
    chunk_count: int = Field(..., description="分段数量")
    status: DocumentStatus = Field(..., description="状态")
    error_message: Optional[str] = Field(None, description="处理失败原因")
    creator_id: UUID4 = Field(..., description="上传者用户ID")
    created_at: datetime = Field(..., description="上传时间")
    updated_at: datetime = Field(..., description="最后更新时间")


class SegmentRuleUpdate(BaseModel):
    chunk_size: int = Field(500, description="每段最大字符数")
    chunk_overlap: int = Field(50, description="相邻段重叠字符数")
    separators: List[str] = Field(default=["\n\n", "\n", "。", ".", " "], description="分段分隔符优先级")
    split_mode: SplitMode = Field(SplitMode.FIXED, description="分段模式")
    enable_semantic: bool = Field(False, description="是否启用语义分段")


class DocumentChunkResponse(BaseModel):
    id: UUID4 = Field(..., description="分段ID")
    document_id: UUID4 = Field(..., description="所属文档ID")
    chunk_index: int = Field(..., description="分段序号")
    content: str = Field(..., description="分段内容")
    metadata: Dict = Field(..., description="元数据")
    is_active: bool = Field(..., description="是否启用")
    index_version: str = Field(..., description="索引版本")
    created_at: datetime = Field(..., description="创建时间")


class ChunkUpdate(BaseModel):
    content: Optional[str] = Field(None, description="分段内容")
    is_active: Optional[bool] = Field(None, description="是否启用")


class DocumentFilter(BaseModel):
    filename: Optional[str] = Field(None, description="按文件名搜索")
    file_type: Optional[FileType] = Field(None, description="按文件类型筛选")
    status: Optional[DocumentStatus] = Field(None, description="按状态筛选")
"""文档模块 Pydantic DTO。【对齐 docs/openapi.json】"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    id: str
    kb_id: str
    filename: str
    file_type: str
    file_size: int
    file_path: str
    chunk_count: int
    status: str
    error_message: str | None = None
    creator_id: str
    created_at: datetime
    updated_at: datetime


class DocumentContentPreviewResponse(BaseModel):
    """文档正文预览（管理端预览面板）。"""

    id: str
    kb_id: str
    filename: str
    file_type: str
    status: str
    chunk_count: int
    error_message: str | None = None
    raw_text: str = Field(default="", description="解析后的原文")
    normalized_text: str = Field(default="", description="清洗后的正文")
    raw_char_count: int = 0
    normalized_char_count: int = 0
    truncated: bool = Field(False, description="正文是否因过长被截断")
    max_preview_chars: int = Field(80000, description="单字段预览最大字符数")
    preview_source: str = Field(
        default="normalized_text",
        description="推荐展示源：normalized_text / raw_text / empty",
    )
    segment_rules: dict[str, Any] = Field(default_factory=dict)


class DocumentListItem(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    status: str
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


class DocumentChunkResponse(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    content: str
    char_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class ChunkListResponse(BaseModel):
    items: list[DocumentChunkResponse]
    total: int
    page: int
    page_size: int


class UpdateSegmentRulesRequest(BaseModel):
    chunk_size: int = Field(ge=100, le=5000)
    chunk_overlap: int = Field(ge=0, le=1000)
    separators: list[str] | None = None
    split_mode: str | None = None
    # P2迭代开发，当前仅配置存储，不启用语义切分
    enable_semantic: bool | None = False


class SegmentPreviewChunk(BaseModel):
    chunk_index: int
    content: str
    char_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class SegmentPreviewResponse(BaseModel):
    """干跑分段预览：不写库。"""

    document_id: str
    rules: dict[str, Any]
    total_chunks: int
    chunks: list[SegmentPreviewChunk]
    preview_source: str = Field(description="normalized_text / raw_text")


class SegmentPreviewOffsetChunk(BaseModel):
    """带起止下标的预览分段。start 含、end 不含，均相对解析后的预览源文本。"""

    chunk_index: int
    content: str
    char_count: int
    start: int = Field(description="该分段在解析文本中的起始下标（含）")
    end: int = Field(description="该分段在解析文本中的结束下标（不含）")
    metadata: dict[str, Any] = Field(default_factory=dict)


class FileSegmentPreviewResponse(BaseModel):
    """预校验分段效果：支持待解析文件或已上传文档 id 干跑分段。

    仅返回分段结果，不触发向量化、不写向量库、不修改数据库正式文档记录。
    """

    kb_id: str
    document_id: str | None = Field(default=None, description="按已上传文档预览时回填，按文件预览时为 None")
    filename: str
    file_type: str
    rules: dict[str, Any]
    total_chunks: int
    total_chars: int = Field(description="解析后预览源文本总字符数")
    chunks: list[SegmentPreviewOffsetChunk]
    preview_source: str = Field(description="normalized_text / raw_text")


class UpdateChunkRequest(BaseModel):
    content: str | None = None
    is_enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class NormalizeResult(BaseModel):
    removed_blank_lines: int = 0
    removed_duplicate_blocks: int = 0
    char_count_before: int = 0
    char_count_after: int = 0


# kerper 模块占位兼容（实际 5.5 实现见 app.services.document_service）
class DocumentFilter(BaseModel):
    filename: str | None = None
    file_type: str | None = None
    status: str | None = None


class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int
    status: str


SegmentRuleUpdate = UpdateSegmentRulesRequest
ChunkUpdate = UpdateChunkRequest

"""文档模块 Pydantic DTO。【对齐 contracts/openapi.json】"""

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

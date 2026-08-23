"""智能问答相关 Pydantic Schema，对齐 OpenAPI 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.schemas.common import PaginationResponse
from pydantic import BaseModel, Field


class CitationImageSchema(BaseModel):
    """引用关联的文档图表页（PDF 栅格化 PNG）。"""

    page: int = Field(description="页码，从 1 开始")
    url: str = Field(description="相对 API 路径，需带登录态或访客可访问库权限拉取")


class CitationSchema(BaseModel):
    """回答引用来源片段。"""

    doc_id: UUID = Field(description="文档 ID")
    doc_name: str = Field(description="文档名称")
    chunk_index: int = Field(description="分段序号，从 0 开始")
    content: str = Field(description="引用原文片段")
    score: float = Field(description="相关性得分")
    chunk_id: UUID | None = Field(default=None, description="分段 ID（粘性证据回溯用）")
    source: str | None = Field(default=None, description="命中来源：vector/fulltext/hybrid/sticky")
    images: list[CitationImageSchema] = Field(
        default_factory=list,
        description="与本命中片段相关的 PDF 页缩略图（非整本文档）",
    )


# 用户问题（输入框）硬上限，与前端提示文案保持一致
QA_QUESTION_MAX_CHARS = 2000


class AskRequest(BaseModel):
    """流式问答请求体。"""

    question: str = Field(
        ...,
        min_length=1,
        max_length=QA_QUESTION_MAX_CHARS,
        description=f"用户问题（最长 {QA_QUESTION_MAX_CHARS} 字）",
    )
    session_id: UUID | None = Field(default=None, description="不传则创建新会话")
    kb_ids: list[UUID] | None = Field(default=None, description="限定检索知识库")
    strategy: Literal["vector", "fulltext", "hybrid"] = Field(default="hybrid", description="检索策略")
    top_k: int = Field(default=5, ge=1, le=20, description="返回片段数量")
    temperature: float = Field(default=0.7, ge=0, le=2, description="生成温度")
    explicit_faq_click: bool = Field(
        default=False,
        description="访客点选热门 FAQ 时为 True，强制允许 FAQ 命中（含多轮会话）",
    )
    rewrite_enabled: bool | None = Field(
        default=None,
        description="是否对本轮启用 Query 改写；不传则沿用管理员全局策略（追问场景可能临时开启）",
    )


class RenameSessionRequest(BaseModel):
    """会话重命名请求。"""

    title: str = Field(..., min_length=1, max_length=100, description="新标题")


class SessionSchema(BaseModel):
    """会话列表/详情摘要。"""

    id: UUID
    title: str
    kb_names: list[str] = Field(default_factory=list)
    message_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageSchema(BaseModel):
    """会话内单条消息。"""

    id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    citations: list[CitationSchema] | None = None
    token_count: int | None = None
    created_at: datetime
    # 扩展字段：检索元数据与追踪（契约外可选返回）
    retrieval_meta: dict[str, Any] | None = None
    request_id: str | None = None
    strategy: str | None = None
    latency_ms: int | None = None

    model_config = {"from_attributes": True}


class SessionListData(PaginationResponse[SessionSchema]):
    """会话分页列表 data 载荷。"""


class MessageListData(PaginationResponse[MessageSchema]):
    """消息分页列表 data 载荷。"""


class FeedbackRequest(BaseModel):
    """回答反馈请求。``rating=null`` 表示取消已有点赞/点踩。"""

    message_id: UUID = Field(description="被评价的助手消息 ID")
    rating: Literal["useful", "useless"] | None = Field(description="有用/无用；传 null 取消反馈并从统计表删除")
    comment: str | None = Field(default=None, max_length=500, description="可选评论")


class ChartUiEventRequest(BaseModel):
    """引用图表 UI 埋点（P2 lazy hydrate / lightbox）。"""

    action: Literal["hydrate", "hydrate_failed", "lightbox_open"] = Field(description="事件类型")

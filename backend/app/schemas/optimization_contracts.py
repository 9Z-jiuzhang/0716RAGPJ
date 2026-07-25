"""六维优化公共契约：路由、缓存、事件、向量分数与 Redis Key 规范。

业务层应通过本模块类型交互，避免各模块自行定义冲突字段。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationIntent(str, Enum):
    """业务意图（Guard 的 SAFETY_BLOCK 仍由 Guard 独立处理）。"""

    GREETING_CHAT = "GREETING_CHAT"
    THANKS_GOODBYE = "THANKS_GOODBYE"
    SYSTEM_HELP = "SYSTEM_HELP"
    SYSTEM_MECHANISM = "SYSTEM_MECHANISM"
    PREVIOUS_ANSWER_TRANSFORM = "PREVIOUS_ANSWER_TRANSFORM"
    CONTEXT_FOLLOWUP_KB = "CONTEXT_FOLLOWUP_KB"
    NEW_KB_QUERY = "NEW_KB_QUERY"
    CLARIFICATION = "CLARIFICATION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    ROUTE_FALLBACK = "ROUTE_FALLBACK"


class ConversationRouteDecision(BaseModel):
    """业务路由决策结果，写入问答事件与流水线分支。"""

    model_config = ConfigDict(protected_namespaces=())

    intent: ConversationIntent
    confidence: float = Field(ge=0, le=1, default=1.0)
    should_retrieve: bool = False
    should_use_last_answer: bool = False
    should_clarify: bool = False
    should_block: bool = False
    normalized_query: str | None = None
    inherited_scope: dict[str, Any] = Field(default_factory=dict)
    reason_code: str = "ok"
    classifier_version: str = "rules-v1"
    transform_type: str | None = None


class CacheLookupRequest(BaseModel):
    """多级缓存查询请求；答案键必须含 Scope/版本，禁止仅用问题文本。"""

    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    tenant_id: str = "default"
    user_id: str | None = None
    role_ids: list[str] = Field(default_factory=list)
    scope_fingerprint: str
    permission_version: str = "v0"
    normalized_question: str
    language: str = "zh-CN"
    model_config_version: str = "env"
    prompt_version: str = "v1"
    query_processing_version: str = "v1"
    top_k: int = 5
    deadline_at: datetime | None = None


class CacheLookupResult(BaseModel):
    """缓存查询结果；权限失败只能视为未命中。"""

    status: Literal["hit", "miss", "observe", "error"] = "miss"
    level: Literal["L1", "L2", "L3", "L4", "L5", "none"] = "none"
    answer: str | None = None
    citation_ids: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    cache_entry_id: str | None = None
    normalized_similarity: float | None = None
    top1_top2_margin: float | None = None
    source_versions: dict[str, str] = Field(default_factory=dict)
    quality_score: float | None = None
    lookup_latency_ms: int = 0
    miss_reason: str | None = None


class UnifiedVectorScore(BaseModel):
    """适配器输出的版本化统一相似度。"""

    raw_score: float
    raw_score_type: Literal["cosine_similarity", "cosine_distance", "l2", "inner_product", "unknown"] = "unknown"
    normalized_similarity: float = Field(ge=0, le=1)
    normalization_version: str = "v1"


class ModelConfigSnapshot(BaseModel):
    """单次请求冻结的模型配置快照，执行中不随后台修改变化。"""

    model_config = ConfigDict(protected_namespaces=())

    snapshot_id: str
    model_id: str | None = None
    model_type: str = "chat"
    provider: str = "env"
    model_name: str
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    config_version: str = "env"
    published_at: datetime | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class QARequestEventCreate(BaseModel):
    """问答事件写入载荷（异步、失败不阻塞问答）。"""

    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    trace_id: str | None = None
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    actor_hash: str | None = None
    tenant_id: str = "default"
    role_ids: list[str] = Field(default_factory=list)
    question_hash: str | None = None
    question_preview: str | None = None
    route_intent: str | None = None
    route_confidence: float | None = None
    should_retrieve: bool | None = None
    top_k: int | None = None
    rewrite_enabled: bool | None = None
    cache_level: str | None = None
    cache_hit_id: str | None = None
    normalized_similarity: float | None = None
    miss_reason: str | None = None
    retrieval_hit_count: int | None = None
    citation_count: int | None = None
    model_snapshot_id: str | None = None
    latency_ms: int | None = None
    result_status: str = "ok"
    error_code: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class QAFeedbackUpsert(BaseModel):
    """反馈 Upsert：同一 message_id + actor_hash 不重复计数。"""

    message_id: UUID
    actor_hash: str
    rating: Literal["useful", "useless"]
    reason: str | None = None
    comment: str | None = Field(default=None, max_length=500)

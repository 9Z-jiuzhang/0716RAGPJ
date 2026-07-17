"""检索引擎公共数据类型与常量。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

RetrievalStrategy = Literal["vector", "fulltext", "hybrid"]


@dataclass
class RetrievalHit:
    """统一检索命中结构，供融合排序与引用组装使用。"""

    chunk_id: str
    doc_id: str
    doc_name: str
    kb_id: str
    chunk_index: int
    content: str
    score: float
    source: RetrievalStrategy
    # 原始分路得分（融合前），便于调试与可观测
    raw_score: float = 0.0
    # RRF 融合分（仅 hybrid 路径填充）
    rrf_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_citation(self) -> dict[str, Any]:
        """转换为 API CitationResponse 字段结构。"""
        return {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "score": round(self.score, 6),
        }


@dataclass
class KBTarget:
    """授权知识库及其当前索引版本。"""

    kb_id: UUID
    name: str
    index_version: str


@dataclass
class RetrievalResult:
    """单次检索的完整输出。"""

    hits: list[RetrievalHit]
    strategy: RetrievalStrategy
    query: str
    rewritten_query: str | None = None
    authorized_kb_ids: list[str] = field(default_factory=list)
    vector_count: int = 0
    fulltext_count: int = 0
    filtered_out: int = 0

    @property
    def empty(self) -> bool:
        return len(self.hits) == 0

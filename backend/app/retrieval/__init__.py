"""
检索引擎包（产品手册 5.6）。

- scope：知识库权限与检索范围解析
- vector：Chroma 语义向量检索
- fulltext：PostgreSQL tsvector / pg_trgm 全文检索
- hybrid：双路 RRF 融合 + 相关性阈值过滤
"""

from app.retrieval.fulltext import FulltextRetriever, fulltext_retriever
from app.retrieval.hybrid import HybridRetriever, hybrid_retriever
from app.retrieval.scope import resolve_kb_targets
from app.retrieval.types import (
    KBTarget,
    RetrievalHit,
    RetrievalResult,
    RetrievalStrategy,
)
from app.retrieval.vector import VectorRetriever, vector_retriever

__all__ = [
    "KBTarget",
    "RetrievalHit",
    "RetrievalResult",
    "RetrievalStrategy",
    "resolve_kb_targets",
    "VectorRetriever",
    "vector_retriever",
    "FulltextRetriever",
    "fulltext_retriever",
    "HybridRetriever",
    "hybrid_retriever",
]

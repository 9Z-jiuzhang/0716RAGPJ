"""向量检索引擎：Embedding + Chroma 语义相似度检索。

适用场景：通用语义搜索、模糊意图、同义改写后的召回。
权限边界由调用方传入的 KBTarget 列表保证，本模块不再二次鉴权。
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.retrieval.types import KBTarget, RetrievalHit
from app.services.chroma_store import chroma_store
from app.services.embedding import EmbeddingServiceError, embedding_service

logger = logging.getLogger(__name__)


class VectorRetriever:
    """基于 Chroma 的语义向量检索器。"""

    async def search(
        self,
        query: str,
        targets: Sequence[KBTarget],
        *,
        top_k: int = 5,
    ) -> list[RetrievalHit]:
        """
        对授权知识库执行向量检索并合并为统一命中列表。

        各库先取 top_k，再按 score 全局截取 top_k，避免单库垄断。
        """
        if not query.strip() or not targets:
            return []

        try:
            query_embedding = await embedding_service.embed_query(query)
        except EmbeddingServiceError as exc:
            logger.warning("向量检索跳过：Embedding 不可用 — %s", exc)
            return []

        try:
            kb_targets = [(t.kb_id, t.index_version) for t in targets]
            # 每库多取一些候选，合并后再截断，提升跨库召回质量
            per_kb_k = max(top_k, min(top_k * 2, 20))
            raw_hits = await chroma_store.aquery_multi_kb(
                kb_targets=kb_targets,
                query_embedding=query_embedding,
                top_k=per_kb_k,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("向量检索跳过：Chroma 查询失败 — %s", exc)
            return []

        # 用 targets 补全可能缺失的 doc_name（Chroma metadata 应已含 doc_name）
        name_map = {str(t.kb_id): t.name for t in targets}
        results: list[RetrievalHit] = []
        for h in raw_hits:
            results.append(
                RetrievalHit(
                    chunk_id=h.chunk_id,
                    doc_id=h.doc_id,
                    doc_name=h.doc_name or name_map.get(h.kb_id, ""),
                    kb_id=h.kb_id,
                    chunk_index=h.chunk_index,
                    content=h.content,
                    score=h.score,
                    source="vector",
                    raw_score=h.score,
                    metadata=h.metadata,
                )
            )

        results.sort(key=lambda x: x.score, reverse=True)
        return results[: max(1, top_k)]


vector_retriever = VectorRetriever()

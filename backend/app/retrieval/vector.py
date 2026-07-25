"""向量检索引擎：Embedding + VectorStorePort 语义相似度检索。

适用场景：通用语义搜索、模糊意图、同义改写后的召回。
权限边界由调用方传入的 KBTarget 列表保证，本模块不再二次鉴权。
读提供方由 VECTOR_READ_PROVIDER 决定（默认 chroma，不切阿里云生产读）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.retrieval.types import KBTarget, RetrievalHit
from app.services.embedding import EmbeddingServiceError, embedding_service
from app.services.vector_port import VectorSearchRequest, vector_store_router

logger = logging.getLogger(__name__)


class VectorRetriever:
    """基于统一向量端口的语义向量检索器。"""

    async def search_many(
        self,
        queries: Sequence[tuple[str, str]],
        targets: Sequence[KBTarget],
        *,
        top_k: int = 5,
    ) -> list[tuple[str, list[RetrievalHit]]]:
        """批量向量化多个 Query，再分别执行向量检索。

        ``queries`` 使用 ``(通道标签, 查询文本)``，返回值保留相同标签供 RRF
        标记命中来源。所有 Query 在一次 ``embed_texts`` 调用中提交，避免主查询、
        扩展查询和 HyDE 逐条产生远程 Embedding 往返。
        """
        if not queries or not targets:
            return []

        cleaned_queries: list[tuple[str, str]] = []
        for label, query in queries:
            cleaned = (query or "").strip()
            if cleaned:
                cleaned_queries.append((label, cleaned))
        if not cleaned_queries:
            return []

        try:
            # Embedding 服务自身会按厂商上限分批；默认扩展数量较少时这里仅发一次 HTTP 请求。
            embeddings = await embedding_service.embed_texts([query for _, query in cleaned_queries])
        except EmbeddingServiceError as exc:
            logger.warning("批量向量检索跳过：Embedding 不可用 — %s", exc)
            return []

        if len(embeddings) != len(cleaned_queries):
            logger.warning(
                "批量向量检索跳过：Embedding 数量不匹配（查询 %d，向量 %d）",
                len(cleaned_queries),
                len(embeddings),
            )
            return []

        results: list[tuple[str, list[RetrievalHit]]] = []
        for (label, _), query_embedding in zip(cleaned_queries, embeddings, strict=True):
            hits = await self._search_by_embedding(query_embedding, targets, top_k=top_k)
            if hits:
                results.append((label, hits))
        return results

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

        # 单 Query 接口继续保留给其他调用方，并复用批量实现保证只有一套检索逻辑。
        results = await self.search_many([("query", query)], targets, top_k=top_k)
        return results[0][1] if results else []

    async def _search_by_embedding(
        self,
        query_embedding: list[float],
        targets: Sequence[KBTarget],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """使用已生成的向量经 VectorStorePort 查询，不再触发任何 Embedding 请求。"""

        # 每库多取一些候选，合并后再截断，提升跨库召回质量
        per_kb_k = max(top_k, min(top_k * 2, 20))
        name_map = {str(t.kb_id): t.name for t in targets}
        results: list[RetrievalHit] = []

        try:
            for t in targets:
                if not t.index_version:
                    continue
                req = VectorSearchRequest(
                    tenant_id="default",
                    collection=f"{t.kb_id}__{t.index_version}",
                    query_vector=list(query_embedding),
                    top_k=per_kb_k,
                    kb_id=str(t.kb_id),
                    index_version=str(t.index_version),
                )
                hits = await vector_store_router.search(req)
                for h in hits:
                    meta = dict(h.metadata or {})
                    kb_id = str(meta.get("kb_id") or t.kb_id)
                    score = float(h.score.normalized_similarity) if h.score else 0.0
                    chunk_index = int(meta.get("chunk_index") or 0)
                    results.append(
                        RetrievalHit(
                            chunk_id=h.chunk_id,
                            doc_id=h.document_id,
                            doc_name=str(meta.get("doc_name") or name_map.get(kb_id, "")),
                            kb_id=kb_id,
                            chunk_index=chunk_index,
                            content=h.content_ref or "",
                            score=score,
                            source="vector",
                            raw_score=score,
                            metadata=meta,
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("向量检索跳过：端口查询失败 — %s", exc)
            return []

        results.sort(key=lambda x: x.score, reverse=True)
        return results[: max(1, top_k)]


vector_retriever = VectorRetriever()

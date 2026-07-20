"""混合检索引擎：向量 + 全文双路召回，RRF 融合排序，相关性阈值截断。

RRF（Reciprocal Rank Fusion）公式：
  score(d) = sum( 1 / (k + rank_i(d)) )
其中 k 默认 60（QA_RRF_K），rank_i 为文档在第 i 路检索结果中的名次（从 1 开始）。

优势：无需对不同检索器的原始分数做归一化，工程上稳定可靠。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.retrieval.fulltext import fulltext_retriever
from app.retrieval.types import (
    KBTarget,
    RetrievalHit,
    RetrievalResult,
    RetrievalStrategy,
)
from app.retrieval.vector import vector_retriever
from app.services.rerank import rerank_service

logger = logging.getLogger(__name__)


class HybridRetriever:
    """统一检索门面：按 strategy 调度单路或混合检索。"""

    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        targets: Sequence[KBTarget],
        *,
        strategy: RetrievalStrategy = "hybrid",
        top_k: int | None = None,
        relevance_threshold: float | None = None,
        rewritten_query: str | None = None,
        expanded_queries: Sequence[str] | None = None,
        hyde_document: str | None = None,
    ) -> RetrievalResult:
        """
        执行检索并返回统一结果。

        query: 用于主路检索的查询文本（通常为改写后或原始问题）
        rewritten_query: 若与 query 不同，记录在结果元数据中
        expanded_queries: Query 扩展结果，同时参与向量与全文召回
        hyde_document: HyDE 假设文档，仅参与向量召回，绝不作为全文关键词
        """
        effective_k = top_k or settings.QA_DEFAULT_TOP_K
        # 先扩大候选集再重排；直接对最终 Top-K 调用 Rerank 无法纠正漏在后排的高相关片段。
        candidate_k = min(
            50,
            max(effective_k, effective_k * max(1, settings.RERANK_CANDIDATE_MULTIPLIER)),
        )
        threshold = settings.QA_RELEVANCE_THRESHOLD if relevance_threshold is None else relevance_threshold
        search_text = (query or "").strip()
        if not search_text or not targets:
            return RetrievalResult(
                hits=[],
                strategy=strategy,
                query=search_text,
                rewritten_query=rewritten_query,
                authorized_kb_ids=[str(t.kb_id) for t in targets],
            )

        # 主 Query 与扩展 Query 先做规范化去重，避免重复请求 Embedding 或数据库。
        search_variants: list[tuple[str, str]] = [("primary", search_text)]
        seen_queries = {search_text.casefold()}
        for index, candidate in enumerate(expanded_queries or [], start=1):
            cleaned = (candidate or "").strip()
            normalized = cleaned.casefold()
            if not cleaned or normalized in seen_queries:
                continue
            seen_queries.add(normalized)
            search_variants.append((f"expansion_{index}", cleaned))

        vector_lists: list[tuple[str, list[RetrievalHit]]] = []
        fulltext_lists: list[tuple[str, list[RetrievalHit]]] = []

        if strategy in ("vector", "hybrid"):
            for label, query_text in search_variants:
                try:
                    hits = await vector_retriever.search(query_text, targets, top_k=candidate_k)
                    if hits:
                        vector_lists.append((f"vector_{label}", hits))
                except Exception as exc:  # noqa: BLE001 — 单条 Query 失败不得阻断其他召回路
                    logger.warning("向量检索失败（%s），继续其他查询：%s", label, exc)

            # HyDE 只通过假设文档的向量寻找语义相近片段，避免假设内容参与字面全文匹配。
            cleaned_hyde = (hyde_document or "").strip()
            if cleaned_hyde:
                try:
                    hyde_hits = await vector_retriever.search(cleaned_hyde, targets, top_k=candidate_k)
                    if hyde_hits:
                        vector_lists.append(("vector_hyde", hyde_hits))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("HyDE 向量检索失败，继续使用其他召回结果：%s", exc)

        if strategy in ("fulltext", "hybrid"):
            # 同一个 AsyncSession 不做并发 SQL，按顺序执行以避免事务状态相互影响。
            for label, query_text in search_variants:
                try:
                    hits = await fulltext_retriever.search(db, query_text, targets, top_k=candidate_k)
                    if hits:
                        fulltext_lists.append((f"fulltext_{label}", hits))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("全文检索失败（%s），继续其他查询：%s", label, exc)

        if strategy == "vector":
            ranked_lists = vector_lists
        elif strategy == "fulltext":
            ranked_lists = fulltext_lists
        else:
            ranked_lists = [*vector_lists, *fulltext_lists]

        if not ranked_lists:
            merged = []
        elif len(ranked_lists) == 1:
            # 只有一条召回路时保留其原始相关度，避免无意义的 RRF 归一化。
            merged = ranked_lists[0][1][:candidate_k]
        else:
            merged = self._rrf_fuse_many(
                ranked_lists,
                k=settings.QA_RRF_K,
                top_k=candidate_k,
            )

        # Rerank 返回的 relevance_score 是真实 0-1 相关度，将直接用于引用置信度展示。
        rerank_outcome = await rerank_service.rerank(
            db,
            query=search_text,
            hits=merged,
            top_k=effective_k,
        )
        ranked = rerank_outcome.hits

        before_filter = len(ranked)
        filtered = self._apply_threshold(ranked, threshold)
        # 软兜底：阈值过严导致全灭时，保留融合/单路排序后的前几条，避免有召回却显示「未命中」
        if not filtered and ranked:
            logger.info(
                "相关性阈值 %.2f 滤空 %d 条命中，回退保留 top-%d",
                threshold,
                before_filter,
                min(effective_k, len(ranked)),
            )
            filtered = ranked[:effective_k]
        filtered_out = before_filter - len(filtered)

        return RetrievalResult(
            hits=filtered,
            strategy=strategy,
            query=search_text,
            rewritten_query=rewritten_query,
            authorized_kb_ids=[str(t.kb_id) for t in targets],
            vector_count=sum(len(hits) for _, hits in vector_lists),
            fulltext_count=sum(len(hits) for _, hits in fulltext_lists),
            filtered_out=filtered_out,
            rerank_applied=rerank_outcome.applied,
            rerank_provider=rerank_outcome.provider,
            rerank_model=rerank_outcome.model,
            rerank_error=rerank_outcome.error,
            expanded_query_count=max(0, len(search_variants) - 1),
            hyde_used=bool((hyde_document or "").strip() and strategy in ("vector", "hybrid")),
        )

    @staticmethod
    def _rrf_fuse_many(
        ranked_lists: list[tuple[str, list[RetrievalHit]]],
        *,
        k: int,
        top_k: int,
    ) -> list[RetrievalHit]:
        """融合任意数量的 Query/检索通道，并记录每个片段的命中来源。"""
        rrf_scores: dict[str, float] = {}
        hit_map: dict[str, RetrievalHit] = {}

        for channel, hits in ranked_lists:
            for rank, hit in enumerate(hits, start=1):
                contribution = 1.0 / (k + rank)
                rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + contribution
                stored = hit_map.get(hit.chunk_id)
                if stored is None:
                    stored = RetrievalHit(
                        chunk_id=hit.chunk_id,
                        doc_id=hit.doc_id,
                        doc_name=hit.doc_name,
                        kb_id=hit.kb_id,
                        chunk_index=hit.chunk_index,
                        content=hit.content,
                        score=0.0,
                        source="hybrid",
                        raw_score=hit.raw_score,
                        metadata={**hit.metadata, "matched_queries": [channel]},
                    )
                    hit_map[hit.chunk_id] = stored
                else:
                    matched = stored.metadata.setdefault("matched_queries", [])
                    if channel not in matched:
                        matched.append(channel)
                    if hit.raw_score > stored.raw_score:
                        stored.raw_score = hit.raw_score
                stored.metadata[f"{channel}_rank"] = rank

        list_count = max(1, len(ranked_lists))
        fused: list[RetrievalHit] = []
        for chunk_id, rrf_score in rrf_scores.items():
            hit = hit_map[chunk_id]
            hit.rrf_score = rrf_score
            hit.score = HybridRetriever._normalize_rrf(
                rrf_score,
                k=k,
                num_lists=list_count,
            )
            # RRF 分数表示多路排序一致性，不冒充向量或模型置信概率。
            hit.metadata["score_source"] = "normalized_rrf"
            fused.append(hit)

        fused.sort(key=lambda item: item.rrf_score, reverse=True)
        return fused[: max(1, top_k)]

    @staticmethod
    def _rrf_fuse(
        vector_hits: list[RetrievalHit],
        fulltext_hits: list[RetrievalHit],
        *,
        k: int,
        top_k: int,
    ) -> list[RetrievalHit]:
        """
        对两路结果做 RRF 融合。

        同 chunk_id 合并为一条，score 取 RRF 总分，source 标记为 hybrid。
        """
        rrf_scores: dict[str, float] = {}
        hit_map: dict[str, RetrievalHit] = {}

        def accumulate(hits: list[RetrievalHit], channel: str) -> None:
            for rank, hit in enumerate(hits, start=1):
                cid = hit.chunk_id
                contribution = 1.0 / (k + rank)
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + contribution
                stored = hit_map.get(cid)
                if stored is None:
                    hit_map[cid] = RetrievalHit(
                        chunk_id=hit.chunk_id,
                        doc_id=hit.doc_id,
                        doc_name=hit.doc_name,
                        kb_id=hit.kb_id,
                        chunk_index=hit.chunk_index,
                        content=hit.content,
                        score=0.0,
                        source="hybrid",
                        raw_score=hit.raw_score,
                        metadata={**hit.metadata, f"{channel}_rank": rank},
                    )
                else:
                    stored.metadata[f"{channel}_rank"] = rank
                    # 保留较高 raw_score 作为参考
                    if hit.raw_score > stored.raw_score:
                        stored.raw_score = hit.raw_score

        accumulate(vector_hits, "vector")
        accumulate(fulltext_hits, "fulltext")

        fused: list[RetrievalHit] = []
        for cid, rrf in rrf_scores.items():
            hit = hit_map[cid]
            hit.rrf_score = rrf
            # 对外展示的 score 使用 RRF 分（非 0-1，但可排序）；同时归一化到 (0,1] 便于阈值
            hit.score = HybridRetriever._normalize_rrf(rrf, k=k, num_lists=2)
            hit.metadata["score_source"] = "normalized_rrf"
            fused.append(hit)

        fused.sort(key=lambda h: h.rrf_score, reverse=True)
        return fused[: max(1, top_k)]

    @staticmethod
    def _normalize_rrf(rrf_score: float, *, k: int, num_lists: int) -> float:
        """
        将 RRF 分映射到 (0, 1] 便于与 QA_RELEVANCE_THRESHOLD 比较。

        理论上双路都排第 1 时 RRF 最大 = 2 / (k+1)。
        """
        max_rrf = num_lists / (k + 1)
        if max_rrf <= 0:
            return 0.0
        return max(0.0, min(1.0, rrf_score / max_rrf))

    @staticmethod
    def _apply_threshold(hits: list[RetrievalHit], threshold: float) -> list[RetrievalHit]:
        """相关性阈值截断：低于阈值的片段丢弃。"""
        if threshold <= 0:
            return hits
        return [h for h in hits if h.score >= threshold]


hybrid_retriever = HybridRetriever()

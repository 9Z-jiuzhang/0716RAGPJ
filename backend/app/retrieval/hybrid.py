"""混合检索引擎：向量 + 全文双路召回，RRF 融合排序，相关性阈值截断。

RRF（Reciprocal Rank Fusion）公式：
  score(d) = sum( 1 / (k + rank_i(d)) )
其中 k 默认 60（QA_RRF_K），rank_i 为文档在第 i 路检索结果中的名次（从 1 开始）。

优势：无需对不同检索器的原始分数做归一化，工程上稳定可靠。
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

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
        top_k: Optional[int] = None,
        relevance_threshold: Optional[float] = None,
        rewritten_query: Optional[str] = None,
    ) -> RetrievalResult:
        """
        执行检索并返回统一结果。

        query: 用于全文检索的查询文本（通常为改写后或原始问题）
        rewritten_query: 若与 query 不同，记录在结果元数据中
        """
        effective_k = top_k or settings.QA_DEFAULT_TOP_K
        threshold = (
            settings.QA_RELEVANCE_THRESHOLD
            if relevance_threshold is None
            else relevance_threshold
        )
        search_text = (query or "").strip()
        if not search_text or not targets:
            return RetrievalResult(
                hits=[],
                strategy=strategy,
                query=search_text,
                rewritten_query=rewritten_query,
                authorized_kb_ids=[str(t.kb_id) for t in targets],
            )

        vector_hits: list[RetrievalHit] = []
        fulltext_hits: list[RetrievalHit] = []

        if strategy in ("vector", "hybrid"):
            try:
                vector_hits = await vector_retriever.search(
                    search_text, targets, top_k=effective_k
                )
            except Exception as exc:  # noqa: BLE001 — 向量失败不得阻断全文路
                logger.warning("向量检索失败，将仅使用全文结果：%s", exc)
                vector_hits = []

        if strategy in ("fulltext", "hybrid"):
            try:
                fulltext_hits = await fulltext_retriever.search(
                    db, search_text, targets, top_k=effective_k
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("全文检索失败：%s", exc)
                fulltext_hits = []

        if strategy == "vector":
            merged = vector_hits
        elif strategy == "fulltext":
            merged = fulltext_hits
        else:
            # 单路有结果时直接采用该路，避免 RRF 归一化 + 阈值把唯一命中滤空
            if vector_hits and not fulltext_hits:
                merged = vector_hits
            elif fulltext_hits and not vector_hits:
                merged = fulltext_hits
            else:
                merged = self._rrf_fuse(
                    vector_hits,
                    fulltext_hits,
                    k=settings.QA_RRF_K,
                    top_k=effective_k,
                )

        before_filter = len(merged)
        filtered = self._apply_threshold(merged, threshold)
        # 软兜底：阈值过严导致全灭时，保留融合/单路排序后的前几条，避免有召回却显示「未命中」
        if not filtered and merged:
            logger.info(
                "相关性阈值 %.2f 滤空 %d 条命中，回退保留 top-%d",
                threshold,
                before_filter,
                min(effective_k, len(merged)),
            )
            filtered = merged[:effective_k]
        filtered_out = before_filter - len(filtered)

        return RetrievalResult(
            hits=filtered,
            strategy=strategy,
            query=search_text,
            rewritten_query=rewritten_query,
            authorized_kb_ids=[str(t.kb_id) for t in targets],
            vector_count=len(vector_hits),
            fulltext_count=len(fulltext_hits),
            filtered_out=filtered_out,
        )

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
    def _apply_threshold(
        hits: list[RetrievalHit], threshold: float
    ) -> list[RetrievalHit]:
        """相关性阈值截断：低于阈值的片段丢弃。"""
        if threshold <= 0:
            return hits
        return [h for h in hits if h.score >= threshold]


hybrid_retriever = HybridRetriever()

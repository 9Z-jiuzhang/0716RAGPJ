"""全文检索引擎：PostgreSQL tsvector + pg_trgm 辅助。

适用场景：精确关键词、法规条文编号、专有名词匹配。
主路径：content_tsv @@ plainto_tsquery('simple', q) + ts_rank_cd 排序；
辅助路径：当主路径召回不足时，用 ILIKE / similarity 补足（依赖 pg_trgm）。

说明：simple 配置不依赖中文分词扩展；对中文连续文本，辅助路径尤为重要。
"""

from __future__ import annotations

import logging
import math
import re
from typing import Sequence
from uuid import UUID

from sqlalchemy import Float, cast, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.retrieval.types import KBTarget, RetrievalHit

logger = logging.getLogger(__name__)


class FulltextRetriever:
    """基于 PostgreSQL 的关键词全文检索器。"""

    async def search(
        self,
        db: AsyncSession,
        query: str,
        targets: Sequence[KBTarget],
        *,
        top_k: int = 5,
    ) -> list[RetrievalHit]:
        """在授权知识库范围内执行全文检索。"""
        cleaned = (query or "").strip()
        if not cleaned or not targets:
            return []

        kb_ids = [t.kb_id for t in targets]
        # 先走 tsvector；召回不足时叠加 trigram
        hits = await self._search_tsvector(db, cleaned, kb_ids, top_k=top_k)
        if len(hits) < top_k:
            trgm_hits = await self._search_trgm(db, cleaned, kb_ids, top_k=top_k)
            hits = self._merge_by_chunk_id(hits, trgm_hits, top_k=top_k)
        return hits

    async def _search_tsvector(
        self,
        db: AsyncSession,
        query: str,
        kb_ids: Sequence[UUID],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """使用 plainto_tsquery + ts_rank_cd 检索。"""
        # 必须显式 regconfig，否则 asyncpg 会变成 varchar,varchar 重载不存在
        ts_query = func.plainto_tsquery(literal_column("'simple'::regconfig"), query)
        rank = func.ts_rank_cd(DocumentChunk.content_tsv, ts_query)

        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.kb_id,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                Document.filename,
                rank.label("rank_score"),
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.is_enabled.is_(True),
                DocumentChunk.kb_id.in_(list(kb_ids)),
                DocumentChunk.content_tsv.op("@@")(ts_query),
            )
            .order_by(rank.desc())
            .limit(top_k)
        )

        try:
            # savepoint：失败后不污染外层事务（否则 hybrid 后续 SQL 全部 aborted）
            async with db.begin_nested():
                rows = (await db.execute(stmt)).all()
        except Exception as exc:
            # content_tsv 尚未迁移时降级为空，由 trigram 路径兜底
            logger.warning("tsvector 检索失败，将尝试 trigram：%s", exc)
            return []

        return [
            RetrievalHit(
                chunk_id=str(row.id),
                doc_id=str(row.document_id),
                doc_name=row.filename or "",
                kb_id=str(row.kb_id),
                chunk_index=int(row.chunk_index),
                content=row.content or "",
                score=self._normalize_ts_rank(float(row.rank_score or 0.0)),
                source="fulltext",
                raw_score=float(row.rank_score or 0.0),
                metadata={"channel": "tsvector"},
            )
            for row in rows
        ]

    async def _search_trgm(
        self,
        db: AsyncSession,
        query: str,
        kb_ids: Sequence[UUID],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """
        pg_trgm 辅助检索：适合中文连续字符串与短关键词。

        策略：
        1. 对整句做 similarity 排序；
        2. 同时对拆出的关键词做 ILIKE 匹配，扩大召回。
        """
        tokens = self._extract_tokens(query)
        # similarity(content, query) 需要 pg_trgm
        sim = func.similarity(DocumentChunk.content, query)

        like_filters = [DocumentChunk.content.ilike(f"%{query}%")]
        for tok in tokens:
            if tok != query:
                like_filters.append(DocumentChunk.content.ilike(f"%{tok}%"))

        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.kb_id,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                Document.filename,
                cast(sim, Float).label("sim_score"),
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.is_enabled.is_(True),
                DocumentChunk.kb_id.in_(list(kb_ids)),
                or_(*like_filters),
            )
            .order_by(sim.desc())
            .limit(top_k)
        )

        try:
            async with db.begin_nested():
                rows = (await db.execute(stmt)).all()
        except Exception as exc:
            logger.warning("trigram 检索失败：%s", exc)
            # 最后降级：纯 ILIKE，无相似度分
            return await self._search_ilike_fallback(db, query, kb_ids, top_k=top_k)

        hits: list[RetrievalHit] = []
        for row in rows:
            sim_score = float(row.sim_score or 0.0)
            # 中文 similarity 往往偏低；既已 ILIKE 命中，抬到可过默认阈值的底分
            score = max(sim_score, 0.55)
            hits.append(
                RetrievalHit(
                    chunk_id=str(row.id),
                    doc_id=str(row.document_id),
                    doc_name=row.filename or "",
                    kb_id=str(row.kb_id),
                    chunk_index=int(row.chunk_index),
                    content=row.content or "",
                    score=max(0.0, min(1.0, score)),
                    source="fulltext",
                    raw_score=sim_score,
                    metadata={"channel": "trgm"},
                )
            )
        return hits

    async def _search_ilike_fallback(
        self,
        db: AsyncSession,
        query: str,
        kb_ids: Sequence[UUID],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """无 pg_trgm 时的 ILIKE 降级路径。"""
        tokens = self._extract_tokens(query)
        like_filters = [DocumentChunk.content.ilike(f"%{query}%")]
        for tok in tokens:
            if tok != query:
                like_filters.append(DocumentChunk.content.ilike(f"%{tok}%"))

        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.kb_id,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                Document.filename,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.is_enabled.is_(True),
                DocumentChunk.kb_id.in_(list(kb_ids)),
                or_(*like_filters),
            )
            .limit(top_k)
        )
        try:
            async with db.begin_nested():
                rows = (await db.execute(stmt)).all()
        except Exception as exc:
            logger.warning("ILIKE 降级检索失败：%s", exc)
            return []
        # 无真实分数时按命中顺序递减赋分，保证排序稳定
        hits: list[RetrievalHit] = []
        for i, row in enumerate(rows):
            score = max(0.55, 1.0 - i * 0.05)
            hits.append(
                RetrievalHit(
                    chunk_id=str(row.id),
                    doc_id=str(row.document_id),
                    doc_name=row.filename or "",
                    kb_id=str(row.kb_id),
                    chunk_index=int(row.chunk_index),
                    content=row.content or "",
                    score=score,
                    source="fulltext",
                    raw_score=score,
                    metadata={"channel": "ilike"},
                )
            )
        return hits

    @staticmethod
    def _extract_tokens(query: str) -> list[str]:
        """提取关键词：空白分词 + 连续中文/字母数字片段。"""
        parts = [p for p in re.split(r"\s+", query) if p]
        # 额外按标点切分
        refined: list[str] = []
        for p in parts:
            refined.extend(t for t in re.split(r"[，。；、,\.\!\?；：:]+", p) if t)
        # 去重保序，过滤过短噪声
        seen: set[str] = set()
        tokens: list[str] = []
        for t in refined:
            if len(t) < 2 or t in seen:
                continue
            seen.add(t)
            tokens.append(t)
        return tokens[:8]

    @staticmethod
    def _normalize_ts_rank(rank: float) -> float:
        """将 ts_rank_cd 分数压缩到约 (0, 1] 区间，便于与向量分比较。"""
        if rank <= 0:
            return 0.0
        # 经验映射：rank 通常较小，使用 1 - exp(-rank*4) 拉开差距
        return max(0.0, min(1.0, 1.0 - math.exp(-rank * 4.0)))

    @staticmethod
    def _merge_by_chunk_id(
        primary: list[RetrievalHit],
        secondary: list[RetrievalHit],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """合并两路全文结果，同分取高，再截断。"""
        merged: dict[str, RetrievalHit] = {h.chunk_id: h for h in primary}
        for h in secondary:
            exist = merged.get(h.chunk_id)
            if exist is None or h.score > exist.score:
                merged[h.chunk_id] = h
        ranked = sorted(merged.values(), key=lambda x: x.score, reverse=True)
        return ranked[: max(1, top_k)]


fulltext_retriever = FulltextRetriever()

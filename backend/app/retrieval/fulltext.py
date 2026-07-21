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
from collections.abc import Sequence
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
                metadata={
                    "channel": "tsvector",
                    "score_source": "normalized_ts_rank",
                },
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
            lexical_coverage = self._lexical_coverage_score(query, row.content or "")
            # 中文短查询对长文的 pg_trgm similarity 常只有 0.01 量级，直接当「相关度%」会严重偏低。
            # 字面 n-gram 覆盖率更能反映「问句关键词是否出现在片段中」。
            contains_cjk = bool(re.search(r"[\u4e00-\u9fff]", query or ""))
            if contains_cjk:
                score = max(sim_score, lexical_coverage)
            else:
                score = sim_score
            score = max(0.0, min(1.0, score))
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
                    raw_score=sim_score,
                    metadata={
                        "channel": "trgm",
                        "score_source": "pg_trgm_similarity+lexical_coverage" if contains_cjk else "pg_trgm_similarity",
                        "pg_trgm_similarity": round(sim_score, 8),
                        "lexical_coverage": round(lexical_coverage, 8),
                    },
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
            # ILIKE 没有数据库相关度排序，先多取少量候选，再按可解释的字面覆盖率排序。
            .limit(min(100, max(top_k, top_k * 4)))
        )
        try:
            async with db.begin_nested():
                rows = (await db.execute(stmt)).all()
        except Exception as exc:
            logger.warning("ILIKE 降级检索失败：%s", exc)
            return []
        # ILIKE 本身没有相关度分数，使用查询字符 n-gram 覆盖率作为可解释的
        # 字面相关度；不能再按数据库返回顺序伪造 1.00、0.95 或固定 0.55。
        hits: list[RetrievalHit] = []
        for row in rows:
            score = self._lexical_coverage_score(query, row.content or "")
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
                    metadata={
                        "channel": "ilike",
                        "score_source": "query_ngram_coverage",
                    },
                )
            )
        hits.sort(
            key=lambda hit: (
                -hit.score,
                hit.doc_id,
                hit.chunk_index,
                hit.chunk_id,
            )
        )
        return hits[: max(1, top_k)]

    @staticmethod
    def _lexical_coverage_score(query: str, content: str) -> float:
        """
        计算纯 ILIKE 降级路径的字面覆盖率，返回 0-1 区间分数。

        该值表示查询字符 n-gram 在片段中的覆盖比例，不是回答正确概率。中文使用
        二元字符组，英文和数字使用三元字符组；短查询则按完整字符串是否出现判断。
        """

        def normalize(value: str) -> str:
            # 去除空白和标点后再比较，使“年假 申请”与“年假申请”采用同一口径。
            return "".join(re.findall(r"[a-z0-9\u4e00-\u9fff]+", (value or "").casefold()))

        normalized_query = normalize(query)
        normalized_content = normalize(content)
        if not normalized_query or not normalized_content:
            return 0.0
        if len(normalized_query) <= 2:
            return 1.0 if normalized_query in normalized_content else 0.0

        contains_cjk = bool(re.search(r"[\u4e00-\u9fff]", normalized_query))
        ngram_size = 2 if contains_cjk else 3
        if len(normalized_query) < ngram_size:
            return 1.0 if normalized_query in normalized_content else 0.0

        query_ngrams = {
            normalized_query[index : index + ngram_size] for index in range(len(normalized_query) - ngram_size + 1)
        }
        if not query_ngrams:
            return 0.0
        matched = sum(1 for ngram in query_ngrams if ngram in normalized_content)
        return max(0.0, min(1.0, matched / len(query_ngrams)))

    @staticmethod
    def _extract_tokens(query: str) -> list[str]:
        """提取关键词：支持中文 n-gram，避免整句无法 ILIKE 命中。"""
        parts = [p for p in re.split(r"\s+", (query or "").strip()) if p]
        refined: list[str] = []
        for p in parts:
            refined.extend(t for t in re.split(r"[，。；、,\.\!\?？！；：:\(\)（）\[\]【】]+", p) if t)

        question_tails = (
            "是什么情况",
            "是什么意思",
            "怎么样",
            "如何办理",
            "如何申请",
            "怎么算",
            "怎么折算",
            "是多少",
            "是什么",
            "如何",
            "怎么",
            "哪些",
            "多少",
            "吗",
            "呢",
        )

        seen: set[str] = set()
        tokens: list[str] = []

        def add(token: str) -> None:
            t = (token or "").strip()
            if len(t) < 2 or t in seen:
                return
            # 过滤纯语气词
            if t in {"什么", "情况", "如何", "怎么", "是否", "可以", "需要"}:
                return
            seen.add(t)
            tokens.append(t)

        for raw in refined:
            add(raw)
            core = raw
            for tail in question_tails:
                if core.endswith(tail) and len(core) > len(tail) + 1:
                    core = core[: -len(tail)]
                    add(core)
                    break

            # 连续中文：2/3/4-gram，提升「公司年假是什么情况」类问句召回
            cjk_spans = re.findall(r"[\u4e00-\u9fff]{2,}", core or raw)
            for span in cjk_spans:
                add(span)
                for n in (2, 3, 4):
                    if len(span) < n:
                        continue
                    # 控制组合数量：取首尾与滑动窗口抽样
                    add(span[:n])
                    add(span[-n:])
                    step = 1 if len(span) <= 8 else 2
                    for i in range(0, len(span) - n + 1, step):
                        add(span[i : i + n])
                        if len(tokens) >= 28:
                            return tokens[:28]

            for m in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{1,}", raw):
                add(m)

        return tokens[:28]

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

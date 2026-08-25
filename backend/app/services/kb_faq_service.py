"""知识库级 FAQ：生成、命中、失效与热门列表。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.metrics import (
    faq_active_count,
    faq_cache_hit_total,
    faq_generation_duration_seconds,
    faq_generation_total,
    faq_semantic_hit_total,
    faq_semantic_miss_total,
)
from app.core.redis import get_redis_client
from app.core.redis_keys import kb_faq_key, kb_faq_lock_key
from app.models.base import utcnow
from app.models.document import Document, DocumentChunk
from app.models.enums import FAQStatus
from app.models.kb_faq import FAQAuditLog, KBCachedFAQ
from app.models.knowledge_base import KnowledgeBase
from app.services.llm import LLMServiceError, llm_service
from app.services.role_cache import normalize_cache_question

logger = logging.getLogger(__name__)

# 抢不到 Redis 锁时轮询等待（多实例互斥）；串行队列已保证单进程内不互踩
_FAQ_LOCK_WAIT_SECONDS = 3600
_FAQ_LOCK_POLL_SECONDS = 5
_FAQ_WORKER_IDLE_SECONDS = 300

_GENERATION_PROMPT = """你是企业知识库 FAQ 缓存生成器。
根据输入的文档片段生成可直接缓存的问题与答案。

格式：{{"items":[{{"question":"...","answer":"...","refs":[1,2]}}]}}

规则：
1. 生成{count}条高质量、互不重复的问题
2. 答案只能依据输入片段，禁止编造
3. refs必须是实际支持答案的片段编号
4. 问题应能脱离上下文独立理解
5. 禁止将人名、日期、金额泛化为标准答案模板
6. 同结构不同参数的问题应生成独立FAQ，不要合并
7. 优先生成通用性强、可能被多次问到的问题
8. 每个 question 只能包含一个疑问意图；禁止用问号/分号/“且”把多个子问题写进同一条
9. 相关但可独立提问的意图必须拆成多条 FAQ（例如进 PIP 的条件 与 PIP 通过标准 分两条）
10. 只输出 JSON，不要 Markdown 或解释
"""

_SPLIT_PROMPT = """你是企业知识库 FAQ 拆分助手。
将一条含多个子问题的 FAQ 拆成多条「一问一条」的独立 FAQ。

格式：{{"items":[{{"question":"...","answer":"..."}}]}}

规则：
1. 每个 question 只能有一个疑问意图，禁止用问号连接多个子问
2. 答案只能来自原答案改写/截取，禁止编造原文没有的事实
3. 拆成 2～5 条，覆盖原子问题的主要意图，互不重复
4. 问题应能脱离上下文独立理解
5. 只输出 JSON，不要 Markdown 或解释
"""

_Q_MARK_RE = re.compile(r"[？?]")
_INTERROG_SLOT_RE = re.compile(r"(怎么|如何|多少|几天|何种|是否|什么情况下|什么时候|标准是什么|通过标准|有几天|怎么请)")
_WEAK_COMPOUND_RE = re.compile(
    r"(分别|以及|同时).{0,48}(怎么|如何|多少|几天|何种|是否)|" r"(怎么|如何).{0,24}(和|与|及|以及).{0,24}(怎么|如何)"
)


@dataclass
class FAQMatch:
    """权限复核后的 FAQ 命中。"""

    faq_id: uuid.UUID
    kb_id: uuid.UUID
    question: str
    answer: str
    chunk_ids: list[str]
    citations: list[dict[str, Any]]
    source: str  # redis | kb_faq | kb_faq_semantic | click
    sensitivity_level: str = "normal"
    normalized_similarity: float | None = None


@dataclass
class FAQHitOutcome:
    """FAQ 查找结果：命中或因密级拒绝。"""

    match: FAQMatch | None = None
    denied: bool = False
    denied_level: str | None = None


@dataclass
class _DraftFAQ:
    question: str
    answer: str
    chunk_ids: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    quality_score: float = 0.75
    status: str = "active"


@dataclass(frozen=True)
class _FaqGenJob:
    doc_id: uuid.UUID
    kb_id: uuid.UUID | None = None
    tenant_id: str | None = None


class KBFaqService:
    """知识库 FAQ 业务门面。"""

    def __init__(self) -> None:
        # 按知识库串行：进程内队列 + 单 worker，避免假 queued 丢弃
        self._kb_queues: dict[str, asyncio.Queue[_FaqGenJob]] = {}
        self._kb_workers: dict[str, asyncio.Task[None]] = {}
        self._queue_state_lock = asyncio.Lock()
        # doc_id -> queued|running|done|error|skipped（进程内，供上传进度轮询）
        self._doc_faq_job_status: dict[str, str] = {}
        self._doc_faq_job_reason: dict[str, str] = {}

    def get_doc_faq_job_status(self, doc_id: uuid.UUID | str) -> str | None:
        return self._doc_faq_job_status.get(str(doc_id))

    def get_doc_faq_job_reason(self, doc_id: uuid.UUID | str) -> str | None:
        return self._doc_faq_job_reason.get(str(doc_id))

    def _set_doc_faq_job_status(self, doc_id: uuid.UUID | str, status: str, reason: str | None = None) -> None:
        key = str(doc_id)
        self._doc_faq_job_status[key] = status
        if reason:
            self._doc_faq_job_reason[key] = reason
        elif status in {"queued", "running", "done"}:
            self._doc_faq_job_reason.pop(key, None)

    @staticmethod
    def _cosine(a: list[float] | None, b: list[float] | None) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            fx = float(x)
            fy = float(y)
            dot += fx * fy
            na += fx * fx
            nb += fy * fy
        if na <= 0 or nb <= 0:
            return 0.0
        return dot / ((na**0.5) * (nb**0.5))

    def normalize_question(self, question: str) -> str:
        return normalize_cache_question(question)

    def question_hash(self, normalized: str) -> str:
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def classify_compound_question(question: str) -> tuple[bool, bool]:
        """判定复合题。

        Returns:
            (is_compound, strong)：strong=True 时应将 active 降为 pending_review。
        """
        q = (question or "").strip()
        if not q:
            return False, False
        marks = _Q_MARK_RE.findall(q)
        if len(marks) >= 2:
            return True, True
        if "分别" in q and len(_INTERROG_SLOT_RE.findall(q)) >= 2:
            return True, True
        if _WEAK_COMPOUND_RE.search(q):
            return True, False
        return False, False

    def apply_compound_flags(self, *, question: str, status: str) -> tuple[bool, str]:
        """根据问题文本返回 (is_compound, 可能降级后的 status)。"""
        is_compound, strong = self.classify_compound_question(question)
        next_status = status
        if strong and status == "active":
            next_status = "pending_review"
        return is_compound, next_status

    @staticmethod
    def clean_answer_for_output(answer: str) -> str:
        """出库清理：去掉模型思考标签，避免前端展示推理过程。"""
        text = answer or ""
        text = re.sub(
            r"<(?:redacted_)?thinking>.*?</(?:redacted_)?thinking>",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<思考>.*?</思考>", "", text, flags=re.DOTALL)
        text = re.sub(r"<\|.*?\|>", "", text)
        return " ".join(text.split()).strip()

    async def invalidate_kb_faq_redis(self, *, tenant_id: str, kb_id: uuid.UUID | str) -> int:
        """按 kb_id 清除 FAQ Redis 缓存。"""
        try:
            redis_client = get_redis_client()
        except Exception:  # noqa: BLE001
            return 0
        pattern = f"kb:faq:v1:{tenant_id}:{kb_id}:*"
        deleted = 0
        try:
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    deleted += int(await redis_client.delete(*keys))
                if cursor == 0:
                    break
        except Exception:  # noqa: BLE001
            logger.warning("faq redis invalidate failed kb=%s", kb_id, exc_info=True)
        return deleted

    async def check_faq_hit(
        self,
        db: AsyncSession,
        *,
        question: str,
        tenant_id: str,
        authorized_kb_ids: list[uuid.UUID],
        is_explicit_click: bool,
        message_count_in_session: int,
        has_unfinished_context: bool,
        user_max_level: str = "normal",
        user_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        debug_skip_read: bool | None = None,
    ) -> FAQHitOutcome:
        """FAQ 命中：精确匹配 Redis/DB，并按密级过滤。

        精确命中但无权：outcome.denied=True（流水线应明确提示更高权限）。
        """
        from app.models.sensitivity import normalize_sensitivity_level
        from app.services.sensitivity_service import sensitivity_service

        if not settings.FAQ_MASTER_SWITCH:
            return FAQHitOutcome()
        if debug_skip_read if debug_skip_read is not None else settings.FAQ_DEBUG_SKIP_READ:
            return FAQHitOutcome()

        authorized = [kb for kb in authorized_kb_ids if kb]
        if not authorized:
            return FAQHitOutcome()

        # 库级开关：仅查询 faq_enabled 的库
        enabled_rows = list(
            (
                await db.scalars(
                    select(KnowledgeBase.id).where(
                        KnowledgeBase.id.in_(authorized),
                        KnowledgeBase.faq_enabled.is_(True),
                        KnowledgeBase.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        authorized = list(enabled_rows)
        if not authorized:
            return FAQHitOutcome()

        normalized = self.normalize_question(question)
        if not normalized:
            return FAQHitOutcome()
        qhash = self.question_hash(normalized)

        redis_client = None
        try:
            redis_client = get_redis_client()
        except Exception:  # noqa: BLE001
            redis_client = None

        denied = False
        denied_level: str | None = None

        if redis_client is not None:
            for kb_id in authorized:
                cache_key = kb_faq_key(tenant=tenant_id, kb_id=str(kb_id), question_hash=qhash)
                try:
                    cached = await redis_client.get(cache_key)
                except Exception:  # noqa: BLE001
                    cached = None
                if not cached:
                    continue
                try:
                    data = json.loads(cached)
                except json.JSONDecodeError:
                    continue
                # 只信 DB：Redis 仅作加速；密级/启停以 KBCachedFAQ 为准
                faq_id_raw = data.get("faq_id")
                faq_row = None
                if faq_id_raw:
                    try:
                        faq_row = await db.scalar(
                            select(KBCachedFAQ).where(KBCachedFAQ.id == uuid.UUID(str(faq_id_raw)))
                        )
                    except (TypeError, ValueError):
                        faq_row = None
                if (
                    faq_row is None
                    or faq_row.kb_id != kb_id
                    or not bool(faq_row.is_active)
                    or str(faq_row.status or "") != "active"
                ):
                    try:
                        await redis_client.delete(cache_key)
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                level = normalize_sensitivity_level(getattr(faq_row, "sensitivity_level", None))
                if not sensitivity_service.can_access_level(user_max_level, level):
                    denied = True
                    denied_level = level
                    await sensitivity_service.log_access_denied(
                        db,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        question=question,
                        sensitivity_level=level,
                        source="faq",
                        conversation_id=conversation_id,
                        reason="FAQ Redis 命中但密级不足（以 DB 为准）",
                    )
                    continue
                faq_cache_hit_total.labels(source="redis").inc()
                return FAQHitOutcome(
                    match=FAQMatch(
                        faq_id=faq_row.id,
                        kb_id=kb_id,
                        question=question,
                        answer=self.clean_answer_for_output(faq_row.answer or data.get("answer") or ""),
                        chunk_ids=[str(x) for x in (faq_row.chunk_ids or data.get("chunk_ids") or [])],
                        citations=list(faq_row.citations or data.get("citations") or []),
                        source="redis",
                        sensitivity_level=level,
                    )
                )

        faqs = list(
            (
                await db.scalars(
                    select(KBCachedFAQ)
                    .where(
                        KBCachedFAQ.tenant_id == tenant_id,
                        KBCachedFAQ.normalized_question == normalized,
                        KBCachedFAQ.kb_id.in_(authorized),
                        KBCachedFAQ.is_active.is_(True),
                        KBCachedFAQ.status == "active",
                    )
                    .order_by(KBCachedFAQ.quality_score.desc(), KBCachedFAQ.hit_count.desc())
                )
            ).all()
        )

        authorized_set = set(authorized)
        for faq in faqs:
            if faq.kb_id not in authorized_set:
                logger.warning(
                    "越权命中被拦截: faq=%s kb=%s authorized=%s",
                    faq.id,
                    faq.kb_id,
                    [str(x) for x in authorized],
                )
                continue

            level = normalize_sensitivity_level(getattr(faq, "sensitivity_level", None))
            if not sensitivity_service.can_access_level(user_max_level, level):
                denied = True
                denied_level = level
                await sensitivity_service.log_access_denied(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    question=question,
                    sensitivity_level=level,
                    source="faq",
                    conversation_id=conversation_id,
                    reason="FAQ 精确命中但密级不足",
                )
                continue

            faq.hit_count = int(faq.hit_count or 0) + 1
            await db.flush()

            if redis_client is not None:
                cache_key = kb_faq_key(tenant=tenant_id, kb_id=str(faq.kb_id), question_hash=qhash)
                payload = json.dumps(
                    {
                        "answer": faq.answer,
                        "chunk_ids": faq.chunk_ids or [],
                        "citations": faq.citations or [],
                        "faq_id": str(faq.id),
                        "sensitivity_level": level,
                    },
                    ensure_ascii=False,
                )
                try:
                    await redis_client.setex(cache_key, settings.FAQ_REDIS_CACHE_TTL_SECONDS, payload)
                except Exception:  # noqa: BLE001
                    logger.debug("faq redis writeback failed", exc_info=True)

            faq_cache_hit_total.labels(source="kb_faq").inc()
            if is_explicit_click:
                faq_cache_hit_total.labels(source="click").inc()
            return FAQHitOutcome(
                match=FAQMatch(
                    faq_id=faq.id,
                    kb_id=faq.kb_id,
                    question=faq.question,
                    answer=self.clean_answer_for_output(faq.answer or ""),
                    chunk_ids=[str(x) for x in (faq.chunk_ids or [])],
                    citations=list(faq.citations or []),
                    source="kb_faq",
                    sensitivity_level=level,
                )
            )

        # 精确未命中：语义近义命中（A1）
        if settings.FAQ_SEMANTIC_HIT_ENABLED:
            semantic = await self._semantic_faq_hit(
                db,
                question=question,
                tenant_id=tenant_id,
                authorized=authorized,
                user_max_level=user_max_level,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if semantic.match is not None:
                if is_explicit_click:
                    faq_cache_hit_total.labels(source="click").inc()
                return semantic
            if semantic.denied:
                denied = True
                denied_level = semantic.denied_level or denied_level
            else:
                faq_semantic_miss_total.inc()

        return FAQHitOutcome(denied=denied, denied_level=denied_level)

    async def _semantic_faq_hit(
        self,
        db: AsyncSession,
        *,
        question: str,
        tenant_id: str,
        authorized: list[uuid.UUID],
        user_max_level: str,
        user_id: uuid.UUID | None,
        conversation_id: uuid.UUID | None,
    ) -> FAQHitOutcome:
        from app.models.sensitivity import normalize_sensitivity_level
        from app.services.embedding import EmbeddingServiceError, embedding_service
        from app.services.sensitivity_service import sensitivity_service

        try:
            query_vec = await embedding_service.embed_query(question)
        except EmbeddingServiceError:
            logger.warning("faq semantic embed_query failed", exc_info=True)
            return FAQHitOutcome()
        except Exception:  # noqa: BLE001
            logger.warning("faq semantic embed_query unexpected error", exc_info=True)
            return FAQHitOutcome()

        candidates = list(
            (
                await db.scalars(
                    select(KBCachedFAQ)
                    .where(
                        KBCachedFAQ.tenant_id == tenant_id,
                        KBCachedFAQ.kb_id.in_(authorized),
                        KBCachedFAQ.is_active.is_(True),
                        KBCachedFAQ.status == FAQStatus.ACTIVE.value,
                        KBCachedFAQ.embedding.is_not(None),
                    )
                    .order_by(KBCachedFAQ.hit_count.desc())
                    .limit(max(1, settings.FAQ_SEMANTIC_CANDIDATE_LIMIT))
                )
            ).all()
        )
        best: KBCachedFAQ | None = None
        best_sim = -1.0
        denied = False
        denied_level: str | None = None
        for faq in candidates:
            sim = self._cosine(query_vec, list(faq.embedding) if faq.embedding else None)
            if sim < settings.FAQ_SIMILARITY_THRESHOLD:
                continue
            level = normalize_sensitivity_level(getattr(faq, "sensitivity_level", None))
            if not sensitivity_service.can_access_level(user_max_level, level):
                denied = True
                denied_level = level
                await sensitivity_service.log_access_denied(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    question=question,
                    sensitivity_level=level,
                    source="faq",
                    conversation_id=conversation_id,
                    reason="FAQ 语义命中但密级不足",
                )
                continue
            if sim > best_sim:
                best_sim = sim
                best = faq

        if best is None:
            return FAQHitOutcome(denied=denied, denied_level=denied_level)

        best.hit_count = int(best.hit_count or 0) + 1
        await db.flush()
        level = normalize_sensitivity_level(getattr(best, "sensitivity_level", None))
        faq_cache_hit_total.labels(source="kb_faq_semantic").inc()
        faq_semantic_hit_total.inc()
        return FAQHitOutcome(
            match=FAQMatch(
                faq_id=best.id,
                kb_id=best.kb_id,
                question=best.question,
                answer=self.clean_answer_for_output(best.answer or ""),
                chunk_ids=[str(x) for x in (best.chunk_ids or [])],
                citations=list(best.citations or []),
                source="kb_faq_semantic",
                sensitivity_level=level,
                normalized_similarity=best_sim,
            )
        )

    async def list_semantic_candidates_for_cache(
        self,
        db: AsyncSession,
        *,
        question: str,
        tenant_id: str,
        authorized_kb_ids: list[uuid.UUID],
        user_max_level: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """供 L3 语义 QA 缓存注入候选（A2）；不含写入 hit_count。"""
        from app.models.sensitivity import normalize_sensitivity_level
        from app.services.embedding import EmbeddingServiceError, embedding_service
        from app.services.sensitivity_service import sensitivity_service

        if not authorized_kb_ids:
            return []
        try:
            query_vec = await embedding_service.embed_query(question)
        except Exception:  # noqa: BLE001
            logger.warning("L3 faq candidate embed failed", exc_info=True)
            return []

        rows = list(
            (
                await db.scalars(
                    select(KBCachedFAQ)
                    .where(
                        KBCachedFAQ.tenant_id == tenant_id,
                        KBCachedFAQ.kb_id.in_(authorized_kb_ids),
                        KBCachedFAQ.is_active.is_(True),
                        KBCachedFAQ.status == FAQStatus.ACTIVE.value,
                        KBCachedFAQ.embedding.is_not(None),
                    )
                    .limit(max(1, settings.FAQ_SEMANTIC_CANDIDATE_LIMIT))
                )
            ).all()
        )
        scored: list[tuple[float, KBCachedFAQ]] = []
        for faq in rows:
            sim = self._cosine(query_vec, list(faq.embedding) if faq.embedding else None)
            if sim <= 0:
                continue
            scored.append((sim, faq))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[dict[str, Any]] = []
        for sim, faq in scored[: max(1, limit)]:
            level = normalize_sensitivity_level(getattr(faq, "sensitivity_level", None))
            out.append(
                {
                    "id": str(faq.id),
                    "answer": self.clean_answer_for_output(faq.answer or ""),
                    "citations": list(faq.citations or []),
                    "citation_ids": [str(x) for x in (faq.chunk_ids or [])],
                    "normalized_similarity": sim,
                    "quality_score": float(faq.quality_score or 0),
                    "permission_ok": sensitivity_service.can_access_level(user_max_level, level),
                    "disabled": False,
                    "high_risk": False,
                }
            )
        return out

    async def generate_from_document(
        self,
        doc_id: uuid.UUID,
        *,
        kb_id: uuid.UUID | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """文档就绪后异步生成 FAQ；不阻塞 ready 状态。"""
        if not settings.FAQ_GENERATION_ENABLED or settings.FAQ_DEBUG_SKIP_WRITE:
            return {"status": "skipped", "reason": "generation_disabled"}

        if not (settings.LLM_API_KEY or "").strip():
            logger.info("FAQ generation skipped: LLM_API_KEY missing doc=%s", doc_id)
            faq_generation_total.labels(status="skipped_no_llm").inc()
            self._set_doc_faq_job_status(doc_id, "skipped", "no_llm_key")
            return {"status": "skipped", "reason": "no_llm_key"}

        started = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            doc = await db.scalar(select(Document).where(Document.id == doc_id))
            if not doc:
                self._set_doc_faq_job_status(doc_id, "skipped", "document_not_found")
                return {"status": "skipped", "reason": "document_not_found"}
            if doc.status != "ready":
                self._set_doc_faq_job_status(doc_id, "skipped", "document_not_ready")
                return {"status": "skipped", "reason": "document_not_ready"}

            resolved_kb = kb_id or doc.kb_id
            resolved_tenant = tenant_id or settings.FAQ_TENANT_ID
            # 重生前清掉该库 FAQ Redis，避免旧答案脏读
            await self.invalidate_kb_faq_redis(tenant_id=resolved_tenant, kb_id=resolved_kb)
            kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == resolved_kb))
            if kb is None or kb.deleted_at is not None:
                self._set_doc_faq_job_status(doc_id, "skipped", "kb_missing")
                return {"status": "skipped", "reason": "kb_missing"}

            chunks = list(
                (
                    await db.scalars(
                        select(DocumentChunk)
                        .where(
                            DocumentChunk.document_id == doc_id,
                            DocumentChunk.is_enabled.is_(True),
                        )
                        .order_by(DocumentChunk.chunk_index.asc())
                    )
                ).all()
            )
            # 短文档也要生成：只要有 ≥1 段非空内容即可（不再要求 ≥3 段）
            content_chunks = [c for c in chunks if (c.content or "").strip()]
            if not content_chunks:
                faq_generation_total.labels(status="skipped_content").inc()
                self._set_doc_faq_job_status(doc_id, "skipped", "no_content_chunks")
                return {"status": "skipped", "reason": "no_content_chunks"}
            chunks = content_chunks

            today_count = await self._today_generation_count(db, resolved_kb)
            if today_count >= settings.FAQ_KB_DAILY_LIMIT:
                faq_generation_total.labels(status="rate_limited").inc()
                self._set_doc_faq_job_status(doc_id, "skipped", "daily_limit_reached")
                return {"status": "rate_limited", "reason": "daily_limit_reached"}

            active_count = await db.scalar(
                select(func.count())
                .select_from(KBCachedFAQ)
                .where(
                    KBCachedFAQ.kb_id == resolved_kb,
                    KBCachedFAQ.is_active.is_(True),
                    KBCachedFAQ.status.in_(["active", "pending_review"]),
                )
            )
            if int(active_count or 0) >= settings.FAQ_PER_KB_LIMIT:
                self._set_doc_faq_job_status(doc_id, "skipped", "kb_limit_reached")
                return {"status": "rate_limited", "reason": "kb_limit_reached"}

            lock_key = kb_faq_lock_key(tenant=resolved_tenant, kb_id=str(resolved_kb))
            if not await self._acquire_lock_with_wait(lock_key, wait_seconds=_FAQ_LOCK_WAIT_SECONDS):
                logger.warning(
                    "FAQ锁等待超时仍未获得 doc=%s kb=%s",
                    doc_id,
                    resolved_kb,
                )
                return {"status": "error", "reason": "lock_wait_timeout"}

            try:
                target_count = self._faq_target_for_document(chunks)
                generated: list[_DraftFAQ] = []
                logger.info(
                    "开始生成FAQ doc=%s kb=%s target=%s chunks=%s",
                    doc_id,
                    resolved_kb,
                    target_count,
                    len(chunks),
                )
                per_batch = min(5, max(3, target_count))
                for batch in self._chunk_batches(chunks, settings.FAQ_DOCUMENT_CHUNK_BATCH_SIZE):
                    if len(generated) >= target_count:
                        break
                    remain = target_count - len(generated)
                    batch_faqs = await self._generate_batch_with_retry(
                        batch,
                        doc=doc,
                        count=min(remain, per_batch),
                    )
                    generated.extend(batch_faqs)

                unique = await self._deduplicate(db, generated, resolved_kb)
                saved = 0
                for faq in unique:
                    if self._contains_sensitive(faq.answer) or self._contains_sensitive(faq.question):
                        faq.status = "pending_review"
                    if faq.quality_score < settings.FAQ_QUALITY_THRESHOLD and faq.status != "pending_review":
                        continue
                    is_compound, status = self.apply_compound_flags(question=faq.question, status=faq.status)
                    await self._upsert_faq(
                        db,
                        tenant_id=resolved_tenant,
                        kb_id=resolved_kb,
                        question=faq.question,
                        answer=faq.answer,
                        source_document_ids=[str(doc_id)],
                        chunk_ids=faq.chunk_ids,
                        citations=faq.citations,
                        quality_score=faq.quality_score,
                        source="document_auto",
                        status=status,
                        model_version=settings.LLM_MODEL,
                        is_compound=is_compound,
                    )
                    saved += 1

                await db.commit()
                faq_generation_total.labels(status="success").inc()
                faq_active_count.set(
                    float(
                        await db.scalar(
                            select(func.count())
                            .select_from(KBCachedFAQ)
                            .where(
                                KBCachedFAQ.kb_id == resolved_kb,
                                KBCachedFAQ.is_active.is_(True),
                                KBCachedFAQ.status == "active",
                            )
                        )
                        or 0
                    )
                )
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                faq_generation_duration_seconds.observe(elapsed)
                logger.info(
                    "FAQ生成完成 doc=%s kb=%s generated=%s saved=%s elapsed=%.1fs",
                    doc_id,
                    resolved_kb,
                    len(unique),
                    saved,
                    elapsed,
                )
                try:
                    from app.services.faq_verify_service import faq_verify_service

                    await faq_verify_service.enqueue_for_document(doc_id)
                except Exception:  # noqa: BLE001
                    logger.warning("faq verify enqueue after generate failed doc=%s", doc_id, exc_info=True)
                return {
                    "status": "success",
                    "generated": len(unique),
                    "saved": saved,
                    "kb_id": str(resolved_kb),
                    "doc_id": str(doc_id),
                }
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                faq_generation_total.labels(status="error").inc()
                logger.exception("FAQ generation failed doc=%s: %s", doc_id, exc)
                self._set_doc_faq_job_status(doc_id, "error", str(exc)[:200])
                return {"status": "error", "reason": str(exc)[:200]}
            finally:
                await self._release_lock(lock_key)

    async def enqueue_document(
        self,
        doc_id: uuid.UUID,
        *,
        kb_id: uuid.UUID | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """将单文档 FAQ 生成放入对应知识库串行队列（不丢弃）。"""
        if not settings.FAQ_GENERATION_ENABLED:
            self._set_doc_faq_job_status(doc_id, "skipped")
            return
        resolved_kb = kb_id
        if resolved_kb is None:
            async with SessionLocal() as db:
                resolved_kb = await db.scalar(select(Document.kb_id).where(Document.id == doc_id))
        if resolved_kb is None:
            logger.warning("FAQ入队跳过：文档不存在或不属于知识库 doc=%s", doc_id)
            self._set_doc_faq_job_status(doc_id, "skipped")
            return
        self._set_doc_faq_job_status(doc_id, "queued")
        await self._put_faq_job(
            _FaqGenJob(
                doc_id=doc_id,
                kb_id=resolved_kb,
                tenant_id=tenant_id or settings.FAQ_TENANT_ID,
            )
        )

    async def enqueue_generation(
        self,
        *,
        kb_id: uuid.UUID,
        tenant_id: str,
        document_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        """为知识库内文档排队生成；返回 task_id 与 document_count。"""
        task_id = str(uuid.uuid4())
        async with SessionLocal() as db:
            stmt = select(Document.id).where(
                Document.kb_id == kb_id,
                Document.status == "ready",
            )
            if document_ids:
                stmt = stmt.where(Document.id.in_(document_ids))
            doc_ids = list((await db.scalars(stmt.limit(200))).all())
        for doc_id in doc_ids:
            await self.enqueue_document(doc_id, kb_id=kb_id, tenant_id=tenant_id)
        logger.info(
            "FAQ批次已入队 task=%s kb=%s docs=%s",
            task_id,
            kb_id,
            len(doc_ids),
        )
        return {"task_id": task_id, "document_count": len(doc_ids)}

    async def _put_faq_job(self, job: _FaqGenJob) -> None:
        kb_key = str(job.kb_id)
        async with self._queue_state_lock:
            queue = self._kb_queues.get(kb_key)
            if queue is None:
                queue = asyncio.Queue()
                self._kb_queues[kb_key] = queue
            worker = self._kb_workers.get(kb_key)
            if worker is None or worker.done():
                self._kb_workers[kb_key] = asyncio.create_task(
                    self._kb_faq_worker(kb_key),
                    name=f"kb-faq-worker-{kb_key}",
                )
        await queue.put(job)
        logger.info(
            "FAQ已入队 doc=%s kb=%s pending≈%s",
            job.doc_id,
            kb_key,
            queue.qsize(),
        )

    async def _kb_faq_worker(self, kb_key: str) -> None:
        """按知识库串行消费 FAQ 生成任务。"""
        queue = self._kb_queues.get(kb_key)
        if queue is None:
            return
        logger.info("FAQ worker 启动 kb=%s", kb_key)
        try:
            while True:
                try:
                    job = await asyncio.wait_for(queue.get(), timeout=_FAQ_WORKER_IDLE_SECONDS)
                except asyncio.TimeoutError:
                    async with self._queue_state_lock:
                        if queue.empty():
                            self._kb_workers.pop(kb_key, None)
                            logger.info("FAQ worker 空闲退出 kb=%s", kb_key)
                            return
                    continue
                self._set_doc_faq_job_status(job.doc_id, "running")
                try:
                    result = await self.generate_from_document(
                        job.doc_id,
                        kb_id=job.kb_id,
                        tenant_id=job.tenant_id,
                    )
                    status = str(result.get("status") or "done")
                    reason = str(result.get("reason") or "") or None
                    if status == "error":
                        self._set_doc_faq_job_status(job.doc_id, "error", reason)
                    elif status in ("skipped", "rate_limited"):
                        self._set_doc_faq_job_status(job.doc_id, "skipped", reason)
                    else:
                        self._set_doc_faq_job_status(job.doc_id, "done")
                    logger.info(
                        "FAQ队列任务完成 doc=%s kb=%s status=%s saved=%s",
                        job.doc_id,
                        kb_key,
                        result.get("status"),
                        result.get("saved"),
                    )
                except Exception:  # noqa: BLE001
                    self._set_doc_faq_job_status(job.doc_id, "error")
                    logger.exception("FAQ队列任务异常 doc=%s kb=%s", job.doc_id, kb_key)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            logger.info("FAQ worker 已取消 kb=%s", kb_key)
            raise

    async def _acquire_lock_with_wait(self, lock_key: str, *, wait_seconds: int) -> bool:
        """轮询抢锁，避免「假 queued」直接丢弃。"""
        deadline = max(0, int(wait_seconds))
        waited = 0
        while waited <= deadline:
            if await self._acquire_lock(lock_key, timeout=_FAQ_LOCK_WAIT_SECONDS):
                if waited:
                    logger.info("FAQ锁等待成功 key=%s waited=%ss", lock_key, waited)
                return True
            if waited >= deadline:
                break
            await asyncio.sleep(_FAQ_LOCK_POLL_SECONDS)
            waited += _FAQ_LOCK_POLL_SECONDS
        return False

    async def list_hot(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        kb_ids: list[uuid.UUID],
        limit: int = 8,
        page: int = 1,
        sort: str = "random",
        seed: int | None = None,
        user_max_level: str | None = None,
    ) -> list[KBCachedFAQ]:
        if not kb_ids:
            return []
        from app.models.sensitivity import levels_at_or_below, normalize_sensitivity_level

        offset = max(0, (page - 1) * limit)
        allowed = levels_at_or_below(normalize_sensitivity_level(user_max_level or "normal"))
        base = (
            select(KBCachedFAQ)
            .where(
                KBCachedFAQ.tenant_id == tenant_id,
                KBCachedFAQ.kb_id.in_(kb_ids),
                KBCachedFAQ.is_active.is_(True),
                KBCachedFAQ.status == "active",
                KBCachedFAQ.sensitivity_level.in_(allowed),
            )
            .limit(limit)
            .offset(offset)
        )
        if sort == "hit":
            base = base.order_by(KBCachedFAQ.hit_count.desc(), KBCachedFAQ.updated_at.desc())
        elif sort == "quality":
            base = base.order_by(KBCachedFAQ.quality_score.desc(), KBCachedFAQ.hit_count.desc())
        else:
            # 稳定伪随机：md5(id||seed)
            seed_val = int(seed or 0)
            base = base.order_by(text("md5(kb_cached_faqs.id::text || :seed)")).params(seed=str(seed_val))
        return list((await db.scalars(base)).all())

    async def prune_by_document(self, db: AsyncSession, *, doc_id: uuid.UUID, kb_id: uuid.UUID) -> int:
        """文档删除后：移出引用该文档的 FAQ；无剩余来源则删除该 FAQ。"""
        rows = list(
            (
                await db.scalars(
                    select(KBCachedFAQ).where(
                        KBCachedFAQ.kb_id == kb_id,
                        KBCachedFAQ.source_document_ids.contains([str(doc_id)]),
                    )
                )
            ).all()
        )
        affected = 0
        for row in rows:
            docs = [str(x) for x in (row.source_document_ids or []) if str(x) != str(doc_id)]
            if docs:
                row.source_document_ids = docs
                affected += 1
                continue
            await db.delete(row)
            affected += 1
        if affected:
            await db.flush()
            await self.invalidate_kb_faq_redis(tenant_id=settings.FAQ_TENANT_ID, kb_id=kb_id)
        return affected

    async def mark_stale_by_version(
        self,
        db: AsyncSession,
        *,
        kb_ids: list[uuid.UUID] | None,
        stale_reason: str,
        model_version: str | None,
    ) -> int:
        stmt = (
            update(KBCachedFAQ)
            .where(KBCachedFAQ.is_active.is_(True))
            .values(
                is_active=False,
                status="disabled",
                stale_reason=stale_reason,
                model_version=model_version,
                updated_at=utcnow(),
            )
        )
        if kb_ids:
            stmt = stmt.where(KBCachedFAQ.kb_id.in_(kb_ids))
        result = await db.execute(stmt)
        await db.flush()
        if kb_ids:
            for kid in kb_ids:
                await self.invalidate_kb_faq_redis(tenant_id=settings.FAQ_TENANT_ID, kb_id=kid)
        else:
            # 全量标失效：按租户前缀清 FAQ Redis
            try:
                redis_client = get_redis_client()
                pattern = f"kb:faq:v1:{settings.FAQ_TENANT_ID}:*"
                cursor = 0
                while True:
                    cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=200)
                    if keys:
                        await redis_client.delete(*keys)
                    if cursor == 0:
                        break
            except Exception:  # noqa: BLE001
                logger.warning("faq redis tenant invalidate failed", exc_info=True)
        return int(result.rowcount or 0)

    async def record_reject(self, db: AsyncSession, *, faq_id: uuid.UUID) -> None:
        faq = await db.scalar(select(KBCachedFAQ).where(KBCachedFAQ.id == faq_id))
        if faq is None:
            return
        faq.reject_count = int(faq.reject_count or 0) + 1
        if faq.reject_count >= settings.FAQ_REJECT_DISABLE_THRESHOLD:
            faq.is_active = False
            faq.status = "disabled"
            faq.stale_reason = "user_rejects"
            await self.invalidate_kb_faq_redis(tenant_id=faq.tenant_id or settings.FAQ_TENANT_ID, kb_id=faq.kb_id)
        await db.flush()

    async def get_stats(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        kb_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """按库/租户从 DB 汇总 FAQ 统计（不走 Prometheus 高基数标签）。"""
        filters = [KBCachedFAQ.tenant_id == tenant_id]
        if kb_id is not None:
            filters.append(KBCachedFAQ.kb_id == kb_id)
        total = int(await db.scalar(select(func.count()).select_from(KBCachedFAQ).where(*filters)) or 0)
        active = int(
            await db.scalar(
                select(func.count())
                .select_from(KBCachedFAQ)
                .where(*filters, KBCachedFAQ.status == "active", KBCachedFAQ.is_active.is_(True))
            )
            or 0
        )
        pending = int(
            await db.scalar(
                select(func.count()).select_from(KBCachedFAQ).where(*filters, KBCachedFAQ.status == "pending_review")
            )
            or 0
        )
        disabled = int(
            await db.scalar(
                select(func.count()).select_from(KBCachedFAQ).where(*filters, KBCachedFAQ.status == "disabled")
            )
            or 0
        )
        hit_sum = await db.scalar(select(func.coalesce(func.sum(KBCachedFAQ.hit_count), 0)).where(*filters))
        return {
            "total": total,
            "active": active,
            "pending_review": pending,
            "disabled": disabled,
            "total_hits": int(hit_sum or 0),
            "kb_id": str(kb_id) if kb_id else None,
        }

    async def write_audit(
        self,
        db: AsyncSession,
        *,
        action: str,
        tenant_id: str,
        operator_id: uuid.UUID | None = None,
        target_id: uuid.UUID | None = None,
        target_ids: list[str] | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
    ) -> None:
        db.add(
            FAQAuditLog(
                tenant_id=tenant_id,
                action=action,
                operator_id=operator_id,
                target_id=target_id,
                target_ids=target_ids,
                old_value=old_value,
                new_value=new_value,
            )
        )

    async def _today_generation_count(self, db: AsyncSession, kb_id: uuid.UUID) -> int:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        count = await db.scalar(
            select(func.count())
            .select_from(KBCachedFAQ)
            .where(
                KBCachedFAQ.kb_id == kb_id,
                KBCachedFAQ.source == "document_auto",
                KBCachedFAQ.created_at >= start,
            )
        )
        return int(count or 0)

    async def _acquire_lock(self, lock_key: str, timeout: int) -> bool:
        try:
            redis = get_redis_client()
            ok = await redis.set(lock_key, "1", nx=True, ex=timeout)
            return bool(ok)
        except Exception:  # noqa: BLE001
            logger.warning("FAQ lock acquire failed, proceed single-instance fallback", exc_info=True)
            return True

    async def _release_lock(self, lock_key: str) -> None:
        try:
            redis = get_redis_client()
            await redis.delete(lock_key)
        except Exception:  # noqa: BLE001
            logger.debug("FAQ lock release failed", exc_info=True)

    def _chunk_batches(self, chunks: list[DocumentChunk], batch_size: int) -> list[list[DocumentChunk]]:
        size = max(1, batch_size)
        return [chunks[i : i + size] for i in range(0, len(chunks), size)]

    @staticmethod
    def _faq_target_for_document(chunks: list[DocumentChunk]) -> int:
        """按文档规模缩放目标条数：短文少生成，长文仍受 FAQ_PER_DOCUMENT_COUNT 上限。"""
        cap = max(1, int(settings.FAQ_PER_DOCUMENT_COUNT or 25))
        n = len(chunks)
        total_chars = sum(len((c.content or "").strip()) for c in chunks)
        if total_chars < 200:
            scaled = 2
        elif total_chars < 600 or n <= 1:
            scaled = 4
        elif total_chars < 1500 or n <= 3:
            scaled = 8
        elif n <= 8:
            scaled = max(10, n * 2)
        else:
            scaled = cap
        return max(1, min(cap, scaled))

    async def _generate_batch_with_retry(
        self,
        chunks: list[DocumentChunk],
        *,
        doc: Document,
        count: int,
    ) -> list[_DraftFAQ]:
        materials = []
        for index, chunk in enumerate(chunks, start=1):
            materials.append(
                {
                    "ref": index,
                    "doc_id": str(doc.id),
                    "doc_name": doc.filename or "",
                    "chunk_id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "content": (chunk.content or "")[: settings.FAQ_DOCUMENT_CHARS_PER_CHUNK],
                }
            )
        prompt = _GENERATION_PROMPT.format(count=count)
        from app.services.model_concurrency import model_concurrency_gate

        for attempt in range(2):
            acquired = await model_concurrency_gate.acquire()
            if not acquired:
                logger.warning("FAQ LLM skipped: model concurrency gate busy doc=%s", doc.id)
                return []
            try:
                raw = await llm_service.chat(
                    [
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"count": count, "materials": materials},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=settings.FAQ_LLM_MAX_TOKENS,
                )
                faqs = self._parse_and_validate(raw, materials)
                if faqs and all(f.answer and len(f.answer) > 10 for f in faqs):
                    return faqs
            except LLMServiceError as exc:
                logger.error("FAQ LLM failed attempt=%s: %s", attempt + 1, exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("FAQ generate failed attempt=%s: %s", attempt + 1, exc)
            finally:
                model_concurrency_gate.release()
        return []

    def _parse_and_validate(self, raw: str, materials: list[dict[str, Any]]) -> list[_DraftFAQ]:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                return []
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                return []
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        by_ref = {int(m["ref"]): m for m in materials}
        out: list[_DraftFAQ] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            refs = item.get("refs") or []
            if not question or not answer or len(answer) <= 10:
                continue
            valid_refs = []
            for r in refs:
                try:
                    ri = int(r)
                except (TypeError, ValueError):
                    continue
                if ri in by_ref:
                    valid_refs.append(ri)
            if not valid_refs:
                continue
            citations = []
            chunk_ids = []
            for ri in valid_refs[:3]:
                m = by_ref[ri]
                chunk_ids.append(m["chunk_id"])
                citations.append(
                    {
                        "doc_id": m["doc_id"],
                        "doc_name": m["doc_name"],
                        "chunk_index": m["chunk_index"],
                        "chunk_id": m["chunk_id"],
                        "content": m["content"][:500],
                        "score": 1.0,
                        "source": "kb_faq",
                    }
                )
            out.append(
                _DraftFAQ(
                    question=question[:500],
                    answer=answer[:4000],
                    chunk_ids=chunk_ids,
                    citations=citations,
                    quality_score=0.78 if len(valid_refs) >= 2 else 0.72,
                )
            )
        return out

    def _contains_sensitive(self, text: str) -> bool:
        for pattern in settings.FAQ_SENSITIVE_PATTERNS:
            try:
                if re.search(pattern, text or ""):
                    return True
            except re.error:
                continue
        return False

    def _similarity(self, q1: str, q2: str) -> float:
        n1 = self.normalize_question(q1)
        n2 = self.normalize_question(q2)
        if n1 == n2:
            return 1.0
        dist = self._levenshtein(n1, n2)
        max_len = max(len(n1), len(n2))
        edit_sim = 1 - (dist / max_len) if max_len else 0.0
        chars1, chars2 = set(n1), set(n2)
        jaccard = len(chars1 & chars2) / len(chars1 | chars2) if chars1 | chars2 else 0.0
        return 0.4 * edit_sim + 0.6 * jaccard

    def _levenshtein(self, s1: str, s2: str) -> int:
        if len(s1) < len(s2):
            return self._levenshtein(s2, s1)
        if not s2:
            return len(s1)
        previous = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current = [i + 1]
            for j, c2 in enumerate(s2):
                current.append(
                    min(
                        previous[j + 1] + 1,
                        current[j] + 1,
                        previous[j] + (c1 != c2),
                    )
                )
            previous = current
        return previous[-1]

    async def _deduplicate(
        self,
        db: AsyncSession,
        faqs: list[_DraftFAQ],
        kb_id: uuid.UUID,
    ) -> list[_DraftFAQ]:
        threshold = settings.FAQ_SIMILARITY_THRESHOLD
        existing = list(
            (
                await db.scalars(
                    select(KBCachedFAQ.question).where(
                        KBCachedFAQ.kb_id == kb_id,
                        KBCachedFAQ.is_active.is_(True),
                    )
                )
            ).all()
        )
        unique: list[_DraftFAQ] = []
        for faq in faqs:
            duplicate = False
            for exist_q in existing:
                if self._similarity(faq.question, exist_q) > threshold:
                    duplicate = True
                    break
            if not duplicate:
                for kept in unique:
                    if self._similarity(faq.question, kept.question) > threshold:
                        kept.answer = faq.answer
                        kept.quality_score = faq.quality_score
                        kept.chunk_ids = faq.chunk_ids
                        kept.citations = faq.citations
                        kept.status = faq.status
                        duplicate = True
                        break
            if not duplicate:
                unique.append(faq)
        return unique

    async def _upsert_faq(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        kb_id: uuid.UUID,
        question: str,
        answer: str,
        source_document_ids: list[str],
        chunk_ids: list[str],
        citations: list[dict[str, Any]],
        quality_score: float,
        source: str,
        status: str = "active",
        model_version: str | None = None,
        stale_reason: str | None = None,
        is_compound: bool | None = None,
    ) -> None:
        normalized = self.normalize_question(question)
        if not normalized:
            return
        from app.models.knowledge_base import KnowledgeBase
        from app.models.sensitivity import LEVEL_ORDER, normalize_sensitivity_level

        if is_compound is None:
            is_compound, status = self.apply_compound_flags(question=question, status=status)
        sens_level: str | None = None
        if source_document_ids:
            try:
                doc_ids = [uuid.UUID(str(x)) for x in source_document_ids]
                docs = list((await db.scalars(select(Document).where(Document.id.in_(doc_ids)))).all())
                if docs:
                    sens_level = max(
                        (normalize_sensitivity_level(getattr(d, "sensitivity_level", None)) for d in docs),
                        key=lambda lv: LEVEL_ORDER.get(lv, 0),
                    )
            except Exception:  # noqa: BLE001
                sens_level = None
        if sens_level is None:
            kb_row = await db.get(KnowledgeBase, kb_id)
            sens_level = normalize_sensitivity_level(
                getattr(kb_row, "default_sensitivity_level", None) if kb_row else None
            )
        values = {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "kb_id": kb_id,
            "question": question,
            "normalized_question": normalized,
            "answer": self.clean_answer_for_output(answer),
            "source_document_ids": source_document_ids,
            "chunk_ids": chunk_ids,
            "citations": citations,
            "quality_score": quality_score,
            "source": source,
            "status": status,
            "is_active": status != "disabled",
            "model_version": model_version,
            "stale_reason": stale_reason,
            "hit_count": 0,
            "reject_count": 0,
            "version": 1,
            "sensitivity_level": sens_level,
            "is_compound": bool(is_compound),
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        embedding_vec: list[float] | None = None
        try:
            from app.services.embedding import embedding_service

            embedding_vec = await embedding_service.embed_query(question)
            values["embedding"] = embedding_vec
        except Exception:  # noqa: BLE001
            logger.warning("faq embedding on upsert failed q=%s", question[:80], exc_info=True)

        cleaned_answer = values["answer"]
        conflict_set: dict[str, Any] = {
            "question": question,
            "answer": cleaned_answer,
            "source_document_ids": source_document_ids,
            "chunk_ids": chunk_ids,
            "citations": citations,
            "quality_score": quality_score,
            "source": source,
            "status": status,
            "is_active": status != "disabled",
            "model_version": model_version,
            "stale_reason": stale_reason,
            "sensitivity_level": sens_level,
            "is_compound": bool(is_compound),
            "updated_at": utcnow(),
            "version": KBCachedFAQ.version + 1,
        }
        if embedding_vec is not None:
            conflict_set["embedding"] = embedding_vec
        stmt = insert(KBCachedFAQ).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["kb_id", "normalized_question"],
            set_=conflict_set,
        )
        await db.execute(stmt)

    async def refresh_faq_embedding(self, db: AsyncSession, faq: KBCachedFAQ) -> None:
        """问题变更后刷新 embedding。"""
        try:
            from app.services.embedding import embedding_service

            faq.embedding = await embedding_service.embed_query(faq.question or "")
        except Exception:  # noqa: BLE001
            logger.warning("faq embedding refresh failed id=%s", faq.id, exc_info=True)

    async def split_compound_faq(
        self,
        db: AsyncSession,
        *,
        faq: KBCachedFAQ,
        operator_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        """LLM 将复合 FAQ 拆成多条单问；父条停用并记 faq_split 审计。"""
        raw_children = await self._split_via_llm(faq.question or "", faq.answer or "")
        if len(raw_children) < 2:
            raise ValueError("拆分结果不足 2 条，请编辑后重试或手工拆分")

        parent_snapshot = {
            "id": str(faq.id),
            "question": faq.question,
            "answer": faq.answer,
            "status": faq.status,
            "is_compound": bool(getattr(faq, "is_compound", False)),
        }
        source_docs = [str(x) for x in (faq.source_document_ids or [])]
        chunk_ids = [str(x) for x in (faq.chunk_ids or [])]
        citations = list(faq.citations or [])
        sens = getattr(faq, "sensitivity_level", None) or "normal"

        created: list[dict[str, Any]] = []
        for item in raw_children:
            question = str(item.get("question") or "").strip()[:500]
            answer = self.clean_answer_for_output(str(item.get("answer") or "").strip())[:4000]
            if not question or len(answer) <= 10:
                continue
            is_compound, status = self.apply_compound_flags(question=question, status="active")
            child = KBCachedFAQ(
                tenant_id=faq.tenant_id,
                kb_id=faq.kb_id,
                question=question,
                normalized_question=self.normalize_question(question),
                answer=answer,
                source_document_ids=source_docs,
                chunk_ids=chunk_ids,
                citations=citations,
                quality_score=float(faq.quality_score or 0.75),
                hit_count=0,
                reject_count=0,
                status=status,
                source="refined",
                is_active=status != "disabled",
                version=1,
                sensitivity_level=sens,
                is_compound=is_compound,
                split_from_id=faq.id,
                model_version=settings.LLM_MODEL,
            )
            if not child.normalized_question:
                continue
            # 与已有同题冲突则跳过该子条
            exists = await db.scalar(
                select(KBCachedFAQ.id).where(
                    KBCachedFAQ.kb_id == faq.kb_id,
                    KBCachedFAQ.normalized_question == child.normalized_question,
                    KBCachedFAQ.id != faq.id,
                )
            )
            if exists:
                continue
            db.add(child)
            await db.flush()
            created.append({"id": str(child.id), "question": child.question, "status": child.status})

        if len(created) < 2:
            raise ValueError("有效子问题不足 2 条（可能与已有 FAQ 重复），未改动原条目")

        faq.status = "disabled"
        faq.is_active = False
        faq.stale_reason = "split_parent"
        faq.is_compound = True
        faq.updated_at = utcnow()

        child_ids = [c["id"] for c in created]
        await self.write_audit(
            db,
            action="faq_split",
            tenant_id=faq.tenant_id or settings.FAQ_TENANT_ID,
            operator_id=operator_id,
            target_id=faq.id,
            target_ids=[str(faq.id), *child_ids],
            old_value=parent_snapshot,
            new_value={"children": created, "child_count": len(created)},
        )
        return {
            "parent_id": str(faq.id),
            "children": created,
            "child_count": len(created),
        }

    async def list_split_children(
        self,
        db: AsyncSession,
        *,
        parent: KBCachedFAQ,
    ) -> list[dict[str, Any]]:
        """列出拆分产生的子问（优先 split_from_id，旧数据回退审计）。"""
        rows = list(
            (
                await db.scalars(
                    select(KBCachedFAQ)
                    .where(KBCachedFAQ.split_from_id == parent.id)
                    .order_by(KBCachedFAQ.created_at.asc())
                )
            ).all()
        )
        if rows:
            return [
                {
                    "id": str(r.id),
                    "question": r.question,
                    "status": r.status,
                    "is_active": bool(r.is_active),
                    "available": True,
                    "stale_reason": r.stale_reason,
                }
                for r in rows
            ]

        # 兼容：无 split_from_id 的旧拆分，从最近一条 faq_split 审计回填
        audit = await db.scalar(
            select(FAQAuditLog)
            .where(
                FAQAuditLog.action == "faq_split",
                FAQAuditLog.target_id == parent.id,
            )
            .order_by(FAQAuditLog.created_at.desc())
            .limit(1)
        )
        if audit is None:
            return []
        child_ids: list[str] = []
        new_val = audit.new_value or {}
        for c in new_val.get("children") or []:
            if isinstance(c, dict) and c.get("id"):
                child_ids.append(str(c["id"]))
        if not child_ids and audit.target_ids:
            child_ids = [str(x) for x in audit.target_ids if str(x) != str(parent.id)]
        if not child_ids:
            return []
        id_uuids: list[uuid.UUID] = []
        for cid in child_ids:
            try:
                id_uuids.append(uuid.UUID(str(cid)))
            except ValueError:
                continue
        found = {
            str(r.id): r for r in (await db.scalars(select(KBCachedFAQ).where(KBCachedFAQ.id.in_(id_uuids)))).all()
        }
        out: list[dict[str, Any]] = []
        for cid in child_ids:
            row = found.get(str(cid))
            if row is None:
                out.append(
                    {
                        "id": str(cid),
                        "question": "（已删除）",
                        "status": "deleted",
                        "is_active": False,
                        "available": False,
                        "stale_reason": None,
                    }
                )
                continue
            # 回填关联，便于后续撤销
            if getattr(row, "split_from_id", None) is None:
                row.split_from_id = parent.id
            out.append(
                {
                    "id": str(row.id),
                    "question": row.question,
                    "status": row.status,
                    "is_active": bool(row.is_active),
                    "available": True,
                    "stale_reason": row.stale_reason,
                }
            )
        return out

    async def revoke_split_faq(
        self,
        db: AsyncSession,
        *,
        parent: KBCachedFAQ,
        child_ids: list[uuid.UUID],
        operator_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        """撤销拆分：恢复父条；勾选子问停用（split_revoked）；未勾选保留。"""
        if not (parent.status == "disabled" and (parent.stale_reason or "") == "split_parent"):
            raise ValueError("仅已拆分的父条可撤销拆分")

        children_meta = await self.list_split_children(db, parent=parent)
        available_map = {c["id"]: c for c in children_meta if c.get("available")}
        selected: list[KBCachedFAQ] = []
        skipped: list[str] = []
        for cid in child_ids:
            key = str(cid)
            if key not in available_map:
                skipped.append(key)
                continue
            row = await db.get(KBCachedFAQ, cid)
            if row is None:
                skipped.append(key)
                continue
            selected.append(row)

        # 恢复父条：优先审计快照中的 status
        restore_status = "active"
        audit = await db.scalar(
            select(FAQAuditLog)
            .where(
                FAQAuditLog.action == "faq_split",
                FAQAuditLog.target_id == parent.id,
            )
            .order_by(FAQAuditLog.created_at.desc())
            .limit(1)
        )
        if audit and isinstance(audit.old_value, dict):
            prev = str(audit.old_value.get("status") or "").strip()
            if prev in ("active", "pending_review", "disabled"):
                restore_status = prev

        parent_before = {
            "status": parent.status,
            "stale_reason": parent.stale_reason,
            "is_active": parent.is_active,
        }
        parent.status = restore_status
        parent.is_active = restore_status != "disabled"
        parent.stale_reason = None
        parent.is_compound = True
        parent.updated_at = utcnow()

        revoked: list[dict[str, Any]] = []
        for child in selected:
            child.status = "disabled"
            child.is_active = False
            child.stale_reason = "split_revoked"
            child.updated_at = utcnow()
            revoked.append({"id": str(child.id), "question": child.question})

        await self.write_audit(
            db,
            action="faq_split_revoke",
            tenant_id=parent.tenant_id or settings.FAQ_TENANT_ID,
            operator_id=operator_id,
            target_id=parent.id,
            target_ids=[str(parent.id), *[str(c.id) for c in selected]],
            old_value={
                "parent": parent_before,
                "revoked_children": [{"id": str(c.id)} for c in selected],
            },
            new_value={
                "parent_status": restore_status,
                "revoked": revoked,
                "revoked_count": len(revoked),
                "skipped": skipped,
                "kept_unselected": True,
            },
        )
        return {
            "parent_id": str(parent.id),
            "parent_status": restore_status,
            "revoked": revoked,
            "revoked_count": len(revoked),
            "skipped": skipped,
        }

    async def _split_via_llm(self, question: str, answer: str) -> list[dict[str, str]]:
        for attempt in range(2):
            try:
                raw = await llm_service.chat(
                    [
                        {"role": "system", "content": _SPLIT_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"question": question, "answer": answer},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    temperature=0.1,
                    max_tokens=settings.FAQ_LLM_MAX_TOKENS,
                )
                text = (raw or "").strip()
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\s*", "", text)
                    text = re.sub(r"\s*```$", "", text)
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    match = re.search(r"\{[\s\S]*\}", text)
                    if not match:
                        continue
                    payload = json.loads(match.group(0))
                items = payload.get("items") if isinstance(payload, dict) else None
                if isinstance(items, list) and len(items) >= 2:
                    return [x for x in items if isinstance(x, dict)]
            except LLMServiceError as exc:
                logger.error("FAQ split LLM failed attempt=%s: %s", attempt + 1, exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("FAQ split failed attempt=%s: %s", attempt + 1, exc)
        return []


kb_faq_service = KBFaqService()

"""知识库级 FAQ：生成、命中、失效与热门列表。"""

from __future__ import annotations

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
)
from app.core.redis import get_redis_client
from app.core.redis_keys import kb_faq_key, kb_faq_lock_key
from app.models.base import utcnow
from app.models.document import Document, DocumentChunk
from app.models.kb_faq import FAQAuditLog, KBCachedFAQ
from app.models.knowledge_base import KnowledgeBase
from app.services.llm import LLMServiceError, llm_service
from app.services.role_cache import normalize_cache_question

logger = logging.getLogger(__name__)

_GENERATION_PROMPT = """你是企业知识库 FAQ 缓存生成器。
根据输入的文档片段生成可直接缓存的问题与答案。

格式：{"items":[{"question":"...","answer":"...","refs":[1,2]}]}

规则：
1. 生成{count}条高质量、互不重复的问题
2. 答案只能依据输入片段，禁止编造
3. refs必须是实际支持答案的片段编号
4. 问题应能脱离上下文独立理解
5. 禁止将人名、日期、金额泛化为标准答案模板
6. 同结构不同参数的问题应生成独立FAQ，不要合并
7. 优先生成通用性强、可能被多次问到的问题
8. 只输出 JSON，不要 Markdown 或解释
"""


@dataclass
class FAQMatch:
    """权限复核后的 FAQ 命中。"""

    faq_id: uuid.UUID
    kb_id: uuid.UUID
    question: str
    answer: str
    chunk_ids: list[str]
    citations: list[dict[str, Any]]
    source: str  # redis | kb_faq


@dataclass
class _DraftFAQ:
    question: str
    answer: str
    chunk_ids: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    quality_score: float = 0.75
    status: str = "active"


class KBFaqService:
    """知识库 FAQ 业务门面。"""

    def normalize_question(self, question: str) -> str:
        return normalize_cache_question(question)

    def question_hash(self, normalized: str) -> str:
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

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
        debug_skip_read: bool | None = None,
    ) -> FAQMatch | None:
        """FAQ 命中：多轮护栏 → Redis → DB → 写回 Redis。护栏由流水线先行调用。"""
        if not settings.FAQ_MASTER_SWITCH:
            return None
        if debug_skip_read if debug_skip_read is not None else settings.FAQ_DEBUG_SKIP_READ:
            return None
        if not is_explicit_click and (message_count_in_session > 0 or has_unfinished_context):
            return None

        authorized = [kb for kb in authorized_kb_ids if kb]
        if not authorized:
            return None

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
            return None

        normalized = self.normalize_question(question)
        if not normalized:
            return None
        qhash = self.question_hash(normalized)

        redis_client = None
        try:
            redis_client = get_redis_client()
        except Exception:  # noqa: BLE001
            redis_client = None

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
                faq_cache_hit_total.labels(source="redis", kb_id=str(kb_id)).inc()
                return FAQMatch(
                    faq_id=uuid.UUID(data["faq_id"]) if data.get("faq_id") else uuid.uuid4(),
                    kb_id=kb_id,
                    question=question,
                    answer=data.get("answer") or "",
                    chunk_ids=[str(x) for x in (data.get("chunk_ids") or [])],
                    citations=list(data.get("citations") or []),
                    source="redis",
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
                    },
                    ensure_ascii=False,
                )
                try:
                    await redis_client.setex(cache_key, settings.FAQ_REDIS_CACHE_TTL_SECONDS, payload)
                except Exception:  # noqa: BLE001
                    logger.debug("faq redis writeback failed", exc_info=True)

            faq_cache_hit_total.labels(source="kb_faq", kb_id=str(faq.kb_id)).inc()
            return FAQMatch(
                faq_id=faq.id,
                kb_id=faq.kb_id,
                question=faq.question,
                answer=faq.answer,
                chunk_ids=[str(x) for x in (faq.chunk_ids or [])],
                citations=list(faq.citations or []),
                source="kb_faq",
            )
        return None

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
            faq_generation_total.labels(status="skipped_no_llm", kb_id=str(kb_id or "")).inc()
            return {"status": "skipped", "reason": "no_llm_key"}

        started = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            doc = await db.scalar(select(Document).where(Document.id == doc_id))
            if not doc:
                return {"status": "skipped", "reason": "document_not_found"}
            if doc.status != "ready":
                return {"status": "skipped", "reason": "document_not_ready"}

            resolved_kb = kb_id or doc.kb_id
            resolved_tenant = tenant_id or settings.FAQ_TENANT_ID
            kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == resolved_kb))
            if kb is None or kb.deleted_at is not None:
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
            if len(chunks) < 3:
                faq_generation_total.labels(status="skipped_chunks", kb_id=str(resolved_kb)).inc()
                return {"status": "skipped", "reason": "chunks_less_than_3"}

            content_ratio = sum(1 for c in chunks if (c.content or "").strip()) / max(len(chunks), 1)
            if content_ratio < 0.3:
                faq_generation_total.labels(status="skipped_content", kb_id=str(resolved_kb)).inc()
                return {"status": "skipped", "reason": "insufficient_content"}

            today_count = await self._today_generation_count(db, resolved_kb)
            if today_count >= settings.FAQ_KB_DAILY_LIMIT:
                faq_generation_total.labels(status="rate_limited", kb_id=str(resolved_kb)).inc()
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
                return {"status": "rate_limited", "reason": "kb_limit_reached"}

            lock_key = kb_faq_lock_key(tenant=resolved_tenant, kb_id=str(resolved_kb))
            if not await self._acquire_lock(lock_key, timeout=3600):
                return {"status": "queued", "reason": "another_task_running"}

            try:
                target_count = settings.FAQ_PER_DOCUMENT_COUNT
                generated: list[_DraftFAQ] = []
                for batch in self._chunk_batches(chunks, settings.FAQ_DOCUMENT_CHUNK_BATCH_SIZE):
                    if len(generated) >= target_count:
                        break
                    remain = target_count - len(generated)
                    batch_faqs = await self._generate_batch_with_retry(
                        batch,
                        doc=doc,
                        count=min(remain, 5),
                    )
                    generated.extend(batch_faqs)

                unique = await self._deduplicate(db, generated, resolved_kb)
                saved = 0
                for faq in unique:
                    if self._contains_sensitive(faq.answer) or self._contains_sensitive(faq.question):
                        faq.status = "pending_review"
                    if faq.quality_score < settings.FAQ_QUALITY_THRESHOLD and faq.status != "pending_review":
                        continue
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
                        status=faq.status,
                        model_version=settings.LLM_MODEL,
                    )
                    saved += 1

                await db.commit()
                faq_generation_total.labels(status="success", kb_id=str(resolved_kb)).inc()
                faq_active_count.labels(kb_id=str(resolved_kb)).set(
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
                return {
                    "status": "success",
                    "generated": len(unique),
                    "saved": saved,
                    "kb_id": str(resolved_kb),
                    "doc_id": str(doc_id),
                }
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                faq_generation_total.labels(status="error", kb_id=str(resolved_kb)).inc()
                logger.exception("FAQ generation failed doc=%s: %s", doc_id, exc)
                return {"status": "error", "reason": str(exc)[:200]}
            finally:
                await self._release_lock(lock_key)

    async def enqueue_generation(
        self,
        *,
        kb_id: uuid.UUID,
        tenant_id: str,
        document_ids: list[uuid.UUID] | None = None,
    ) -> str:
        """为知识库内文档排队生成；返回任务批次 ID。"""
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
            # 独立任务，不阻塞调用方
            import asyncio

            asyncio.create_task(
                self.generate_from_document(doc_id, kb_id=kb_id, tenant_id=tenant_id),
                name=f"kb-faq-{task_id}-{doc_id}",
            )
        return task_id

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
    ) -> list[KBCachedFAQ]:
        if not kb_ids:
            return []
        offset = max(0, (page - 1) * limit)
        base = (
            select(KBCachedFAQ)
            .where(
                KBCachedFAQ.tenant_id == tenant_id,
                KBCachedFAQ.kb_id.in_(kb_ids),
                KBCachedFAQ.is_active.is_(True),
                KBCachedFAQ.status == "active",
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
        """文档删除后：移出引用该文档的 FAQ；无剩余来源则禁用。"""
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
            row.source_document_ids = docs
            if not docs:
                row.is_active = False
                row.status = "disabled"
                row.stale_reason = "document_deleted"
            affected += 1
        if affected:
            await db.flush()
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
        await db.flush()

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
        for attempt in range(2):
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
    ) -> None:
        normalized = self.normalize_question(question)
        if not normalized:
            return
        values = {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "kb_id": kb_id,
            "question": question,
            "normalized_question": normalized,
            "answer": answer,
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
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        stmt = insert(KBCachedFAQ).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["kb_id", "normalized_question"],
            set_={
                "question": question,
                "answer": answer,
                "source_document_ids": source_document_ids,
                "chunk_ids": chunk_ids,
                "citations": citations,
                "quality_score": quality_score,
                "source": source,
                "status": status,
                "is_active": status != "disabled",
                "model_version": model_version,
                "stale_reason": stale_reason,
                "updated_at": utcnow(),
                "version": KBCachedFAQ.version + 1,
            },
        )
        await db.execute(stmt)


kb_faq_service = KBFaqService()

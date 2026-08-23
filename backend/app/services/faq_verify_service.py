"""FAQ 答案校验（A4-a）：同口径轻量 RAG 模拟，只告警/标 stale，不覆盖答案。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.metrics import faq_verify_stale_total
from app.models.base import utcnow
from app.models.document import Document, DocumentChunk
from app.models.enums import FAQStatus, FAQStaleReason
from app.models.kb_faq import KBCachedFAQ
from app.services.kb_faq_service import kb_faq_service
from app.services.llm import llm_service

logger = logging.getLogger(__name__)

_VERIFY_PROMPT = """你是企业知识库问答助手。只根据给定资料回答用户问题。
要求：简洁中文；不得编造资料中没有的信息；不要输出思考过程。"""


class FAQVerifyService:
    """异步校验 FAQ 是否与当前文档口径漂移。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._daily_count = 0
        self._daily_day = ""
        self._sem = asyncio.Semaphore(max(1, settings.FAQ_VERIFY_CONCURRENCY))

    def _reset_daily_if_needed(self) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if day != self._daily_day:
            self._daily_day = day
            self._daily_count = 0

    def _under_daily_limit(self) -> bool:
        self._reset_daily_if_needed()
        return self._daily_count < max(1, settings.FAQ_VERIFY_DAILY_LIMIT)

    async def ensure_workers(self) -> None:
        if not settings.FAQ_VERIFY_ENABLED:
            return
        need = max(1, settings.FAQ_VERIFY_CONCURRENCY)
        alive = [t for t in self._workers if not t.done()]
        self._workers = alive
        while len(self._workers) < need:
            self._workers.append(asyncio.create_task(self._worker(), name=f"faq-verify-{len(self._workers)}"))

    async def enqueue_faq_ids(self, faq_ids: list[uuid.UUID]) -> int:
        if not settings.FAQ_VERIFY_ENABLED or not faq_ids:
            return 0
        await self.ensure_workers()
        n = 0
        for faq_id in faq_ids:
            if not self._under_daily_limit():
                break
            await self._queue.put(faq_id)
            n += 1
        return n

    async def enqueue_for_document(self, doc_id: uuid.UUID) -> int:
        """文档 ready 后：校验引用该文档的 active FAQ。"""
        if not settings.FAQ_VERIFY_ENABLED or not settings.FAQ_VERIFY_ON_DOCUMENT_READY:
            return 0
        async with SessionLocal() as db:
            rows = list(
                (
                    await db.scalars(
                        select(KBCachedFAQ.id).where(
                            KBCachedFAQ.is_active.is_(True),
                            KBCachedFAQ.status == FAQStatus.ACTIVE.value,
                            KBCachedFAQ.source_document_ids.contains([str(doc_id)]),
                        ).limit(settings.FAQ_VERIFY_DAILY_LIMIT)
                    )
                ).all()
            )
        return await self.enqueue_faq_ids(list(rows))

    async def enqueue_hit_threshold_batch(self) -> int:
        """每日：hit_count ≥ 阈值的 active FAQ。"""
        if not settings.FAQ_VERIFY_ENABLED:
            return 0
        async with SessionLocal() as db:
            rows = list(
                (
                    await db.scalars(
                        select(KBCachedFAQ.id)
                        .where(
                            KBCachedFAQ.is_active.is_(True),
                            KBCachedFAQ.status == FAQStatus.ACTIVE.value,
                            KBCachedFAQ.hit_count >= settings.FAQ_VERIFY_HIT_THRESHOLD,
                        )
                        .order_by(KBCachedFAQ.hit_count.desc())
                        .limit(settings.FAQ_VERIFY_DAILY_LIMIT)
                    )
                ).all()
            )
        return await self.enqueue_faq_ids(list(rows))

    async def enqueue_daily_scan_if_enabled(self) -> int:
        if not settings.FAQ_VERIFY_DAILY_SCAN_ENABLED:
            return 0
        async with SessionLocal() as db:
            rows = list(
                (
                    await db.scalars(
                        select(KBCachedFAQ.id)
                        .where(
                            KBCachedFAQ.is_active.is_(True),
                            KBCachedFAQ.status == FAQStatus.ACTIVE.value,
                        )
                        .order_by(KBCachedFAQ.updated_at.asc())
                        .limit(settings.FAQ_VERIFY_DAILY_LIMIT)
                    )
                ).all()
            )
        return await self.enqueue_faq_ids(list(rows))

    async def _worker(self) -> None:
        while True:
            faq_id = await self._queue.get()
            try:
                async with self._sem:
                    if not self._under_daily_limit():
                        continue
                    self._daily_count += 1
                    await self.verify_one(faq_id)
            except Exception:  # noqa: BLE001
                logger.warning("faq_verify worker failed faq_id=%s", faq_id, exc_info=True)
            finally:
                self._queue.task_done()

    async def verify_one(self, faq_id: uuid.UUID) -> dict[str, Any]:
        async with SessionLocal() as db:
            faq = await db.scalar(select(KBCachedFAQ).where(KBCachedFAQ.id == faq_id))
            if faq is None or not faq.is_active:
                return {"status": "skipped", "reason": "missing"}
            if faq.status == FAQStatus.DISABLED.value:
                return {"status": "skipped", "reason": "disabled"}

            simulated = await self._simulate_rag_answer(db, faq)
            if not simulated:
                return {"status": "skipped", "reason": "simulate_failed"}

            sim = kb_faq_service._similarity(faq.answer or "", simulated)
            if sim >= settings.FAQ_VERIFY_ANSWER_SIM_THRESHOLD:
                return {"status": "ok", "similarity": sim}

            diff_summary = {
                "similarity": round(sim, 4),
                "threshold": settings.FAQ_VERIFY_ANSWER_SIM_THRESHOLD,
                "simulated_preview": (simulated or "")[:240],
                "current_preview": (faq.answer or "")[:240],
            }
            logger.warning(
                "faq_verify stale faq_id=%s diff=%s",
                faq.id,
                diff_summary,
            )
            await kb_faq_service.write_audit(
                db,
                action="faq_verify_stale",
                tenant_id=faq.tenant_id or settings.FAQ_TENANT_ID,
                operator_id=None,
                target_id=faq.id,
                old_value={"answer_preview": (faq.answer or "")[:240], "status": faq.status},
                new_value=diff_summary,
            )
            faq.stale_reason = FAQStaleReason.RAG_DRIFT.value
            if faq.status == FAQStatus.ACTIVE.value:
                faq.status = FAQStatus.PENDING_REVIEW.value
            faq.updated_at = utcnow()
            await db.commit()
            faq_verify_stale_total.inc()
            return {"status": "stale", "similarity": sim}

    async def _simulate_rag_answer(self, db: AsyncSession, faq: KBCachedFAQ) -> str | None:
        """轻量同口径：用来源文档启用分段 + LLM 重答（不改 FAQ）。"""
        chunk_ids = [str(x) for x in (faq.chunk_ids or []) if x]
        chunks: list[DocumentChunk] = []
        if chunk_ids:
            try:
                uuids = [uuid.UUID(x) for x in chunk_ids]
                chunks = list(
                    (
                        await db.scalars(
                            select(DocumentChunk).where(
                                DocumentChunk.id.in_(uuids),
                                DocumentChunk.is_enabled.is_(True),
                            )
                        )
                    ).all()
                )
            except (TypeError, ValueError):
                chunks = []
        if not chunks:
            doc_ids: list[uuid.UUID] = []
            for raw in faq.source_document_ids or []:
                try:
                    doc_ids.append(uuid.UUID(str(raw)))
                except (TypeError, ValueError):
                    continue
            if doc_ids:
                chunks = list(
                    (
                        await db.scalars(
                            select(DocumentChunk)
                            .where(
                                DocumentChunk.document_id.in_(doc_ids),
                                DocumentChunk.is_enabled.is_(True),
                            )
                            .order_by(DocumentChunk.chunk_index.asc())
                            .limit(8)
                        )
                    ).all()
                )
        if not chunks:
            return None

        materials = []
        for i, chunk in enumerate(chunks[:8], start=1):
            materials.append(f"[{i}] {(chunk.content or '')[:800]}")
        context = "\n\n".join(materials)
        try:
            raw = await llm_service.chat(
                [
                    {"role": "system", "content": _VERIFY_PROMPT},
                    {
                        "role": "user",
                        "content": f"资料：\n{context}\n\n问题：{faq.question}\n请作答：",
                    },
                ],
                temperature=0.1,
                max_tokens=min(1024, settings.FAQ_LLM_MAX_TOKENS),
            )
        except Exception:  # noqa: BLE001
            logger.warning("faq_verify llm failed faq_id=%s", faq.id, exc_info=True)
            return None
        return kb_faq_service.clean_answer_for_output(raw or "").strip() or None


faq_verify_service = FAQVerifyService()


async def run_faq_verify_scheduler_once() -> dict[str, int]:
    hit_n = await faq_verify_service.enqueue_hit_threshold_batch()
    scan_n = await faq_verify_service.enqueue_daily_scan_if_enabled()
    return {"hit_enqueued": hit_n, "scan_enqueued": scan_n}


async def faq_verify_loop(stop_event: asyncio.Event) -> None:
    """日级轮询：默认仅 hit 阈值批次；全库日扫受开关控制。"""
    poll = max(3600, int(settings.FAQ_VERIFY_SCHEDULER_POLL_SECONDS))
    while not stop_event.is_set():
        try:
            stats = await run_faq_verify_scheduler_once()
            logger.info("faq_verify scheduler tick %s", stats)
        except Exception:  # noqa: BLE001
            logger.warning("faq_verify scheduler failed", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll)
        except asyncio.TimeoutError:
            continue

"""密级工程加固 B：DB 为唯一真相源、缓存复核、改密级失效闭环。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.services.kb_faq_service import KBFaqService
from app.services.qa_cache import qa_cache_service
from app.services.sensitivity_service import sensitivity_service
from app.schemas.optimization_contracts import CacheLookupRequest


def _scalar_result(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = items
    return result


@pytest.mark.asyncio
async def test_filter_hits_trusts_db_not_vector_metadata() -> None:
    """向量 metadata 标 normal、DB chunk 为 confidential 时仍应滤掉。"""
    chunk_id = uuid4()
    hit = SimpleNamespace(
        chunk_id=str(chunk_id),
        metadata={"sensitivity_level": "normal"},
    )
    db_chunk = SimpleNamespace(id=chunk_id, sensitivity_level="confidential")
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_scalar_result([db_chunk]))

    kept, dropped = await sensitivity_service.filter_hits_by_sensitivity(
        db, [hit], user_max_level="normal"
    )
    assert kept == []
    assert dropped == 1


@pytest.mark.asyncio
async def test_citations_allowed_rechecks_document_table() -> None:
    """L2 缓存引用文档升密后，复核应拒绝。"""
    doc_id = uuid4()
    doc = SimpleNamespace(id=doc_id, sensitivity_level="confidential")
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_scalar_result([doc]))

    ok = await sensitivity_service.citations_allowed_for_user(
        db,
        [{"doc_id": str(doc_id)}],
        user_max_level="normal",
    )
    assert ok is False

    ok2 = await sensitivity_service.citations_allowed_for_user(
        db,
        [{"doc_id": str(doc_id)}],
        user_max_level="confidential",
    )
    assert ok2 is True


@pytest.mark.asyncio
async def test_faq_redis_hit_revalidates_against_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis 仍写 normal，但 DB FAQ 已升 confidential → 无权用户不得秒答。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "FAQ_MASTER_SWITCH", True)
    monkeypatch.setattr(settings, "FAQ_DEBUG_SKIP_READ", False)
    monkeypatch.setattr(settings, "FAQ_SEMANTIC_HIT_ENABLED", False)

    kb_id = uuid4()
    faq_id = uuid4()
    faq_row = SimpleNamespace(
        id=faq_id,
        kb_id=kb_id,
        is_active=True,
        status="active",
        sensitivity_level="confidential",
        answer="机密答案",
        chunk_ids=[],
        citations=[],
    )

    enabled_result = MagicMock()
    enabled_result.all.return_value = [kb_id]
    empty_faqs = MagicMock()
    empty_faqs.all.return_value = []

    db = AsyncMock()
    db.scalars = AsyncMock(side_effect=[enabled_result, empty_faqs])
    db.scalar = AsyncMock(return_value=faq_row)

    redis = AsyncMock()
    redis.get = AsyncMock(
        return_value=json.dumps(
            {
                "faq_id": str(faq_id),
                "answer": "旧普通答案",
                "sensitivity_level": "normal",
                "chunk_ids": [],
                "citations": [],
            }
        )
    )
    redis.delete = AsyncMock()

    with patch("app.services.kb_faq_service.get_redis_client", return_value=redis):
        with patch(
            "app.services.sensitivity_service.sensitivity_service.log_access_denied",
            new_callable=AsyncMock,
        ):
            outcome = await KBFaqService().check_faq_hit(
                db,
                question="机密制度？",
                tenant_id="default",
                authorized_kb_ids=[kb_id],
                is_explicit_click=False,
                message_count_in_session=0,
                has_unfinished_context=False,
                user_max_level="normal",
            )

    assert outcome.match is None
    assert outcome.denied is True


@pytest.mark.asyncio
async def test_update_document_sensitivity_invalidates_caches() -> None:
    """改密级后必须同步分段、重算 FAQ，并调用 FAQ Redis / QA 缓存失效。"""
    from app.services import document_service

    kb_id = uuid4()
    doc_id = uuid4()
    user = SimpleNamespace(id=uuid4(), roles=[])
    doc = SimpleNamespace(id=doc_id, kb_id=kb_id, sensitivity_level="normal", filename="a.md")

    faq = SimpleNamespace(
        source_document_ids=[str(doc_id)],
        sensitivity_level="normal",
    )

    chunk_result = MagicMock()
    chunk_result.rowcount = 3

    db = AsyncMock()
    db.execute = AsyncMock(return_value=chunk_result)
    db.scalars = AsyncMock(
        side_effect=[
            _scalar_result([faq]),
            _scalar_result([doc]),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    faq_inv = AsyncMock(return_value=2)
    qa_inv = AsyncMock(return_value=5)

    with (
        patch.object(document_service, "assert_kb_mutable", new_callable=AsyncMock),
        patch.object(document_service, "get_document_detail", new_callable=AsyncMock, return_value=doc),
        patch.object(document_service, "is_platform_admin_user", return_value=True),
        patch.object(document_service, "write_audit", new_callable=AsyncMock),
        patch("app.services.kb_faq_service.kb_faq_service.invalidate_kb_faq_redis", faq_inv),
        patch("app.services.qa_cache.qa_cache_service.invalidate_by_kb", qa_inv),
    ):
        out_doc, sync = await document_service.update_document_sensitivity(
            db, kb_id, doc_id, "confidential", user
        )

    assert out_doc.sensitivity_level == "confidential"
    assert faq.sensitivity_level == "confidential"
    assert sync["chunks_updated"] == 3
    assert sync["faq_updated"] == 1
    assert sync["faq_redis_deleted"] == 2
    assert sync["qa_cache_deleted"] == 5
    faq_inv.assert_awaited()
    qa_inv.assert_awaited()


@pytest.mark.asyncio
async def test_drop_exact_removes_l1_entry() -> None:
    req = CacheLookupRequest(
        request_id="r1",
        tenant_id="t",
        scope_fingerprint="kb1",
        normalized_question="年假有几天",
        user_max_level="normal",
        top_k=5,
        model_config_version="v1",
    )
    qh = qa_cache_service._question_hash(req.normalized_question)
    l1_key = qa_cache_service._l1_key(req, qh)
    qa_cache_service._l1.set(l1_key, {"status": "hit", "answer": "x"})
    assert qa_cache_service._l1.get(l1_key) is not None
    await qa_cache_service.drop_exact(req, redis_client=None)
    assert qa_cache_service._l1.get(l1_key) is None

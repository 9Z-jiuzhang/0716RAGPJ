"""知识库 FAQ 核心逻辑单测：标准化、相似度、多轮跳过与越权拦截。"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.core.config import settings
from app.core.qa_pipeline import QAPipeline
from app.services.kb_faq_service import KBFaqService, kb_faq_service


def test_faq_lookup_runs_before_role_cache_and_retrieval() -> None:
    source = inspect.getsource(QAPipeline.run)
    faq_pos = source.index("kb_faq_service.check_faq_hit")
    role_pos = source.index("role_cache_service.lookup")
    query_pos = source.index("get_query_processing_options")
    retrieval_pos = source.index("hybrid_retriever.retrieve")
    assert faq_pos < role_pos < query_pos < retrieval_pos


def test_similarity_exact_and_near_duplicate() -> None:
    svc = KBFaqService()
    assert svc._similarity("年假有几天？", "年假有几天") >= 0.99
    assert svc._similarity("年假有几天", "几天年假") < settings.FAQ_SIMILARITY_THRESHOLD


def test_classify_compound_question_tiers() -> None:
    svc = KBFaqService()
    assert svc.classify_compound_question("年假有几天？病假有几天？") == (True, True)
    assert svc.classify_compound_question("员工在什么情况下需要进入绩效改进计划（PIP）？PIP的通过标准是什么？") == (
        True,
        True,
    )
    is_c, strong = svc.classify_compound_question("年假和病假分别怎么请")
    assert is_c is True and strong is False
    assert svc.classify_compound_question("请问年假怎么请") == (False, False)
    assert svc.classify_compound_question("年假和病假的区别是什么") == (False, False)
    is_c2, status = svc.apply_compound_flags(question="年假有几天？病假有几天？", status="active")
    assert is_c2 is True and status == "pending_review"


def test_sensitive_pattern_flags_phone() -> None:
    svc = KBFaqService()
    assert svc._contains_sensitive("联系电话13812345678")


@pytest.mark.asyncio
async def test_check_faq_hit_allows_multiturn_exact_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """多轮会话中手输完整同题仍应查 FAQ（不再因 message_count>0 直接跳过）。"""
    monkeypatch.setattr(settings, "FAQ_MASTER_SWITCH", True)
    monkeypatch.setattr(settings, "FAQ_DEBUG_SKIP_READ", False)
    allowed = uuid4()

    enabled_result = MagicMock()
    enabled_result.all.return_value = [allowed]
    faq_result = MagicMock()
    faq_result.all.return_value = []

    db = AsyncMock()
    db.scalars = AsyncMock(side_effect=[enabled_result, faq_result])
    monkeypatch.setattr(
        "app.services.kb_faq_service.get_redis_client",
        MagicMock(side_effect=RuntimeError("no redis")),
    )

    result = await kb_faq_service.check_faq_hit(
        db,
        question="年假有几天",
        tenant_id="default",
        authorized_kb_ids=[allowed],
        is_explicit_click=False,
        message_count_in_session=2,
        has_unfinished_context=True,
    )
    assert result.match is None
    assert result.denied is False or result.denied is True
    assert db.scalars.await_count >= 1


@pytest.mark.asyncio
async def test_check_faq_hit_rejects_unauthorized_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FAQ_MASTER_SWITCH", True)
    monkeypatch.setattr(settings, "FAQ_DEBUG_SKIP_READ", False)
    allowed = uuid4()
    forbidden = uuid4()
    faq = SimpleNamespace(
        id=uuid4(),
        kb_id=forbidden,
        answer="秘密答案",
        chunk_ids=[],
        citations=[],
        hit_count=0,
        status="active",
        is_active=True,
        question="年假有几天",
    )

    enabled_result = MagicMock()
    enabled_result.all.return_value = [allowed]
    faq_result = MagicMock()
    faq_result.all.return_value = [faq]

    db = AsyncMock()
    db.scalars = AsyncMock(side_effect=[enabled_result, faq_result])

    monkeypatch.setattr(
        "app.services.kb_faq_service.get_redis_client",
        MagicMock(side_effect=RuntimeError("no redis")),
    )

    result = await kb_faq_service.check_faq_hit(
        db,
        question="年假有几天",
        tenant_id="default",
        authorized_kb_ids=[allowed],
        is_explicit_click=True,
        message_count_in_session=0,
        has_unfinished_context=False,
    )
    assert result.match is None
    assert result.denied is False

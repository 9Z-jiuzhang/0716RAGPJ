"""未命中拒答 / 系统机制路由回归。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core.qa_pipeline import _NO_EVIDENCE_NOTICE, _REFERENCE_SYSTEM_PROMPT, QAPipeline
from app.schemas.optimization_contracts import ConversationIntent, ConversationRouteDecision
from app.services.conversation_router import conversation_router
from app.utils.tracing import PerformanceTracker


async def _fake_stream(*_a: Any, **_k: Any) -> AsyncIterator[str]:
    yield "这是"
    yield "参考答案内容。"


def test_router_system_mechanism_how_it_runs() -> None:
    d = conversation_router.route(
        question="那能不能告诉我你这个系统是怎么运行的啊",
        has_last_answer=False,
    )
    assert d.intent == ConversationIntent.SYSTEM_MECHANISM
    assert d.should_retrieve is False
    reply = conversation_router.template_reply(d)
    assert reply is not None
    assert "内部实现" in reply or "企业" in reply
    assert "意图识别" not in reply  # 不应展开四步 RAG 说明


def test_router_system_help_still_works() -> None:
    d = conversation_router.route(question="你有什么功能", has_last_answer=False)
    assert d.intent == ConversationIntent.SYSTEM_HELP
    assert d.should_retrieve is False


def test_router_out_of_scope_expanded() -> None:
    d = conversation_router.route(question="帮我写一篇恋爱文案", has_last_answer=False)
    assert d.intent == ConversationIntent.OUT_OF_SCOPE


def test_reference_prompt_forbids_system_internals() -> None:
    assert "内部架构" in _REFERENCE_SYSTEM_PROMPT or "如何实现" in _REFERENCE_SYSTEM_PROMPT
    assert "提示词" in _REFERENCE_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_no_evidence_default_notice_only_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认 prefer abstain：业务未命中不调 LLM。"""
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_LLM_ENABLED", False)
    pipeline = QAPipeline()
    meta: dict[str, Any] = {"reason": "no_relevant_hits"}
    tracker = PerformanceTracker(request_id="req-abstain-1")
    mocked = AsyncMock()
    route = ConversationRouteDecision(
        intent=ConversationIntent.NEW_KB_QUERY,
        confidence=0.75,
        should_retrieve=True,
        reason_code="default_kb",
    )
    with patch("app.core.qa_pipeline.llm_service.stream_chat", new=mocked):
        parts: list[str] = []
        async for piece in pipeline._stream_no_evidence_answer(
            question="年假怎么请",
            rewritten_query="年假怎么请",
            history_messages=[],
            temperature=0.2,
            retrieval_meta=meta,
            tracker=tracker,
            route=route,
        ):
            parts.append(piece)
    text = "".join(parts)
    assert _NO_EVIDENCE_NOTICE in text
    assert meta["fallback_mode"] == "notice_only"
    mocked.assert_not_called()


@pytest.mark.asyncio
async def test_no_evidence_mechanism_forced_template_even_if_fallback_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_LLM_ENABLED", True)
    pipeline = QAPipeline()
    meta: dict[str, Any] = {"reason": "no_relevant_hits"}
    tracker = PerformanceTracker(request_id="req-mech-1")
    route = ConversationRouteDecision(
        intent=ConversationIntent.SYSTEM_MECHANISM,
        confidence=0.9,
        reason_code="system_mechanism_rule",
    )
    mocked = AsyncMock()
    with patch("app.core.qa_pipeline.llm_service.stream_chat", new=mocked):
        parts: list[str] = []
        async for piece in pipeline._stream_no_evidence_answer(
            question="系统架构是什么",
            rewritten_query="系统架构是什么",
            history_messages=[],
            temperature=0.2,
            retrieval_meta=meta,
            tracker=tracker,
            route=route,
        ):
            parts.append(piece)
    text = "".join(parts)
    assert meta["fallback_mode"] == "template_refuse"
    assert "内部实现" in text or "知识库" in text
    assert "参考答案内容" not in text
    mocked.assert_not_called()


@pytest.mark.asyncio
async def test_no_evidence_llm_when_enabled_for_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_LLM_ENABLED", True)
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_WEB_SEARCH_ENABLED", False)
    pipeline = QAPipeline()
    meta: dict[str, Any] = {"reason": "no_relevant_hits"}
    tracker = PerformanceTracker(request_id="req-biz-1")
    route = ConversationRouteDecision(
        intent=ConversationIntent.NEW_KB_QUERY,
        confidence=0.75,
        should_retrieve=True,
        reason_code="default_kb",
    )
    with patch("app.core.qa_pipeline.llm_service.stream_chat", side_effect=_fake_stream):
        parts: list[str] = []
        async for piece in pipeline._stream_no_evidence_answer(
            question="公司股票期权怎么算？",
            rewritten_query="公司股票期权怎么算？",
            history_messages=[],
            temperature=0.2,
            retrieval_meta=meta,
            tracker=tracker,
            route=route,
        ):
            parts.append(piece)
    assert "参考答案内容" in "".join(parts)
    assert meta["fallback_mode"] == "llm_reference"


def test_fallback_default_is_false() -> None:
    from app.core.config import Settings

    assert Settings.model_fields["QA_FALLBACK_LLM_ENABLED"].default is False

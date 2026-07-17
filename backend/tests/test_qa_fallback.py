"""无知识库命中时的声明 + LLM 参考答案兜底测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from app.core.qa_pipeline import _NO_EVIDENCE_NOTICE, QAPipeline
from app.utils.tracing import PerformanceTracker


async def _fake_stream(*_a: Any, **_k: Any) -> AsyncIterator[str]:
    yield "这是"
    yield "参考答案内容。"


@pytest.mark.asyncio
async def test_no_evidence_streams_notice_then_llm_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_LLM_ENABLED", True)
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_WEB_SEARCH_ENABLED", False)

    pipeline = QAPipeline()
    meta: dict[str, Any] = {"reason": "no_relevant_hits"}
    tracker = PerformanceTracker(request_id="req-fallback-1")

    with patch("app.core.qa_pipeline.llm_service.stream_chat", side_effect=_fake_stream):
        parts: list[str] = []
        async for piece in pipeline._stream_no_evidence_answer(
            question="公司股票期权怎么算？",
            rewritten_query="公司股票期权怎么算？",
            history_messages=[],
            temperature=0.2,
            retrieval_meta=meta,
            tracker=tracker,
        ):
            parts.append(piece)

    text = "".join(parts)
    assert _NO_EVIDENCE_NOTICE in text
    assert "参考答案内容" in text
    assert meta["fallback_mode"] == "llm_reference"
    assert "generation" in tracker.to_dict()["stages_ms"]


@pytest.mark.asyncio
async def test_no_evidence_notice_only_when_fallback_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_LLM_ENABLED", False)

    pipeline = QAPipeline()
    meta: dict[str, Any] = {"reason": "no_authorized_kb"}
    tracker = PerformanceTracker(request_id="req-fallback-2")

    mocked = AsyncMock()
    with patch("app.core.qa_pipeline.llm_service.stream_chat", new=mocked):
        parts: list[str] = []
        async for piece in pipeline._stream_no_evidence_answer(
            question="任意问题",
            rewritten_query="任意问题",
            history_messages=[],
            temperature=0.2,
            retrieval_meta=meta,
            tracker=tracker,
        ):
            parts.append(piece)

    text = "".join(parts)
    assert _NO_EVIDENCE_NOTICE in text
    assert meta["fallback_mode"] == "notice_only"
    mocked.assert_not_called()


@pytest.mark.asyncio
async def test_no_evidence_includes_web_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_LLM_ENABLED", True)
    monkeypatch.setattr("app.core.qa_pipeline.settings.QA_FALLBACK_WEB_SEARCH_ENABLED", True)

    pipeline = QAPipeline()
    meta: dict[str, Any] = {"reason": "no_relevant_hits"}
    tracker = PerformanceTracker(request_id="req-fallback-3")

    async def _fake_web(_q: str, **_k: Any) -> list[dict[str, str]]:
        return [{"title": "公开资料", "snippet": "公开说明一段", "url": "https://example.com"}]

    with (
        patch("app.core.qa_pipeline.search_web", side_effect=_fake_web),
        patch("app.core.qa_pipeline.llm_service.stream_chat", side_effect=_fake_stream),
    ):
        parts: list[str] = []
        async for piece in pipeline._stream_no_evidence_answer(
            question="什么是年假？",
            rewritten_query="什么是年假？",
            history_messages=[],
            temperature=0.2,
            retrieval_meta=meta,
            tracker=tracker,
        ):
            parts.append(piece)

    assert "参考答案内容" in "".join(parts)
    assert meta["fallback_mode"] == "llm_reference_with_web"
    assert meta["web_result_count"] == 1

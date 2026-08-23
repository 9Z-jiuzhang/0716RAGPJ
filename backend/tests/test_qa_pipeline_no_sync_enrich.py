"""P1：ask 路径不再同步 enrich / ensure_pdf_charts。"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.qa_pipeline import QAPipeline
from app.utils.tracing import PerformanceTracker


@pytest.mark.asyncio
async def test_emit_direct_answer_uses_chart_refs_not_sync_enrich(monkeypatch) -> None:
    enrich_calls = 0

    async def track_enrich(*args, **kwargs):
        nonlocal enrich_calls
        enrich_calls += 1
        return args[1]

    monkeypatch.setattr(QAPipeline, "_enrich_citation_images", track_enrich)
    monkeypatch.setattr(QAPipeline, "_persist_turn", AsyncMock())
    monkeypatch.setattr(QAPipeline, "_record_analytics_event", AsyncMock())

    ensure_calls = 0

    def track_ensure(*args, **kwargs):
        nonlocal ensure_calls
        ensure_calls += 1
        return []

    monkeypatch.setattr("app.services.document_charts.ensure_pdf_charts", track_ensure)

    pipeline = QAPipeline()
    db = AsyncMock()
    session = MagicMock()
    session.id = "11111111-1111-1111-1111-111111111111"
    tracker = PerformanceTracker(request_id="req-test")

    request = MagicMock()
    request.kb_ids = None

    citations = [{"doc_id": "22222222-2222-2222-2222-222222222222", "doc_name": "t.pdf", "page": 5}]
    events = []
    with patch("app.services.suggested_questions.suggested_questions_enabled", return_value=False):
        async for ev in pipeline._emit_direct_answer(
            db,
            session=session,
            user=None,
            guest_id="guest-1",
            is_guest=True,
            question="测试问题",
            answer_text="直答内容",
            tracker=tracker,
            lf_trace=None,
            route=None,
            request=request,
            citations=citations,
            retrieval_meta={"source": "test"},
        ):
            events.append(ev)

    assert enrich_calls == 0
    assert ensure_calls == 0
    cit = next(e for e in events if e.get("event") == "citations")
    assert cit["citations"][0]["images"] == []
    assert cit["citations"][0]["chart_refs"] == [{"kind": "page", "page": 5}]

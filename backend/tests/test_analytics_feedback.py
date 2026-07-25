"""问答统计口径与反馈写入行为测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.schemas.optimization_contracts import QAFeedbackUpsert
from app.services.analytics_events import AnalyticsEventService, _window_days


def test_window_days_clamped() -> None:
    assert _window_days(0) == 1
    assert _window_days(14) == 14
    assert _window_days(100) == 90


@pytest.mark.asyncio
async def test_feedback_summary_filters_by_days_window() -> None:
    """汇总计数须带 created_at >= since，与趋势同一口径。"""
    svc = AnalyticsEventService()
    db = AsyncMock()
    # scalar 依次：useful / useless / total_events / actors / sessions / avg_latency
    db.scalar = AsyncMock(side_effect=[2, 1, 10, 3, 4, 120.0])

    empty_result = MagicMock()
    empty_result.all.return_value = []
    db.execute = AsyncMock(return_value=empty_result)

    body = await svc.feedback_summary(db, days=7)
    assert body["days"] == 7
    assert body["trend_days"] == 7
    assert body["useful"] == 2
    assert body["useless"] == 1
    assert body["request_events"] == 10
    assert body["range"]["days"] == 7
    assert len(body["trend"]) >= 7

    assert db.scalar.await_count == 6
    assert db.execute.await_count == 4


@pytest.mark.asyncio
async def test_upsert_feedback_raises_and_logs_on_failure() -> None:
    """统计表写入失败必须向上抛出，禁止静默成功。"""
    svc = AnalyticsEventService()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    db.rollback = AsyncMock()

    payload = QAFeedbackUpsert(
        message_id=uuid4(),
        actor_hash="abc",
        rating="useful",
        comment=None,
    )
    with pytest.raises(RuntimeError, match="db down"):
        await svc.upsert_feedback(db, payload)
    db.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_upsert_feedback_commit_false_only_flushes() -> None:
    svc = AnalyticsEventService()
    db = AsyncMock()
    result = MagicMock()
    result.first.return_value = (uuid4(), "useful")
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    payload = QAFeedbackUpsert(
        message_id=uuid4(),
        actor_hash="abc",
        rating="useful",
    )
    out = await svc.upsert_feedback(db, payload, commit=False)
    assert out["rating"] == "useful"
    db.flush.assert_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_feedback_deletes_row() -> None:
    svc = AnalyticsEventService()
    db = AsyncMock()
    result = MagicMock()
    result.rowcount = 1
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    out = await svc.clear_feedback(
        db,
        message_id=uuid4(),
        actor_hash="abc",
        commit=False,
    )
    assert out["rating"] is None
    assert out["deleted"] == 1
    db.flush.assert_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_feedback_raises_on_failure() -> None:
    svc = AnalyticsEventService()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    db.rollback = AsyncMock()
    with pytest.raises(RuntimeError, match="db down"):
        await svc.clear_feedback(db, message_id=uuid4(), actor_hash="abc")
    db.rollback.assert_awaited()

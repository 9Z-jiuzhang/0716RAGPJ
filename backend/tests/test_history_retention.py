"""问答历史 7 天物理删除与 20 轮裁剪策略测试。"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.models.base import utcnow
from app.services.history_retention import enforce_history_retention


def _scalar_result(items: list[object]) -> MagicMock:
    """构造 SQLAlchemy scalars().all() 的最小测试替身。"""
    result = MagicMock()
    result.all.return_value = items
    return result


@pytest.mark.asyncio
async def test_retention_deletes_session_inactive_for_seven_days() -> None:
    """最后活跃时间超过保留期的会话应物理删除并清理 Redis。"""
    user_id = uuid4()
    old_session = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        guest_id=None,
        status="expired",
        last_active_at=utcnow() - timedelta(days=8),
    )
    db = AsyncMock()
    db.scalars = AsyncMock(
        side_effect=[
            _scalar_result([old_session]),
            _scalar_result([]),
            _scalar_result([]),
        ]
    )
    db.delete = AsyncMock()

    with (
        patch("app.services.history_retention.settings") as mock_settings,
        patch("app.services.history_retention.session_store") as mock_store,
    ):
        mock_settings.QA_HISTORY_RETENTION_DAYS = 7
        mock_settings.QA_HISTORY_MAX_TURNS = 20
        mock_store.delete_session_cache = AsyncMock()
        result = await enforce_history_retention(db, user_id=user_id)

    assert result.deleted_sessions == 1
    db.delete.assert_awaited_once_with(old_session)
    mock_store.delete_session_cache.assert_awaited_once_with(old_session.id, guest_id=None)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_retention_keeps_only_latest_twenty_turns() -> None:
    """同一用户跨会话累计超过 40 条正常消息时，应删除最旧的消息。"""
    user_id = uuid4()
    session_id = uuid4()
    session = SimpleNamespace(
        id=session_id,
        user_id=user_id,
        guest_id=None,
        summary="可能包含旧轮次的摘要",
        message_count=42,
    )
    messages = [SimpleNamespace(id=uuid4(), session_id=session_id, created_at=utcnow()) for _ in range(42)]
    db = AsyncMock()
    db.scalars = AsyncMock(
        side_effect=[
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result(messages),
            _scalar_result([session]),
        ]
    )
    db.scalar = AsyncMock(return_value=40)
    db.delete = AsyncMock()

    with (
        patch("app.services.history_retention.settings") as mock_settings,
        patch("app.services.history_retention.session_store") as mock_store,
    ):
        mock_settings.QA_HISTORY_RETENTION_DAYS = 7
        mock_settings.QA_HISTORY_MAX_TURNS = 20
        mock_store.delete_session_cache = AsyncMock()
        result = await enforce_history_retention(db, user_id=user_id, commit=False)

    assert result.deleted_messages == 2
    assert result.affected_session_ids == {session_id}
    assert session.message_count == 40
    assert session.summary is None
    assert db.delete.await_count == 2
    mock_store.delete_session_cache.assert_awaited_once_with(session_id, guest_id=None)
    db.commit.assert_not_awaited()


def test_redis_context_never_exceeds_history_turn_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """即使配置了更大的上下文窗口，Redis 也不能保留超过历史硬上限的消息。"""
    import importlib

    from app.memory.session_store import SessionStore

    session_store_module = importlib.import_module("app.memory.session_store")
    monkeypatch.setattr(session_store_module.settings, "QA_CONTEXT_WINDOW", 100)
    monkeypatch.setattr(session_store_module.settings, "QA_HISTORY_MAX_TURNS", 20)

    assert SessionStore().max_messages == 40

"""闲置会话过期逻辑单元测试。"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.base import utcnow
from app.services.session_expiry import expire_idle_sessions


@pytest.mark.asyncio
async def test_expire_idle_sessions_marks_expired_and_clears_redis() -> None:
    old = SimpleNamespace(
        id=uuid4(),
        guest_id="g1",
        status="active",
        last_active_at=utcnow() - timedelta(hours=2),
    )
    fresh = SimpleNamespace(
        id=uuid4(),
        guest_id=None,
        status="active",
        last_active_at=utcnow(),
    )

    result = MagicMock()
    result.all.return_value = [old]  # DB 查询已按 cutoff 过滤，仅返回闲置会话

    db = AsyncMock()
    db.scalars = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    with (
        patch("app.services.session_expiry.settings") as mock_settings,
        patch("app.services.session_expiry.session_store") as mock_store,
    ):
        mock_settings.QA_SESSION_IDLE_EXPIRE_MINUTES = 30
        mock_store.delete_session_cache = AsyncMock()

        count = await expire_idle_sessions(db)

    assert count == 1
    assert old.status == "expired"
    assert fresh.status == "active"
    mock_store.delete_session_cache.assert_awaited_once_with(old.id, guest_id="g1")
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_expire_idle_sessions_noop_when_empty() -> None:
    result = MagicMock()
    result.all.return_value = []
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=result)

    with patch("app.services.session_expiry.settings") as mock_settings:
        mock_settings.QA_SESSION_IDLE_EXPIRE_MINUTES = 30
        count = await expire_idle_sessions(db)

    assert count == 0
    db.commit.assert_not_called()

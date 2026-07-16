"""pytest 公共配置：开发集成测试 + QA 模块 Mock 夹具。"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("JWT_SECRET_KEY", "pytest-secret-key-change-me-32bytes!!")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ["RATE_LIMIT_ENABLED"] = "false"

# 确保配置单例读取到测试环境变量
try:
    from app.core.config import get_settings

    get_settings.cache_clear()
except Exception:
    pass


class FakeRedis:
    """内存 Redis 替身，满足会话记忆、限流与任务队列最小接口。"""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:  # noqa: ARG002
        self._store[key] = value
        return True

    async def incr(self, key: str) -> int:
        current = int(self._store.get(key) or "0") + 1
        self._store[key] = str(current)
        return current

    async def lpush(self, key: str, *values: str) -> int:
        bucket = self._lists.setdefault(key, [])
        for value in reversed(values):
            bucket.insert(0, value)
        return len(bucket)

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                count += 1
            if key in self._lists:
                del self._lists[key]
                count += 1
        return count

    async def expire(self, key: str, ttl: int) -> bool:  # noqa: ARG002
        return key in self._store or key in self._lists

    async def aclose(self) -> None:
        return None

    @property
    def is_closed(self) -> bool:
        return False


@pytest.fixture
async def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """注入 FakeRedis，供问答模块单测使用。"""
    client = FakeRedis()

    async def _init() -> FakeRedis:
        from app.core import redis as redis_module

        redis_module._redis_client = client
        return client

    monkeypatch.setattr("app.core.redis.init_redis", _init)
    monkeypatch.setattr("app.core.redis.get_redis_client", lambda: client)
    monkeypatch.setattr("app.core.redis.ping_redis", AsyncMock(return_value=True))

    async def _close() -> None:
        from app.core import redis as redis_module

        redis_module._redis_client = None

    monkeypatch.setattr("app.core.redis.close_redis", _close)
    return client


@pytest.fixture
async def client_mocked(fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """
    Mock DB / Chroma 的 AsyncClient，供 QA API 契约测试（无需真实依赖）。
    """
    mock_conn = AsyncMock()
    mock_conn.run_sync = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_engine.dispose = AsyncMock()
    mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_db = AsyncMock()
    mock_db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_db.scalar = AsyncMock(return_value=None)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute = AsyncMock()

    mock_session_local = MagicMock()
    mock_session_local.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_local.return_value.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("app.main.engine", mock_engine)
    monkeypatch.setattr("app.main.SessionLocal", mock_session_local)
    monkeypatch.setattr("app.main.seed_identity_data", AsyncMock())
    monkeypatch.setattr("app.main.init_chroma", lambda: MagicMock())
    monkeypatch.setattr("app.main.close_chroma", lambda: None)
    monkeypatch.setattr("app.core.chroma.ping_chroma", lambda: True)
    monkeypatch.setattr("app.main.llm_service.aclose", AsyncMock())
    monkeypatch.setattr("app.main.embedding_service.aclose", AsyncMock())

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def client(
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """每个测试独立启动应用 lifespan（Postgres 真实；Redis/Chroma 使用替身避免 event loop 冲突）。"""
    monkeypatch.setattr("app.main.init_chroma", lambda: None)
    monkeypatch.setattr("app.main.close_chroma", lambda: None)
    monkeypatch.setattr("app.core.chroma.ping_chroma", lambda: True)

    from app.main import app, lifespan

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

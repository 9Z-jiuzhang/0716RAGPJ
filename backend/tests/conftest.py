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

# 仅在宿主机跑 pytest 时，把 Compose 服务名映射为 localhost。
# 容器内（存在 /.dockerenv）应继续使用 postgres/redis 等服务名。
_IN_CONTAINER = Path("/.dockerenv").exists()
if not _IN_CONTAINER:
    for _key, _docker, _local in (
        ("POSTGRES_HOST", "postgres", "localhost"),
        ("REDIS_HOST", "redis", "localhost"),
        ("CHROMA_HOST", "chroma", "localhost"),
    ):
        current = os.environ.get(_key)
        if not current or current == _docker:
            os.environ[_key] = _local

os.environ.setdefault("JWT_SECRET_KEY", "pytest-secret-key-change-me-32bytes!!")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ["RATE_LIMIT_ENABLED"] = "false"

# 确保配置单例与引擎使用测试环境主机名
try:
    from app.core.config import get_settings
    import app.core.config as config_module
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    import app.core.database as database_module

    get_settings.cache_clear()
    config_module.settings = get_settings()
    database_module.engine = create_async_engine(config_module.settings.database_url, pool_pre_ping=True)
    database_module.SessionLocal = async_sessionmaker(
        database_module.engine, expire_on_commit=False, class_=AsyncSession
    )
    database_module.AsyncSessionLocal = database_module.SessionLocal
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

    async def _close() -> None:
        from app.core import redis as redis_module

        redis_module._redis_client = None

    # 必须同时 patch app.main 中的绑定名：lifespan 使用 from-import，仅改 core.redis 无效
    monkeypatch.setattr("app.core.redis.init_redis", _init)
    monkeypatch.setattr("app.core.redis.close_redis", _close)
    monkeypatch.setattr("app.core.redis.get_redis_client", lambda: client)
    monkeypatch.setattr("app.core.redis.ping_redis", AsyncMock(return_value=True))
    monkeypatch.setattr("app.main.init_redis", _init)
    monkeypatch.setattr("app.main.close_redis", _close)
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
    monkeypatch.setattr("app.main.seed_model_configs", AsyncMock())
    monkeypatch.setattr("app.main.ensure_schema_patches", AsyncMock())
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
    import app.core.database as database_module
    import app.main as main_mod

    # 确保 main 使用 conftest 重建后的 engine（避免仍指向 docker 主机名）
    monkeypatch.setattr(main_mod, "engine", database_module.engine)
    monkeypatch.setattr(main_mod, "SessionLocal", database_module.SessionLocal)
    monkeypatch.setattr(main_mod, "init_chroma", lambda: None)
    monkeypatch.setattr(main_mod, "close_chroma", lambda: None)
    monkeypatch.setattr("app.core.chroma.ping_chroma", lambda: True)

    async with main_mod.lifespan(main_mod.app):
        transport = ASGITransport(app=main_mod.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

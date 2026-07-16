"""pytest 公共配置。"""
import os
import sys
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("POSTGRES_HOST", "localhost")


@pytest_asyncio.fixture
async def client():
    """每个测试独立启动应用 lifespan，避免 event loop 与连接池跨用例冲突。"""
    from app.main import app, lifespan

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

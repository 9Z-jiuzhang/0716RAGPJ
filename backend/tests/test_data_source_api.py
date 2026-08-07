"""外部数据源 / API 客户端路由烟雾测试（需可用数据库）。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_capabilities_requires_auth(client: AsyncClient):
    res = await client.get("/api/v1/data-sources/capabilities")
    assert res.status_code in {401, 403}


@pytest.mark.asyncio
async def test_external_requires_api_key(client: AsyncClient):
    res = await client.get("/api/v1/external/knowledge-bases")
    assert res.status_code == 401

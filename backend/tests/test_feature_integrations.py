"""新增管理模块在真实 PostgreSQL 启动链路下的接口集成验收。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_admin_can_read_role_cache_ragas_and_guard_monitoring(client) -> None:
    """管理员应能访问角色缓存、RAGAS 记录和 Guard 拦截统计三个管理模块。"""
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Admin123!"},
    )
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    cache_response = await client.get("/api/v1/role-caches", headers=headers)
    assert cache_response.status_code == 200
    caches = cache_response.json()["data"]
    assert caches
    assert all(cache["interval_days"] >= 1 for cache in caches)
    assert all(cache["document_question_limit"] <= 20 for cache in caches)
    assert all(cache["history_question_limit"] <= 5 for cache in caches)

    ragas_response = await client.get("/api/v1/ragas/runs", headers=headers)
    assert ragas_response.status_code == 200
    ragas_data = ragas_response.json()["data"]
    assert isinstance(ragas_data["items"], list)
    assert ragas_data["total"] >= 0

    monitor_response = await client.get("/api/v1/monitor/stats", headers=headers)
    assert monitor_response.status_code == 200
    monitor_data = monitor_response.json()["data"]
    assert monitor_data["guard_blocked_24h"] >= 0
    assert monitor_data["guard_blocked_7d"] >= monitor_data["guard_blocked_24h"]
    assert isinstance(monitor_data["guard_recent_events"], list)

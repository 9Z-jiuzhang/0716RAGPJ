"""健康检查与认证基础冒烟测试。"""

import pytest


@pytest.mark.asyncio
async def test_health_returns_wrapped_response(client):
    res = await client.get("/api/v1/monitor/health")
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 0
    assert body["data"]["status"] in ("healthy", "degraded", "unhealthy")
    assert "postgres" in body["data"]["checks"]


@pytest.mark.asyncio
async def test_login_and_me(client):
    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    assert login.status_code == 200
    payload = login.json()
    assert payload["code"] == 0
    assert payload["data"]["access_token"]
    assert payload["data"]["expires_in"] == 30 * 60

    token = payload["data"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    user = me.json()["data"]
    assert user["username"] == "admin"
    assert "permissions" in user
    assert "admin" in user["roles"] or "user:read" in user["permissions"]


@pytest.mark.asyncio
async def test_disabled_user_gets_403(client):
    """禁用用户登录应返回 403（需先有可禁用测试账号，此处仅校验注册后禁用流程骨架）。"""
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "test_disabled_user",
            "password": "TestPass1!",
            "email": "disabled@example.com",
        },
    )
    if reg.status_code == 409:
        pytest.skip("测试用户已存在，跳过")
    assert reg.status_code == 201

    admin_login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    admin_token = admin_login.json()["data"]["access_token"]
    user_id = reg.json()["data"]["id"]

    patch = await client.patch(
        f"/api/v1/users/{user_id}/status",
        json={"status": "disabled"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch.status_code == 200

    denied = await client.post(
        "/api/v1/auth/login",
        json={"username": "test_disabled_user", "password": "TestPass1!"},
    )
    assert denied.status_code == 403

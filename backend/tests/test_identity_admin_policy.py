"""用户管理与角色权限优化的回归测试。"""
import uuid

import pytest


async def _admin_headers(client) -> dict[str, str]:
    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


@pytest.mark.asyncio
async def test_admin_can_create_user_but_cannot_reset_password(client):
    headers = await _admin_headers(client)
    suffix = uuid.uuid4().hex[:8]
    created = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": f"manager_{suffix}", "email": f"manager_{suffix}@example.com", "password": "ManagerPass1!"},
    )
    assert created.status_code == 201, created.text
    user = created.json()["data"]
    assert "user" in user["roles"]

    # 管理员不得再通过 API 重置任何用户密码。
    reset = await client.post(f"/api/v1/users/{user['id']}/reset-password", headers=headers, json={"new_password": "OtherPass1!"})
    # 接口已被移除，FastAPI 应返回 404，而不是仍保留路由后拒绝方法的 405。
    assert reset.status_code == 404


@pytest.mark.asyncio
async def test_role_creation_can_assign_permissions(client):
    headers = await _admin_headers(client)
    suffix = uuid.uuid4().hex[:8]
    created = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"reviewer_{suffix}", "description": "测试角色", "permission_codes": ["qa:ask", "kb:read"]},
    )
    assert created.status_code == 201, created.text
    assert set(created.json()["data"]["permissions"]) == {"qa:ask", "kb:read"}

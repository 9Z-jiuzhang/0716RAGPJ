"""当前用户修改密码接口测试。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_change_password_requires_old_and_confirm(client):
    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    mismatch = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"old_password": "Admin123!", "new_password": "Admin999!", "confirm_password": "Admin888!"},
    )
    assert mismatch.status_code == 400
    assert "不一致" in mismatch.json()["detail"]

    wrong_old = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"old_password": "WrongPass1!", "new_password": "Admin999!", "confirm_password": "Admin999!"},
    )
    assert wrong_old.status_code == 400
    assert "原密码" in wrong_old.json()["detail"]

    ok = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"old_password": "Admin123!", "new_password": "Admin999!", "confirm_password": "Admin999!"},
    )
    assert ok.status_code == 200
    assert ok.json()["code"] == 0

    denied = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    assert denied.status_code == 401

    restored_login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin999!"})
    assert restored_login.status_code == 200
    restore_token = restored_login.json()["data"]["access_token"]
    restore = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {restore_token}"},
        json={"old_password": "Admin999!", "new_password": "Admin123!", "confirm_password": "Admin123!"},
    )
    assert restore.status_code == 200


@pytest.mark.asyncio
async def test_super_admin_cannot_change_password_via_api(client):
    login = await client.post("/api/v1/auth/login", json={"username": "super", "password": "Super123!"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]

    res = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "Super123!", "new_password": "Super999!", "confirm_password": "Super999!"},
    )
    assert res.status_code == 403
    assert "SUPER_ADMIN_PASSWORD" in res.json()["detail"]

"""知识库 CRUD 冒烟测试。"""

from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_kb_create_list_get_delete(client):
    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    name = f"pytest-kb-{uuid4().hex[:8]}"
    created = await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={
            "name": name,
            "type": "general",
            "tags": ["pytest"],
            "description": "smoke",
            "visibility": "restricted",
            "embedding_model": "text-embedding-v3",
            "chunk_size": 500,
            "chunk_overlap": 50,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == 0
    kb_id = body["data"]["id"]

    listed = await client.get("/api/v1/knowledge-bases", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == kb_id for item in listed.json()["data"]["items"])

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["name"] == name

    deleted = await client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    assert deleted.status_code == 200

"""大模型管理 / 分段预览 / 病毒扫描 / stats 趋势 冒烟测试。"""

from uuid import uuid4

import pytest

from app.services.security_scan import MalwareDetectedError, virus_scan


def test_virus_scan_blocks_eicar():
    with pytest.raises(MalwareDetectedError):
        virus_scan(
            "eicar.txt",
            b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*",
        )


def test_virus_scan_allows_plain_text():
    virus_scan("note.txt", b"hello knowledge base")


@pytest.mark.asyncio
async def test_models_list_and_stats_trends(client):
    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    models = await client.get("/api/v1/models?page=1&page_size=20", headers=headers)
    assert models.status_code == 200, models.text
    body = models.json()
    assert body["code"] == 0
    assert "items" in body["data"]
    assert body["data"]["total"] >= 1

    stats = await client.get("/api/v1/monitor/stats", headers=headers)
    assert stats.status_code == 200
    data = stats.json()["data"]
    assert len(data["qa_trend_7d"]) == 7
    assert len(data["hit_rate_trend_7d"]) == 7


@pytest.mark.asyncio
async def test_segment_preview_requires_text(client):
    """无解析文本时预览应返回 400；有 KB 时可创建空文档场景跳过。"""
    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    name = f"preview-kb-{uuid4().hex[:8]}"
    created = await client.post(
        "/api/v1/knowledge-bases/",
        headers=headers,
        json={
            "name": name,
            "type": "general",
            "tags": [],
            "visibility": "restricted",
            "embedding_model": "text-embedding-v3",
        },
    )
    assert created.status_code == 200, created.text
    kb_id = created.json()["data"]["id"]

    # 不存在的文档
    missing = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/{uuid4()}/segment-preview",
        headers=headers,
        json={"chunk_size": 200, "chunk_overlap": 20},
    )
    assert missing.status_code in (404, 400, 422)

    await client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)

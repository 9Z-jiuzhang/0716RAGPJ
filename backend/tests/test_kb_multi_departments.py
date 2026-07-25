"""知识库多部门访问范围测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.core.constants import normalize_departments, primary_department


def test_normalize_departments_guest_first() -> None:
    assert normalize_departments(["B", "guest", "A", "B"]) == ["GUEST", "A", "B"]
    assert primary_department(["A", "GUEST"]) == "GUEST"
    assert primary_department([]) is None


@pytest.mark.asyncio
async def test_kb_multi_department_create_and_dept_append(client):
    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    name = f"pytest-multi-dept-{uuid4().hex[:8]}"
    created = await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={
            "name": name,
            "type": "general",
            "tags": ["pytest"],
            "departments": ["A", "B"],
            "embedding_model": "text-embedding-v3",
            "chunk_size": 500,
            "chunk_overlap": 50,
        },
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    kb_id = data["id"]
    assert set(data["departments"]) == {"A", "B"}
    assert data["department"] in {"A", "B"}
    assert data["visibility"] == "restricted"

    depts = await client.get("/api/v1/departments?page=1&page_size=50", headers=headers)
    assert depts.status_code == 200
    items = depts.json()["data"]["items"]
    dept_a = next(d for d in items if d["code"] == "A")
    dept_b = next(d for d in items if d["code"] == "B")
    detail_a = await client.get(f"/api/v1/departments/{dept_a['id']}", headers=headers)
    assert any(k["id"] == kb_id for k in detail_a.json()["data"]["knowledge_bases"])

    # 部门侧再次关联应为追加/幂等，不丢掉 A
    add_b = await client.post(
        f"/api/v1/departments/{dept_b['id']}/knowledge-bases",
        headers=headers,
        json={"kb_ids": [kb_id]},
    )
    assert add_b.status_code == 200, add_b.text

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    assert set(detail.json()["data"]["departments"]) == {"A", "B"}

    # 仅从 B 解除，A 仍在
    rm = await client.delete(
        f"/api/v1/departments/{dept_b['id']}/knowledge-bases/{kb_id}",
        headers=headers,
    )
    assert rm.status_code == 200, rm.text
    detail2 = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    assert detail2.json()["data"]["departments"] == ["A"]

    # 含 GUEST 时可见性为 public
    upd = await client.put(
        f"/api/v1/knowledge-bases/{kb_id}",
        headers=headers,
        json={"departments": ["A", "GUEST"]},
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()["data"]
    assert "GUEST" in body["departments"]
    assert body["visibility"] == "public"
    assert body["department"] == "GUEST"

    await client.delete(f"/api/v1/knowledge-bases/{kb_id}?permanent=true", headers=headers)

"""可观测性：健康检查、metrics、stats、Langfuse no-op。"""

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
async def test_metrics_exposes_prometheus_text(client):
    # 先打一次健康检查，确保有 HTTP 指标样本
    await client.get("/api/v1/monitor/health")
    res = await client.get("/metrics")
    assert res.status_code == 200
    text = res.text
    assert "http_requests_total" in text
    assert "HELP" in text or "# HELP" in text


@pytest.mark.asyncio
async def test_monitor_stats_requires_auth(client):
    denied = await client.get("/api/v1/monitor/stats")
    assert denied.status_code in (401, 403)

    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    ok = await client.get("/api/v1/monitor/stats", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert "user_count" in data
    assert "qa_trend_7d" in data
    assert len(data["qa_trend_7d"]) == 7
    assert "hit_rate_trend_7d" in data
    assert "kb_count" in data
    assert "doc_count" in data
    assert data["user_count"] >= 1


@pytest.mark.asyncio
async def test_langfuse_noop_when_disabled():
    from app.services.langfuse_service import LangfuseService, redact_text

    assert redact_text("hello") == "hello"
    assert "truncated" in redact_text("x" * 1000, max_len=10)

    svc = LangfuseService()
    # 测试环境通常无密钥，应为 no-op
    trace = svc.start_trace(name="unit_test", input_text="secret question")
    svc.span_embedding(trace, model="test", input_text="abc", token_count=3)
    svc.span_retrieval(trace, query="q", context_summary="ctx", hit_count=1)
    svc.span_generation(trace, model="test", prompt="p", completion="c", input_tokens=1, output_tokens=2)
    svc.score_feedback(trace, value=1.0)
    svc.flush()

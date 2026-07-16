"""智能问答 API 集成测试（Mock 流水线，无需真实 LLM/DB）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient


async def _fake_pipeline_run(*_args: Any, **_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
    """模拟完整 SSE 事件序列。"""
    yield {"event": "citations", "citations": []}
    yield {"event": "chunk", "content": "测试回答"}
    yield {
        "event": "done",
        "session_id": str(uuid4()),
        "message_id": str(uuid4()),
        "request_id": "req-test",
        "confidence": "low",
    }


@pytest.mark.asyncio
async def test_health_endpoint(client_mocked: AsyncClient) -> None:
    resp = await client_mocked.get("/api/v1/monitor/health")
    assert resp.status_code == 200
    body = resp.json()
    # 对齐统一响应包装 BaseResponse
    assert body.get("code") == 0
    data = body.get("data") or body
    assert data["status"] in ("healthy", "degraded", "unhealthy", "ok")


@pytest.mark.asyncio
@patch("app.api.v1.qa.qa_pipeline.run", side_effect=_fake_pipeline_run)
async def test_ask_sse_event_sequence(_mock_run: AsyncMock, client_mocked: AsyncClient) -> None:
    """验证 /qa/ask 返回 SSE 且事件顺序包含 chunk 与 done。"""
    async with client_mocked.stream(
        "POST",
        "/api/v1/qa/ask",
        json={"question": "什么是 RAG？"},
        headers={"X-Guest-Id": "guest-test-001", "X-Request-Id": "req-1"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events: list[str] = []
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())

    assert "chunk" in events
    assert "done" in events


@pytest.mark.asyncio
async def test_sessions_requires_auth(client_mocked: AsyncClient) -> None:
    resp = await client_mocked.get("/api/v1/qa/sessions")
    assert resp.status_code == 401

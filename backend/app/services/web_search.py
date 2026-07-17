"""可选轻量联网检索（无 API Key），供问答无命中兜底参考。

默认关闭（QA_FALLBACK_WEB_SEARCH_ENABLED=false）。
使用 DuckDuckGo Instant Answer JSON，失败时静默返回空列表，不影响主流程。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def search_web(query: str, *, max_results: int = 3) -> list[dict[str, str]]:
    """返回 [{title, snippet, url}, ...]；不可用时返回 []。"""
    cleaned = (query or "").strip()
    if not cleaned or not settings.QA_FALLBACK_WEB_SEARCH_ENABLED:
        return []

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": cleaned, "format": "json", "no_html": 1, "skip_disambig": 1},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("联网检索失败，跳过：%s", exc)
        return []

    results: list[dict[str, str]] = []
    abstract = (data.get("AbstractText") or "").strip()
    abstract_url = (data.get("AbstractURL") or "").strip()
    heading = (data.get("Heading") or cleaned).strip()
    if abstract:
        results.append({"title": heading, "snippet": abstract, "url": abstract_url})

    for item in data.get("RelatedTopics") or []:
        if len(results) >= max_results:
            break
        if not isinstance(item, dict):
            continue
        text = (item.get("Text") or "").strip()
        url = (item.get("FirstURL") or "").strip()
        if text:
            results.append({"title": text[:80], "snippet": text, "url": url})

    return results[:max_results]


def format_web_results(results: list[dict[str, str]]) -> str:
    """格式化为提示词片段。"""
    if not results:
        return "（无联网检索结果）"
    parts: list[str] = []
    for i, item in enumerate(results, start=1):
        title = item.get("title") or "来源"
        snippet = item.get("snippet") or ""
        url = item.get("url") or ""
        line = f"[{i}] {title}\n{snippet}"
        if url:
            line += f"\n链接：{url}"
        parts.append(line)
    return "\n\n".join(parts)

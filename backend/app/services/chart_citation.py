"""图表引用：新/旧逻辑集中开关、元数据规范化与安全出参。"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

_PAGE_LIST_KEYS = ("pages", "chart_pages", "source_pages", "pdf_pages")

# 仅排障/流水线内部使用，禁止出现在 API citation 出参
_CITATION_DEBUG_KEYS = frozenset(
    {
        "page_range",
        "chart_page_count",
        "has_pdf_charts",
        "page_start",
        "page_end",
        "pdf_page",
        "source_page",
        *_PAGE_LIST_KEYS,
    }
)


def chart_citation_use_legacy() -> bool:
    """true 时与 develop 一致：按 chart_page_count 展开整本页缩略图。"""
    return bool(settings.CHART_CITATION_USE_LEGACY_LOGIC)


def max_citation_chart_pages() -> int:
    return max(1, int(settings.MAX_CITATION_CHART_PAGES))


def citation_chart_display_limit() -> int:
    return max(1, int(settings.QA_CITATION_CHART_DISPLAY_LIMIT))


def _coerce_page_int(value: Any) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def legacy_pages_from_metadata(metadata: dict[str, Any] | None) -> list[int]:
    """develop 行为：chart_page_count>0 时展开 1..N。"""
    meta = metadata or {}
    try:
        n = int(meta.get("chart_page_count") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return []
    return list(range(1, n + 1))


def stringify_pages_in_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """向量入库前将页码列表压成标量字符串，避免 Chroma 丢弃 list 字段。"""
    if chart_citation_use_legacy():
        return dict(metadata or {})
    meta = dict(metadata or {})
    for key in _PAGE_LIST_KEYS:
        raw = meta.get(key)
        if isinstance(raw, (list, tuple, set)):
            parts: list[str] = []
            for item in raw:
                page = _coerce_page_int(item)
                if page is not None:
                    parts.append(str(page))
            if parts:
                meta[key] = ",".join(parts)
            else:
                meta.pop(key, None)
        elif isinstance(raw, str) and raw.strip():
            meta[key] = raw.strip()
    return meta


def normalize_chunk_metadata_for_storage(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """PG chunk_metadata 与 Chroma 共用：新逻辑下 stringify 页码列表。"""
    return stringify_pages_in_metadata(metadata)


def citation_safe_citation(citation: dict[str, Any]) -> dict[str, Any]:
    """API/SSE 出参剥离 debug 字段，避免下游依赖 chart_page_count 等。"""
    out = dict(citation)
    for key in _CITATION_DEBUG_KEYS:
        out.pop(key, None)
    return out


def format_page_range(pages: list[int]) -> str:
    if not pages:
        return ""
    start, end = min(pages), max(pages)
    return str(start) if start == end else f"{start}-{end}"


def apply_pdf_page_to_metadata(pages: list[int], metadata: dict[str, Any] | None) -> dict[str, Any]:
    """分段元数据：新逻辑只写单点 page；跨页保留 page_range 仅排障。"""
    meta = dict(metadata or {})
    if not pages:
        return meta
    start = min(pages)
    meta["page"] = start
    if len(pages) > 1:
        meta["page_range"] = format_page_range(pages)
    meta.pop("page_start", None)
    meta.pop("page_end", None)
    return meta

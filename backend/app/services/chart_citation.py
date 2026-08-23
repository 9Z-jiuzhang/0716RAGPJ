"""图表引用：新/旧逻辑集中开关、元数据规范化与安全出参。"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.core.config import settings

_PAGE_LIST_KEYS = ("pages", "chart_pages", "source_pages", "pdf_pages")

CHART_REF_KIND_ASSET: Literal["asset"] = "asset"
CHART_REF_KIND_PAGE: Literal["page"] = "page"

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


def _citation_page_metadata(citation: dict[str, Any]) -> dict[str, Any]:
    return {
        "page": citation.get("page"),
        "pages": citation.get("pages"),
        "page_start": citation.get("page_start"),
        "page_end": citation.get("page_end"),
        "chart_page_count": citation.get("chart_page_count"),
        "block_type": citation.get("block_type"),
        "pdf_page": citation.get("pdf_page"),
        "source_page": citation.get("source_page"),
    }


def build_chart_refs(citation: dict[str, Any], *, max_pages: int | None = None) -> list[dict[str, Any]]:
    """
    为单条 citation 构建 chart_refs（不含 URL；前端或 GET 端点按需拼）。

    契约：
    - kind=asset：block_type=image 且 block_id/asset_path 有效
    - kind=page：分段元数据页码（layout 图块仅块级 page）
    - 同 citation 内：已有 asset 且 page 相同 → 不生成 page ref
    - 长度 ≤ max_pages（默认 MAX_CITATION_CHART_PAGES）
    """
    limit = max(1, int(max_pages or max_citation_chart_pages()))
    from app.services.document_charts import pages_for_citation_metadata

    refs: list[dict[str, Any]] = []
    block_type = str(citation.get("block_type") or "").lower()
    block_id = str(citation.get("block_id") or "").strip()
    asset_path = str(citation.get("asset_path") or "").strip()
    asset_pages: set[int] = set()

    if block_type == "image" and block_id and asset_path:
        from app.services.asset_citation import asset_citation_enabled, normalize_asset_id

        if asset_citation_enabled():
            normalized = normalize_asset_id(block_id)
            if normalized:
                page = _coerce_page_int(citation.get("page"))
                asset_ref: dict[str, Any] = {
                    "kind": CHART_REF_KIND_ASSET,
                    "asset_id": normalized,
                }
                if page is not None:
                    asset_ref["page"] = page
                    asset_pages.add(page)
                caption = str(citation.get("caption") or "").strip()
                if caption:
                    asset_ref["caption"] = caption
                refs.append(asset_ref)

    wanted_pages = pages_for_citation_metadata(_citation_page_metadata(citation), max_pages=limit)
    for page in wanted_pages:
        if page in asset_pages:
            continue
        refs.append({"kind": CHART_REF_KIND_PAGE, "page": page})
        if len(refs) >= limit:
            break

    return refs[:limit]


def attach_chart_refs_to_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    为 citations 附加 chart_refs，并清空 images（P1 懒加载；URL 由 GET chart/asset 按需生成）。

    跨 citation：同 doc_id+page 去重；asset 优先（同页已有 page 则跳过 page ref）。
    """
    if not citations:
        return citations

    from app.core.metrics import chart_ref_dedup_skipped_total, total_chart_refs_total

    max_pages = max_citation_chart_pages()
    covered_pages: dict[str, set[int]] = {}
    covered_assets: dict[str, set[str]] = {}

    indexed_candidates: list[tuple[int, dict[str, Any], str]] = []
    for idx, citation in enumerate(citations):
        doc_id = str(citation.get("doc_id") or "").strip()
        for ref in build_chart_refs(citation, max_pages=max_pages):
            indexed_candidates.append((idx, ref, doc_id))

    # asset 覆盖同 doc+page 的 page ref（跨 citation，asset 优先）
    asset_pages_global: set[tuple[str, int]] = set()
    for _, ref, doc_id in indexed_candidates:
        if ref.get("kind") != CHART_REF_KIND_ASSET or not doc_id:
            continue
        page = _coerce_page_int(ref.get("page"))
        if page is not None:
            asset_pages_global.add((doc_id, page))

    per_citation: dict[int, list[dict[str, Any]]] = {i: [] for i in range(len(citations))}

    for idx, ref, doc_id in indexed_candidates:
        kind = str(ref.get("kind") or "")
        if kind == CHART_REF_KIND_ASSET:
            asset_id = str(ref.get("asset_id") or "").strip()
            if not asset_id:
                chart_ref_dedup_skipped_total.inc()
                continue
            asset_keys = covered_assets.setdefault(doc_id, set())
            if asset_id in asset_keys:
                chart_ref_dedup_skipped_total.inc()
                continue
            asset_keys.add(asset_id)
            page = _coerce_page_int(ref.get("page"))
            if doc_id and page is not None:
                covered_pages.setdefault(doc_id, set()).add(page)
            per_citation[idx].append(ref)
            total_chart_refs_total.inc()
            continue

        if kind == CHART_REF_KIND_PAGE:
            page = _coerce_page_int(ref.get("page"))
            if page is None:
                chart_ref_dedup_skipped_total.inc()
                continue
            if doc_id and (doc_id, page) in asset_pages_global:
                chart_ref_dedup_skipped_total.inc()
                continue
            if doc_id and page in covered_pages.get(doc_id, set()):
                chart_ref_dedup_skipped_total.inc()
                continue
            if doc_id:
                covered_pages.setdefault(doc_id, set()).add(page)
            if len(per_citation[idx]) >= max_pages:
                chart_ref_dedup_skipped_total.inc()
                continue
            per_citation[idx].append(ref)
            total_chart_refs_total.inc()

    for idx, citation in enumerate(citations):
        chart_refs = per_citation.get(idx, [])[:max_pages]
        sanitized = citation_safe_citation(citation)
        sanitized["chart_refs"] = chart_refs
        sanitized["images"] = []
        citations[idx] = sanitized

    return citations


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

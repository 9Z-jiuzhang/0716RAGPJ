"""文档图表页资产：PDF 栅格化入库，供问答引用展示。"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from app.services import storage
from app.services.chart_citation import (
    chart_citation_use_legacy,
    legacy_pages_from_metadata,
    max_citation_chart_pages,
)
from app.services.markitdown_export import _rasterize_pdf_pages

logger = logging.getLogger(__name__)

_PAGE_FILE_RE = re.compile(r"^page-(\d{2})\.png$", re.IGNORECASE)
# 兼容旧 import；运行时上限读 settings
MAX_CITATION_CHART_PAGES = 5

_chart_page_bounds_cache: dict[str, int] = {}


def chart_prefix(kb_id: uuid.UUID | str, doc_id: uuid.UUID | str) -> str:
    return f"{kb_id}/{doc_id}/charts/"


def chart_object_name(kb_id: uuid.UUID | str, doc_id: uuid.UUID | str, page: int) -> str:
    return f"{kb_id}/{doc_id}/charts/page-{int(page):02d}.png"


def chart_api_url(doc_id: uuid.UUID | str, page: int) -> str:
    """访客/登录均可带 cookie/token 访问的相对 API 路径。"""
    return f"/api/v1/qa/documents/{doc_id}/charts/page-{int(page):02d}.png"


def persist_pdf_chart_pages(
    *,
    kb_id: uuid.UUID | str,
    doc_id: uuid.UUID | str,
    pdf_bytes: bytes,
    zoom: float = 2.0,
) -> int:
    """将 PDF 每页栅格化为 PNG 写入 MinIO，返回页数。"""
    pages = _rasterize_pdf_pages(pdf_bytes, zoom=zoom)
    if not pages:
        return 0
    for idx, png in enumerate(pages, start=1):
        storage.put_object_bytes(
            chart_object_name(kb_id, doc_id, idx),
            png,
            content_type="image/png",
        )
    logger.info("persisted %s chart pages for doc=%s", len(pages), doc_id)
    return len(pages)


def list_chart_pages(kb_id: uuid.UUID | str, doc_id: uuid.UUID | str) -> list[int]:
    """列出已入库图表页码（升序）。"""
    names = storage.list_object_names(chart_prefix(kb_id, doc_id))
    pages: list[int] = []
    for name in names:
        base = name.rsplit("/", 1)[-1]
        m = _PAGE_FILE_RE.match(base)
        if m:
            pages.append(int(m.group(1)))
    sorted_pages = sorted(set(pages))
    key = str(doc_id)
    if sorted_pages:
        _chart_page_bounds_cache[key] = sorted_pages[-1]
    return sorted_pages


def get_chart_max_page(kb_id: uuid.UUID | str, doc_id: uuid.UUID | str) -> int:
    """进程内缓存文档最大图表页，避免每条 citation 列举对象存储。"""
    key = str(doc_id)
    cached = _chart_page_bounds_cache.get(key)
    if cached is not None:
        return cached
    pages = list_chart_pages(kb_id, doc_id)
    max_page = pages[-1] if pages else 0
    _chart_page_bounds_cache[key] = max_page
    return max_page


def delete_document_charts(kb_id: uuid.UUID | str, doc_id: uuid.UUID | str) -> None:
    """删除文档下全部图表对象（文档删除时调用）。"""
    _chart_page_bounds_cache.pop(str(doc_id), None)
    prefix = chart_prefix(kb_id, doc_id)
    for name in storage.list_object_names(prefix):
        storage.delete_object(name)


def citation_images_for_doc(*, kb_id: uuid.UUID | str, doc_id: uuid.UUID | str) -> list[dict]:
    """组装 citation.images 列表（整本文档全部页；问答展示请用 pages_for_citation_metadata）。"""
    pages = list_chart_pages(kb_id, doc_id)
    return [{"page": p, "url": chart_api_url(doc_id, p)} for p in pages]


def citation_images_for_pages(
    doc_id: uuid.UUID | str,
    pages: list[int],
    *,
    kb_id: uuid.UUID | str | None = None,
    max_page: int | None = None,
) -> list[dict[str, Any]]:
    """按指定页码组装 citation.images；越界页丢弃并记 warning。"""
    if chart_citation_use_legacy():
        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for page in pages:
            p = int(page)
            if p <= 0 or p in seen:
                continue
            seen.add(p)
            out.append({"page": p, "url": chart_api_url(doc_id, p)})
        return out

    if max_page is None and kb_id is not None:
        max_page = get_chart_max_page(kb_id, doc_id)

    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in pages:
        p = int(page)
        if p <= 0 or p in seen:
            continue
        if max_page is not None and max_page > 0 and p > max_page:
            logger.warning(
                "citation chart page out of bounds doc=%s page=%s max=%s",
                doc_id,
                p,
                max_page,
            )
            continue
        seen.add(p)
        out.append({"page": p, "url": chart_api_url(doc_id, p)})
    return out


def _coerce_page_int(value: Any) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def pages_for_citation_metadata(
    metadata: dict[str, Any] | None,
    *,
    max_pages: int | None = None,
) -> list[int]:
    """从分段元数据解析「与本命中相关」的 PDF 页码。"""
    if chart_citation_use_legacy():
        return legacy_pages_from_metadata(metadata)

    limit = max(1, int(max_pages or max_citation_chart_pages()))
    meta = metadata or {}

    # layout 图/表块：块级 page 最可信，单独命中时只展示该页
    block_type = str(meta.get("block_type") or "").lower()
    if block_type in ("image", "table"):
        block_page = _coerce_page_int(meta.get("page"))
        if block_page is not None:
            return [block_page][:limit]

    pages: set[int] = set()

    for key in ("page", "pdf_page", "source_page"):
        page = _coerce_page_int(meta.get(key))
        if page is not None:
            pages.add(page)

    for key in ("pages", "chart_pages", "source_pages", "pdf_pages"):
        raw = meta.get(key)
        if isinstance(raw, (list, tuple, set)):
            for item in raw:
                page = _coerce_page_int(item)
                if page is not None:
                    pages.add(page)
        elif isinstance(raw, str) and raw.strip():
            for part in re.split(r"[,，\s]+", raw.strip()):
                page = _coerce_page_int(part)
                if page is not None:
                    pages.add(page)

    ordered = sorted(pages)
    return ordered[:limit]


def ensure_pdf_charts(
    *,
    kb_id: uuid.UUID | str,
    doc_id: uuid.UUID | str,
    pdf_bytes: bytes | None = None,
    file_path: str | None = None,
    pages: list[int] | None = None,
) -> list[dict]:
    """若尚无图表则按需栅格化。

    - pages 有值：只返回这些页的 images（问答引用路径）
    - pages 为空列表：不返回整本文档缩略图
    - pages 为 None：兼容旧调用，返回全部页（导出/管理场景）
    """
    existing_all = citation_images_for_doc(kb_id=kb_id, doc_id=doc_id)
    if not existing_all:
        data = pdf_bytes
        if data is None and file_path:
            data = storage.download_bytes(file_path)
        if not data:
            return []
        persist_pdf_chart_pages(kb_id=kb_id, doc_id=doc_id, pdf_bytes=data)
        existing_all = citation_images_for_doc(kb_id=kb_id, doc_id=doc_id)

    if pages is None:
        return existing_all
    wanted = [p for p in pages if _coerce_page_int(p)]
    if not wanted:
        return []
    return citation_images_for_pages(doc_id, wanted, kb_id=kb_id)


def parse_chart_filename(filename: str) -> int | None:
    m = _PAGE_FILE_RE.match((filename or "").strip())
    return int(m.group(1)) if m else None

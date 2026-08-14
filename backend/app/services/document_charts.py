"""文档图表页资产：PDF 栅格化入库，供问答引用展示。"""

from __future__ import annotations

import logging
import re
import uuid

from app.services import storage
from app.services.markitdown_export import _rasterize_pdf_pages

logger = logging.getLogger(__name__)

_PAGE_FILE_RE = re.compile(r"^page-(\d{2})\.png$", re.IGNORECASE)


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
    return sorted(set(pages))


def delete_document_charts(kb_id: uuid.UUID | str, doc_id: uuid.UUID | str) -> None:
    """删除文档下全部图表对象（文档删除时调用）。"""
    prefix = chart_prefix(kb_id, doc_id)
    for name in storage.list_object_names(prefix):
        storage.delete_object(name)


def citation_images_for_doc(*, kb_id: uuid.UUID | str, doc_id: uuid.UUID | str) -> list[dict]:
    """组装 citation.images 列表。"""
    pages = list_chart_pages(kb_id, doc_id)
    return [{"page": p, "url": chart_api_url(doc_id, p)} for p in pages]


def ensure_pdf_charts(
    *,
    kb_id: uuid.UUID | str,
    doc_id: uuid.UUID | str,
    pdf_bytes: bytes | None = None,
    file_path: str | None = None,
) -> list[dict]:
    """若尚无图表则按需栅格化；返回 images 列表。"""
    existing = citation_images_for_doc(kb_id=kb_id, doc_id=doc_id)
    if existing:
        return existing
    data = pdf_bytes
    if data is None and file_path:
        data = storage.download_bytes(file_path)
    if not data:
        return []
    persist_pdf_chart_pages(kb_id=kb_id, doc_id=doc_id, pdf_bytes=data)
    return citation_images_for_doc(kb_id=kb_id, doc_id=doc_id)


def parse_chart_filename(filename: str) -> int | None:
    m = _PAGE_FILE_RE.match((filename or "").strip())
    return int(m.group(1)) if m else None

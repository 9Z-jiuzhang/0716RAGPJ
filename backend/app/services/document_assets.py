"""文档内嵌图 asset 解析与下载（MinIO 代理，禁止 presigned）。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk
from app.services.asset_citation import normalize_asset_id

logger = logging.getLogger(__name__)

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def infer_mime_type(object_key: str, fallback: str = "image/png") -> str:
    key = (object_key or "").lower()
    for ext, mime in _MIME_BY_EXT.items():
        if key.endswith(ext):
            return mime
    return fallback or "image/png"


async def resolve_document_asset(
    db: AsyncSession,
    doc_id: uuid.UUID,
    asset_id: str,
) -> tuple[str, str] | None:
    """按 block_id（asset_id）查找 MinIO object key 与 mime。"""
    normalized = normalize_asset_id(asset_id)
    if normalized is None:
        return None

    rows = (
        await db.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == doc_id,
                DocumentChunk.is_enabled.is_(True),
            )
            .limit(400)
        )
    ).all()

    for row in rows:
        meta: dict[str, Any] = row.chunk_metadata or {}
        block_id = str(meta.get("block_id") or "").strip()
        if block_id != normalized:
            continue
        asset_path = str(meta.get("asset_path") or "").strip()
        if not asset_path:
            continue
        mime = str(meta.get("mime_type") or "").strip() or infer_mime_type(asset_path)
        return asset_path, mime

    logger.info("asset not found doc=%s asset_id=%s", doc_id, normalized)
    return None

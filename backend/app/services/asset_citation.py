"""单图 asset 引用：代理 API，禁止 MinIO presigned 直出。"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

_ASSET_ID_RE = re.compile(r"^[a-f0-9]{8,16}$", re.I)


def asset_citation_enabled() -> bool:
    return bool(settings.ASSET_CITATION_ENABLED)


def asset_api_url(doc_id: str, asset_id: str) -> str:
    return f"/api/v1/qa/documents/{doc_id}/assets/{asset_id}"


def normalize_asset_id(asset_id: str) -> str | None:
    cleaned = (asset_id or "").strip()
    if not cleaned or not _ASSET_ID_RE.match(cleaned):
        return None
    return cleaned


def citation_asset_image(
    *,
    doc_id: str,
    asset_id: str,
    mime_type: str = "",
    caption: str = "",
) -> dict[str, Any]:
    return {
        "kind": "asset",
        "asset_id": asset_id,
        "url": asset_api_url(doc_id, asset_id),
        "mime_type": mime_type or "image/png",
        "caption": caption or "",
    }


def merge_citation_images(
    citation: dict[str, Any],
    *,
    page_images: list[dict[str, Any]] | None = None,
    asset_images: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """asset 优先，其次 page 级图表。"""
    out: list[dict[str, Any]] = []
    for img in asset_images or []:
        if img.get("url"):
            out.append(dict(img))
    for img in page_images or []:
        if img.get("url"):
            tagged = dict(img)
            tagged.setdefault("kind", "page")
            out.append(tagged)
    return out

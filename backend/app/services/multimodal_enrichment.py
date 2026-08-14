"""表格/图片摘要与 VLM 描述（Multi-vector 入库）。"""

from __future__ import annotations

import base64
import logging
from typing import Any

from app.core.config import settings
from app.services.llm import LLMService, LLMServiceError, llm_service

logger = logging.getLogger(__name__)

_TABLE_SUMMARY_PROMPT = (
    "请用中文详细概括下面表格的主题、关键字段与重要数值趋势。"
    "不要编造表中不存在的信息。只输出摘要正文。"
)
_IMAGE_CAPTION_PROMPT = (
    "请详细描述这张图片的内容。如果是图表，请提取关键数据趋势；"
    "如果是架构图或流程图，请解释各模块关系。只输出描述正文。"
)


async def summarize_table(markdown_or_html: str) -> str:
    """LLM 表格摘要；失败时回退截断原文。"""
    text = (markdown_or_html or "").strip()
    if not text:
        return ""
    if not settings.MULTIMODAL_SUMMARY_ENABLED:
        return _fallback_summary(text, prefix="表格内容")
    try:
        summary = await llm_service.chat(
            [
                {"role": "system", "content": _TABLE_SUMMARY_PROMPT},
                {"role": "user", "content": text[:12000]},
            ],
            temperature=0.2,
            max_tokens=settings.MULTIMODAL_SUMMARY_MAX_TOKENS,
            extra={"enable_thinking": False} if settings.LLM_ENABLE_THINKING else None,
        )
        return (summary or "").strip() or _fallback_summary(text, prefix="表格内容")
    except Exception as exc:
        logger.warning("table summary failed: %s", exc)
        return _fallback_summary(text, prefix="表格内容")


async def caption_image(
    *,
    caption_hint: str,
    image_bytes: bytes | None,
    mime_type: str = "image/png",
) -> str:
    """VLM 图像描述；无图或失败时用提示/启发式。"""
    hint = (caption_hint or "").strip()
    if not settings.MULTIMODAL_VLM_ENABLED or not image_bytes:
        return hint or "文档内嵌图片"
    try:
        vlm = _vlm_client()
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type or 'image/png'};base64,{b64}"
        # OpenAI 兼容多模态 message content
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _IMAGE_CAPTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        summary = await vlm.chat(
            messages,  # type: ignore[arg-type]
            temperature=0.2,
            max_tokens=settings.MULTIMODAL_SUMMARY_MAX_TOKENS,
            extra={"enable_thinking": False} if settings.LLM_ENABLE_THINKING else None,
        )
        return (summary or "").strip() or hint or "文档内嵌图片"
    except Exception as exc:
        logger.warning("image caption failed: %s", exc)
        return hint or "文档内嵌图片"


def _vlm_client() -> LLMService:
    return LLMService(
        model=(settings.VLM_MODEL or "qwen-vl-plus").strip(),
        api_base=(settings.VLM_BASE_URL or "").strip() or None,
        api_key=(settings.VLM_API_KEY or "").strip() or None,
        timeout_seconds=settings.VLM_TIMEOUT_SECONDS,
        default_max_tokens=settings.MULTIMODAL_SUMMARY_MAX_TOKENS,
    )


def _fallback_summary(text: str, *, prefix: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 240:
        return f"{prefix}：{compact}"
    return f"{prefix}：{compact[:240]}…"


async def enrich_chunk_metadata(
    *,
    block_type: str,
    parent_content: str,
    structure_html: str = "",
    structure_md: str = "",
    asset_path: str = "",
    caption_hint: str = "",
    image_bytes: bytes | None = None,
    mime_type: str = "",
    use_llm: bool = True,
) -> dict[str, Any]:
    """为表/图块生成摘要元数据（向量化用 summary，回填用 parent_content）。"""
    meta: dict[str, Any] = {
        "block_type": block_type,
        "parent_content": parent_content,
        "structure_html": structure_html,
        "structure_md": structure_md or parent_content,
        "asset_path": asset_path,
        "is_summary_vector": True,
    }
    if block_type == "table":
        src = structure_md or parent_content
        if use_llm:
            summary = await summarize_table(src)
        else:
            summary = _fallback_summary(src, prefix="表格内容")
    elif block_type == "image":
        if use_llm:
            summary = await caption_image(
                caption_hint=caption_hint or parent_content,
                image_bytes=image_bytes,
                mime_type=mime_type or "image/png",
            )
        else:
            summary = (caption_hint or parent_content or "文档内嵌图片").strip() or "文档内嵌图片"
    else:
        summary = parent_content
    meta["summary"] = summary
    meta["caption"] = caption_hint or summary
    return meta

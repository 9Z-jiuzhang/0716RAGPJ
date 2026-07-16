"""分段规则引擎。【对齐手册 §5.5.5】"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.enums import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_SEPARATORS,
    DEFAULT_SPLIT_MODE,
    SplitMode,
)


@dataclass
class ChunkPreview:
    chunk_index: int
    content: str
    char_count: int
    metadata: dict[str, Any]


def default_rules() -> dict[str, Any]:
    return {
        "chunk_size": DEFAULT_CHUNK_SIZE,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "separators": list(DEFAULT_SEPARATORS),
        "split_mode": DEFAULT_SPLIT_MODE,
        # P2迭代开发，当前仅配置存储，不启用语义切分
        "enable_semantic": False,
    }


def merge_rules(base: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    rules = default_rules()
    if base:
        rules.update({k: v for k, v in base.items() if v is not None})
    if patch:
        rules.update({k: v for k, v in patch.items() if v is not None})
    # P2迭代开发，当前仅配置存储，不启用语义切分
    rules["enable_semantic"] = bool(rules.get("enable_semantic", False))
    return rules


def split_text(text: str, rules: dict[str, Any] | None = None) -> list[ChunkPreview]:
    """按 split_mode 分段。若 enable_semantic=True 也忽略，仍走规则切分。"""
    rules = merge_rules(None, rules)
    # P2迭代开发，当前仅配置存储，不启用语义切分
    _ = rules.get("enable_semantic", False)
    mode = (rules.get("split_mode") or SplitMode.FIXED.value).lower()
    chunk_size = int(rules.get("chunk_size") or DEFAULT_CHUNK_SIZE)
    overlap = int(rules.get("chunk_overlap") or DEFAULT_CHUNK_OVERLAP)
    separators = rules.get("separators") or list(DEFAULT_SEPARATORS)

    if not text or not text.strip():
        return []

    if mode == SplitMode.HEADING.value:
        parts = _split_by_heading(text)
    elif mode == SplitMode.PARAGRAPH.value:
        parts = _split_by_paragraph(text)
    elif mode == SplitMode.SLIDING.value:
        parts = _split_sliding(text, chunk_size, overlap)
    else:
        parts = _split_fixed(text, chunk_size, overlap, separators)

    refined: list[str] = []
    for part in parts:
        if len(part) <= chunk_size:
            if part.strip():
                refined.append(part.strip())
        else:
            refined.extend(_split_fixed(part, chunk_size, overlap, separators))

    return [
        ChunkPreview(chunk_index=i, content=c, char_count=len(c), metadata={"split_mode": mode})
        for i, c in enumerate(refined)
        if c.strip()
    ]


def _split_by_heading(text: str) -> list[str]:
    pattern = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)
    parts = [p.strip() for p in pattern.split(text) if p and p.strip()]
    return parts or [text]


def _split_by_paragraph(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sliding(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        return [text]
    step = max(chunk_size - max(overlap, 0), 1)
    parts: list[str] = []
    i = 0
    while i < len(text):
        parts.append(text[i : i + chunk_size])
        if i + chunk_size >= len(text):
            break
        i += step
    return parts


def _split_fixed(text: str, chunk_size: int, overlap: int, separators: list[str]) -> list[str]:
    units = _recursive_split(text, separators)
    chunks: list[str] = []
    buf = ""
    for unit in units:
        if not unit:
            continue
        if len(buf) + len(unit) <= chunk_size:
            buf += unit
            continue
        if buf.strip():
            chunks.append(buf.strip())
        if len(unit) > chunk_size:
            start = 0
            while start < len(unit):
                end = start + chunk_size
                chunks.append(unit[start:end].strip())
                start = max(end - overlap, start + 1) if overlap else end
            buf = ""
        else:
            if overlap and chunks:
                tail = chunks[-1][-overlap:]
                buf = tail + unit
            else:
                buf = unit
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def _recursive_split(text: str, separators: list[str]) -> list[str]:
    if not separators:
        return [text]
    sep = separators[0]
    rest = separators[1:]
    if sep not in text:
        return _recursive_split(text, rest) if rest else [text]
    pieces = text.split(sep)
    result: list[str] = []
    for i, piece in enumerate(pieces):
        piece_with_sep = piece + (sep if i < len(pieces) - 1 else "")
        if rest:
            result.extend(_recursive_split(piece_with_sep, rest))
        else:
            result.append(piece_with_sep)
    return result

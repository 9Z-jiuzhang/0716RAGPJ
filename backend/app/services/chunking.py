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


def adapt_rules_for_file_type(rules: dict[str, Any] | None, file_type: str | None) -> dict[str, Any]:
    """按文件类型补充默认规则，当前对 Markdown 自动启用结构化切分。

    历史版本把所有文档默认存为 ``fixed``。为了让旧 Markdown 文档在再次预览或
    重分段时也能获益，``md`` 遇到默认 fixed 会升级为 markdown；其他显式模式保持不变。
    """
    adapted = merge_rules(None, rules)
    normalized_type = (file_type or "").strip().lower().lstrip(".")
    if normalized_type in {"md", "markdown"} and adapted.get("split_mode") == SplitMode.FIXED.value:
        adapted["split_mode"] = SplitMode.MARKDOWN.value
    return adapted


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

    if mode == SplitMode.MARKDOWN.value:
        return _split_markdown(text, chunk_size=chunk_size, overlap=overlap, separators=separators)
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


def _split_markdown(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    separators: list[str],
) -> list[ChunkPreview]:
    """按 Markdown 标题树和块级结构切分，并保留章节元数据。

    围栏代码块被视为原子块，即使略超目标长度也不从中间截断，避免生成缺少起止
    围栏的无效 Markdown。普通超长段落仍复用固定长度递归切分。
    """
    output: list[ChunkPreview] = []
    for section_text, section_meta in _markdown_sections(text):
        parts = _pack_markdown_blocks(
            section_text,
            chunk_size=max(1, chunk_size),
            overlap=max(0, overlap),
            separators=separators,
        )
        for part in parts:
            content = part.strip()
            if not content:
                continue
            output.append(
                ChunkPreview(
                    chunk_index=len(output),
                    content=content,
                    char_count=len(content),
                    metadata={"split_mode": SplitMode.MARKDOWN.value, **section_meta},
                )
            )
    return output


def _markdown_sections(text: str) -> list[tuple[str, dict[str, Any]]]:
    """识别代码围栏外的 ATX 标题，生成章节正文和完整标题路径。"""
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
    fence_pattern = re.compile(r"^\s*(```+|~~~+)")
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_meta: dict[str, Any] = {"heading_path": [], "heading_level": 0}
    sections: list[tuple[str, dict[str, Any]]] = []
    active_fence: str | None = None

    def flush() -> None:
        section = "\n".join(current_lines).strip()
        if section:
            sections.append((section, dict(current_meta)))
        current_lines.clear()

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        fence_match = fence_pattern.match(line)
        heading_match = heading_pattern.match(line) if active_fence is None else None
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            # 截断同级及更深标题，再写入当前标题，形成稳定的面包屑路径。
            heading_stack[level - 1 :] = [title]
            current_meta = {
                "heading_path": list(heading_stack),
                "heading_level": level,
                "heading": title,
            }
        current_lines.append(line)

        if fence_match:
            marker = fence_match.group(1)[0]
            if active_fence is None:
                active_fence = marker
            elif active_fence == marker:
                active_fence = None
    flush()
    return sections or [(text, {"heading_path": [], "heading_level": 0})]


def _pack_markdown_blocks(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    separators: list[str],
) -> list[str]:
    """把段落与完整代码围栏装入目标长度的 Markdown 分段。"""
    block_pattern = re.compile(
        r"(```[\s\S]*?```|~~~[\s\S]*?~~~|.+?)(?=\n\s*\n|\Z)",
        re.MULTILINE,
    )
    blocks = [match.group(0).strip() for match in block_pattern.finditer(text) if match.group(0).strip()]
    if not blocks:
        blocks = [text]

    chunks: list[str] = []
    buffer = ""
    for block in blocks:
        candidate = f"{buffer}\n\n{block}".strip() if buffer else block
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
            buffer = ""

        is_fenced = block.lstrip().startswith(("```", "~~~"))
        if is_fenced:
            chunks.append(block)
        elif len(block) > chunk_size:
            chunks.extend(_split_fixed(block, chunk_size, overlap, separators))
        else:
            buffer = block
    if buffer:
        chunks.append(buffer)
    return chunks


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

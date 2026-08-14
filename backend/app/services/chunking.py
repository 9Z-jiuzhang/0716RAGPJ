"""分段规则引擎。【对齐手册 §5.5.5】"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.models.enums import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_SEPARATORS,
    DEFAULT_SPLIT_MODE,
    SplitMode,
)

logger = logging.getLogger(__name__)

# 分段结果相对原文的最低字符覆盖率（忽略空白）。低于此值视为内容丢失。
MIN_CHUNK_COVERAGE_RATIO = 0.95


@dataclass
class ChunkPreview:
    chunk_index: int
    content: str
    char_count: int
    metadata: dict[str, Any]


class ChunkCoverageError(ValueError):
    """分段后正文覆盖率过低，疑似内容丢失。"""

    def __init__(self, ratio: float, source_chars: int, chunk_count: int) -> None:
        self.ratio = ratio
        self.source_chars = source_chars
        self.chunk_count = chunk_count
        super().__init__(
            f"分段覆盖率过低: {ratio:.2%}（原文非空白 {source_chars} 字，产出 {chunk_count} 段），疑似内容丢失"
        )


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
    rules["separators"] = _sanitize_separators(rules.get("separators"))
    return rules


def _sanitize_separators(separators: Any) -> list[str]:
    """去掉空分隔符，避免 str.split('') 抛错；无有效项时回退系统默认。"""
    if not isinstance(separators, (list, tuple)):
        return list(DEFAULT_SEPARATORS)
    cleaned = [str(s) for s in separators if s is not None and str(s) != ""]
    return cleaned or list(DEFAULT_SEPARATORS)


def _clamp_chunk_params(chunk_size: int, overlap: int) -> tuple[int, int]:
    size = max(1, int(chunk_size))
    ov = max(0, int(overlap))
    if ov >= size:
        ov = size - 1
    return size, ov


# 按扩展名推荐的默认分段模式（仅在规则仍为通用 fixed 时自动应用）。
_FILE_TYPE_DEFAULT_SPLIT_MODE: dict[str, str] = {
    "md": SplitMode.MARKDOWN.value,
    "markdown": SplitMode.MARKDOWN.value,
    "txt": SplitMode.PARAGRAPH.value,
    "pdf": SplitMode.PARAGRAPH.value,
    "doc": SplitMode.PARAGRAPH.value,
    "docx": SplitMode.PARAGRAPH.value,
    "pptx": SplitMode.PARAGRAPH.value,
    "ppt": SplitMode.PARAGRAPH.value,
}


def recommended_split_mode_for_file_type(file_type: str | None) -> str:
    """返回该文件类型最合适的默认分段模式；未知类型回退 fixed。"""
    normalized = (file_type or "").strip().lower().lstrip(".")
    return _FILE_TYPE_DEFAULT_SPLIT_MODE.get(normalized, SplitMode.FIXED.value)


def default_rules_for_file_type(file_type: str | None) -> dict[str, Any]:
    """上传时的文档默认规则：尺寸等用系统默认，``split_mode`` 强制按扩展名推荐。"""
    rules = default_rules()
    rules["split_mode"] = recommended_split_mode_for_file_type(file_type)
    return rules


def adapt_rules_for_file_type(rules: dict[str, Any] | None, file_type: str | None) -> dict[str, Any]:
    """补全规则，并在仍为通用 ``fixed`` 时按文件类型升级默认模式。

    - 上传请用 ``default_rules_for_file_type``（始终按扩展名设模式）；
    - 本函数用于预览/重分段：仅当 ``split_mode`` 仍是 ``fixed`` 时升级；
    - 用户显式选择的 heading / paragraph / markdown / sliding 等保持不变。
    """
    adapted = merge_rules(None, rules)
    current = str(adapted.get("split_mode") or SplitMode.FIXED.value).strip().lower()
    if current == SplitMode.FIXED.value:
        adapted["split_mode"] = recommended_split_mode_for_file_type(file_type)
    return adapted


def content_coverage_ratio(source: str, chunks: Sequence[str]) -> float:
    """估算分段对原文的覆盖率（忽略空白，按字符多重集合取交集）。

    overlap 会使分段合计变长，但不降低覆盖率；静默丢段会显著拉低该值。
    """
    src = re.sub(r"\s+", "", source or "")
    if not src:
        return 1.0
    joined = re.sub(r"\s+", "", "".join(chunks or []))
    src_counts = Counter(src)
    chunk_counts = Counter(joined)
    covered = sum(min(cnt, chunk_counts.get(ch, 0)) for ch, cnt in src_counts.items())
    return covered / len(src)


def ensure_chunk_coverage(
    source: str,
    chunks: Sequence[ChunkPreview] | Sequence[str],
    *,
    min_ratio: float = MIN_CHUNK_COVERAGE_RATIO,
) -> float:
    """覆盖率低于阈值时抛出 ``ChunkCoverageError``。"""
    contents = [c.content if isinstance(c, ChunkPreview) else str(c) for c in chunks]
    ratio = content_coverage_ratio(source, contents)
    src_chars = len(re.sub(r"\s+", "", source or ""))
    if src_chars and ratio < min_ratio:
        raise ChunkCoverageError(ratio=ratio, source_chars=src_chars, chunk_count=len(contents))
    return ratio


def split_text(text: str, rules: dict[str, Any] | None = None) -> list[ChunkPreview]:
    """按 split_mode 分段。若 enable_semantic=True 也忽略，仍走规则切分。

    结束后做正文覆盖率校验；若主策略丢失内容，自动回退到 sliding 保底，
    仍不足则抛出 ``ChunkCoverageError``，避免文档以 ready 入库却缺段。
    """
    rules = merge_rules(None, rules)
    # P2迭代开发，当前仅配置存储，不启用语义切分
    _ = rules.get("enable_semantic", False)
    mode = (rules.get("split_mode") or SplitMode.FIXED.value).lower()
    chunk_size, overlap = _clamp_chunk_params(
        int(rules.get("chunk_size") or DEFAULT_CHUNK_SIZE),
        int(rules.get("chunk_overlap") or DEFAULT_CHUNK_OVERLAP),
    )
    separators = _sanitize_separators(rules.get("separators"))

    if not text or not text.strip():
        return []

    chunks = _split_text_with_mode(
        text,
        mode=mode,
        chunk_size=chunk_size,
        overlap=overlap,
        separators=separators,
    )
    try:
        ensure_chunk_coverage(text, chunks)
        return chunks
    except ChunkCoverageError as exc:
        logger.warning(
            "split_mode=%s coverage=%.2f%% below threshold; fallback to sliding",
            mode,
            exc.ratio * 100,
        )
        fallback = _split_text_with_mode(
            text,
            mode=SplitMode.SLIDING.value,
            chunk_size=chunk_size,
            overlap=overlap,
            separators=separators,
        )
        for item in fallback:
            item.metadata = {
                **item.metadata,
                "split_mode": SplitMode.SLIDING.value,
                "fallback_from": mode,
            }
        ensure_chunk_coverage(text, fallback)
        return fallback


def _split_text_with_mode(
    text: str,
    *,
    mode: str,
    chunk_size: int,
    overlap: int,
    separators: list[str],
) -> list[ChunkPreview]:
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


_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _markdown_sections(text: str) -> list[tuple[str, dict[str, Any]]]:
    """识别代码围栏外的 ATX 标题，生成章节正文和完整标题路径。"""
    fence_pattern = re.compile(r"^\s*(```+|~~~+)")
    # (level, title)：按实际标题层级维护，支持从 ### 起稿、同级替换而非错误嵌套
    heading_stack: list[tuple[int, str]] = []
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
        heading_match = _HEADING_LINE.match(line) if active_fence is None else None
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_stack = [(lv, t) for lv, t in heading_stack if lv < level]
            heading_stack.append((level, title))
            current_meta = {
                "heading_path": [t for _, t in heading_stack],
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
    raw_sections = sections or [(text, {"heading_path": [], "heading_level": 0})]
    return _coalesce_heading_only_sections(raw_sections)


def _is_heading_only_section(section_text: str) -> bool:
    """章节是否仅含一行 ATX 标题（无正文），此类短段应并入下一节避免空洞分段。"""
    lines = [ln for ln in section_text.split("\n") if ln.strip()]
    return len(lines) == 1 and bool(_HEADING_LINE.match(lines[0]))


def _coalesce_heading_only_sections(
    sections: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """将「仅标题」章节合并进后续章节，保留标题文本、采用后续章节元数据。"""
    if len(sections) <= 1:
        return sections
    merged: list[tuple[str, dict[str, Any]]] = []
    pending_prefixes: list[str] = []
    for text, meta in sections:
        if _is_heading_only_section(text):
            pending_prefixes.append(text.strip())
            continue
        if pending_prefixes:
            text = "\n\n".join([*pending_prefixes, text])
            pending_prefixes.clear()
        merged.append((text, meta))
    if pending_prefixes:
        # 文末只剩标题：并入最后一节，或单独保留
        if merged:
            last_text, last_meta = merged[-1]
            merged[-1] = ("\n\n".join([last_text, *pending_prefixes]), last_meta)
        else:
            merged.append(("\n\n".join(pending_prefixes), sections[-1][1]))
    return merged or sections


def _split_markdown_blocks(text: str) -> list[str]:
    """按空行切成段落块，围栏代码保持完整；单换行连接的列表行合并为同一块，绝不跳过正文。

    旧实现用 ``.+?(?=\\n\\s*\\n|\\Z)`` + ``finditer``：``.`` 不能跨行，导致「仅单换行、中间无空行」
    的大段列表无法匹配而被静默丢弃（表现为条款编号跳跃、总字数远小于原文）。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    fence_pattern = re.compile(r"^\s*(```+|~~~+)")
    blocks: list[str] = []
    buf: list[str] = []
    active_fence: str | None = None

    def flush_buf() -> None:
        block = "\n".join(buf).strip()
        if block:
            blocks.append(block)
        buf.clear()

    for line in normalized.split("\n"):
        fence_match = fence_pattern.match(line)
        if active_fence is not None:
            buf.append(line)
            if fence_match and fence_match.group(1)[0] == active_fence:
                active_fence = None
                flush_buf()
            continue
        if fence_match:
            flush_buf()
            active_fence = fence_match.group(1)[0]
            buf.append(line)
            continue
        if not line.strip():
            flush_buf()
            continue
        buf.append(line)
    flush_buf()
    return blocks or ([normalized.strip()] if normalized.strip() else [])


def _pack_markdown_blocks(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    separators: list[str],
) -> list[str]:
    """把段落与完整代码围栏装入目标长度的 Markdown 分段。"""
    blocks = _split_markdown_blocks(text)
    if not blocks:
        return []

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
            # 超长围栏保持原子性，避免截断后缺少闭合标记
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
    return [p.strip() for p in parts if p.strip()] or ([text.strip()] if text.strip() else [])


def _split_sliding(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        return [text]
    chunk_size, overlap = _clamp_chunk_params(chunk_size, overlap)
    step = max(chunk_size - overlap, 1)
    parts: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        parts.append(text[i : i + chunk_size])
        if i + chunk_size >= length:
            break
        i += step
    return parts


def _split_fixed(text: str, chunk_size: int, overlap: int, separators: list[str]) -> list[str]:
    chunk_size, overlap = _clamp_chunk_params(chunk_size, overlap)
    separators = _sanitize_separators(separators)
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
                piece = unit[start:end]
                if piece.strip():
                    chunks.append(piece.strip())
                if end >= len(unit):
                    break
                start = max(end - overlap, start + 1)
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
    if not sep or sep not in text:
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

"""将外部表行转为 Markdown，供现有文档流水线消费。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _format_value(value: Any, *, max_field_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        text = value.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(value, date):
        text = value.strftime("%Y-%m-%d")
    elif isinstance(value, Decimal):
        text = format(value, "f")
    elif isinstance(value, (bytes, bytearray, memoryview)):
        return "[binary omitted]"
    else:
        text = str(value)
    if max_field_chars > 0 and len(text) > max_field_chars:
        return text[:max_field_chars] + "…"
    return text


def rows_to_markdown(
    rows: list[dict[str, Any]],
    *,
    columns: list[str],
    start_index: int = 1,
    title: str | None = None,
    max_field_chars: int = 2000,
) -> str:
    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
        parts.append("")
    for idx, row in enumerate(rows, start=start_index):
        parts.append(f"## 记录 {idx}")
        parts.append("")
        for col in columns:
            val = _format_value(row.get(col), max_field_chars=max_field_chars)
            parts.append(f"- {col}：{val}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def split_markdown_batches(
    rows: list[dict[str, Any]],
    *,
    columns: list[str],
    base_title: str,
    max_bytes: int,
    max_field_chars: int = 2000,
) -> list[tuple[str, str]]:
    """按字节上限拆分多个 Markdown 文档，返回 [(filename, content), ...]。"""
    batches: list[tuple[str, str]] = []
    current: list[dict[str, Any]] = []
    start = 1
    batch_index = 1

    def flush() -> None:
        nonlocal current, start, batch_index
        if not current:
            return
        title = f"{base_title}（批次 {batch_index}）"
        content = rows_to_markdown(
            current,
            columns=columns,
            start_index=start,
            title=title,
            max_field_chars=max_field_chars,
        )
        filename = f"{base_title}_batch{batch_index:03d}.md"
        batches.append((filename, content))
        start += len(current)
        batch_index += 1
        current = []

    for row in rows:
        tentative = current + [row]
        content = rows_to_markdown(
            tentative,
            columns=columns,
            start_index=start,
            title=f"{base_title}（批次 {batch_index}）",
            max_field_chars=max_field_chars,
        )
        if current and len(content.encode("utf-8")) > max_bytes:
            flush()
            current = [row]
        else:
            current = tentative
    flush()
    return batches

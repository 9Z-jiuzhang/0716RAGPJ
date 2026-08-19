"""版面块模型与序列化：Text / Table / Image。【多模态 RAG 入库】"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.enums import ContentBlockType

# 稳定标记：normalize 不会拆坏；chunking 可识别为原子块
BLOCK_OPEN = "<<<KB_BLOCK"
BLOCK_CLOSE = "<<<END_KB_BLOCK>>>"
_BLOCK_RE = re.compile(
    rf"{re.escape(BLOCK_OPEN)}\s+([^\n>>]*)>>>\n(.*?)\n{re.escape(BLOCK_CLOSE)}",
    re.DOTALL,
)


@dataclass
class ContentBlock:
    """版面分析产出的内容块。"""

    block_type: str
    content: str
    block_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    html: str = ""
    markdown: str = ""
    asset_path: str = ""
    mime_type: str = ""
    caption: str = ""
    page: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def table_rows_to_markdown(headers: list[str], rows: list[list[str]]) -> str:
    """二维表 → Markdown 表格。"""
    headers = [str(h or "").strip() or " " for h in headers]
    if not headers and rows:
        width = max(len(r) for r in rows)
        headers = [f"列{i+1}" for i in range(width)]
    if not headers:
        return ""
    width = len(headers)

    def _pad(row: list[str]) -> list[str]:
        cells = [str(c or "").replace("\n", " ").strip() for c in row]
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        return cells[:width]

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_pad(row)) + " |")
    return "\n".join(lines)


def table_rows_to_html(headers: list[str], rows: list[list[str]]) -> str:
    """二维表 → HTML table（检索回填用）。"""
    headers = [str(h or "").strip() or " " for h in headers]
    if not headers and rows:
        width = max(len(r) for r in rows)
        headers = [f"列{i+1}" for i in range(width)]
    if not headers:
        return ""
    width = len(headers)
    parts = ["<table>", "<thead><tr>"]
    for h in headers:
        parts.append(f"<th>{_escape_html(h)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in rows:
        cells = [str(c or "").replace("\n", " ").strip() for c in row]
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        parts.append("<tr>")
        for c in cells[:width]:
            parts.append(f"<td>{_escape_html(c)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def html_table_to_markdown(table_html: str) -> str:
    """简单 HTML <table> → Markdown。"""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return re.sub(r"<[^>]+>", " ", table_html).strip()

    try:
        soup = BeautifulSoup(table_html, "html.parser")
        table = soup.find("table")
        if not table:
            return table_html.strip()
        rows_el = table.find_all("tr")
        matrix: list[list[str]] = []
        for tr in rows_el:
            cells = tr.find_all(["th", "td"])
            matrix.append([c.get_text(" ", strip=True) for c in cells])
        if not matrix:
            return ""
        headers = matrix[0]
        body = matrix[1:] if len(matrix) > 1 else []
        thead = table.find("thead")
        if thead:
            hdr = [c.get_text(" ", strip=True) for c in thead.find_all(["th", "td"])]
            body_rows = []
            tbody = table.find("tbody") or table
            for tr in tbody.find_all("tr"):
                if tr.find_parent("thead"):
                    continue
                body_rows.append([c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])])
            return table_rows_to_markdown(hdr or headers, body_rows or body)
        return table_rows_to_markdown(headers, body)
    except Exception:
        return re.sub(r"<[^>]+>", " ", table_html).strip()


def serialize_blocks(blocks: list[ContentBlock]) -> str:
    """将块序列化为带标记的正文，供 normalize / chunking 使用。"""
    parts: list[str] = []
    for b in blocks:
        attrs = {
            "type": b.block_type,
            "id": b.block_id,
        }
        if b.asset_path:
            attrs["asset"] = b.asset_path
        if b.mime_type:
            attrs["mime"] = b.mime_type
        if b.page is not None:
            attrs["page"] = b.page
        attr_str = " ".join(f'{k}="{_attr_escape(str(v))}"' for k, v in attrs.items())
        body = (b.content or "").strip()
        # 表结构附加隐藏 JSON 元数据行，便于分段后还原 html/md
        meta_payload: dict[str, Any] = {}
        if b.html:
            meta_payload["html"] = b.html
        if b.markdown:
            meta_payload["markdown"] = b.markdown
        if b.caption:
            meta_payload["caption"] = b.caption
        if b.extra:
            meta_payload["extra"] = b.extra
        if meta_payload:
            body = body + "\n<!--KB_META:" + json.dumps(meta_payload, ensure_ascii=False) + "-->"
        parts.append(f"{BLOCK_OPEN} {attr_str}>>>\n{body}\n{BLOCK_CLOSE}")
    return "\n\n".join(parts)


def _attr_escape(value: str) -> str:
    return value.replace('"', "&quot;")


def parse_serialized_blocks(text: str) -> list[dict[str, Any]]:
    """从序列化正文解析块；无标记时返回空列表（表示纯文本旧文档）。"""
    if not text or BLOCK_OPEN not in text:
        return []
    out: list[dict[str, Any]] = []
    for match in _BLOCK_RE.finditer(text):
        attr_raw = match.group(1)
        body = match.group(2)
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', attr_raw))
        meta: dict[str, Any] = {}
        meta_m = re.search(r"<!--KB_META:(.*?)-->", body, re.DOTALL)
        if meta_m:
            try:
                meta = json.loads(meta_m.group(1))
            except json.JSONDecodeError:
                meta = {}
            body = (body[: meta_m.start()] + body[meta_m.end() :]).strip()
        out.append(
            {
                "block_type": attrs.get("type") or ContentBlockType.TEXT.value,
                "block_id": attrs.get("id") or uuid.uuid4().hex[:12],
                "asset_path": attrs.get("asset") or "",
                "mime_type": attrs.get("mime") or "",
                "page": int(attrs["page"]) if attrs.get("page", "").isdigit() else None,
                "content": body.strip(),
                "html": meta.get("html") or "",
                "markdown": meta.get("markdown") or "",
                "caption": meta.get("caption") or "",
                "extra": meta.get("extra") or {},
            }
        )
    return out


def split_table_with_header(markdown: str, max_chars: int) -> list[str]:
    """超长 Markdown 表按行切分，每片保留表头。"""
    lines = [ln for ln in (markdown or "").splitlines() if ln.strip()]
    if len(lines) < 2 or max_chars <= 0 or len(markdown) <= max_chars:
        return [markdown.strip()] if markdown.strip() else []
    header = lines[0]
    sep = lines[1] if len(lines) > 1 and re.match(r"^\|?\s*:?-{3,}", lines[1]) else None
    data_lines = lines[2:] if sep else lines[1:]
    prefix = header + ("\n" + sep if sep else "")
    chunks: list[str] = []
    buf: list[str] = []
    for row in data_lines:
        trial = prefix + "\n" + "\n".join(buf + [row])
        if buf and len(trial) > max_chars:
            chunks.append(prefix + "\n" + "\n".join(buf))
            buf = [row]
        else:
            buf.append(row)
    if buf:
        chunks.append(prefix + "\n" + "\n".join(buf))
    return chunks


def evidence_content_from_metadata(content: str, metadata: dict[str, Any] | None) -> str:
    """检索命中后回填：优先完整表/图结构，否则用正文。"""
    meta = metadata or {}
    parent = (meta.get("parent_content") or "").strip()
    if parent:
        block_type = meta.get("block_type") or ""
        label = {"table": "表格原文", "image": "图片描述"}.get(block_type, "原文")
        html = (meta.get("structure_html") or "").strip()
        extra = f"\n[HTML]\n{html}" if html else ""
        asset = (meta.get("asset_path") or "").strip()
        asset_line = f"\n[资产] {asset}" if asset else ""
        summary = (meta.get("summary") or content or "").strip()
        return f"【{label}】\n{parent}{extra}{asset_line}\n【检索摘要】{summary}".strip()
    return (content or "").strip()

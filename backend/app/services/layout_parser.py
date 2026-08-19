"""版面解析：将文档拆为 Text / Table / Image 块（含 HTML）。"""

from __future__ import annotations

import io
import logging
import re
import uuid
from typing import Any

from app.models.enums import ContentBlockType, DocumentFileType
from app.services.layout_blocks import (
    ContentBlock,
    html_table_to_markdown,
    serialize_blocks,
    table_rows_to_html,
    table_rows_to_markdown,
)
from app.services.parsers import _decode_bytes, _extract_doc, extract_text
from app.utils.exceptions import UnsupportedFileTypeError

logger = logging.getLogger(__name__)


def extract_layout(
    filename: str,
    content: bytes,
    file_type: str,
    *,
    kb_id: str | None = None,
    store_asset=None,
) -> tuple[str, list[ContentBlock]]:
    """抽取版面块并返回 (序列化正文, blocks)。

    ``store_asset(filename, bytes, content_type) -> object_path`` 可选，用于图片入库。
    """
    ft = (file_type or "").lower().lstrip(".")
    try:
        if ft in {DocumentFileType.HTML.value, DocumentFileType.HTM.value}:
            blocks = _extract_html(content, store_asset=store_asset, kb_id=kb_id)
        elif ft in {
            DocumentFileType.XLSX.value,
            DocumentFileType.XLS.value,
            DocumentFileType.CSV.value,
        }:
            from app.services.spreadsheet_parser import extract_spreadsheet_blocks

            blocks = extract_spreadsheet_blocks(content, ft)
        elif ft == DocumentFileType.DOCX.value:
            blocks = _extract_docx_layout(content, store_asset=store_asset, kb_id=kb_id)
        elif ft == DocumentFileType.PDF.value:
            blocks = _extract_pdf_layout(content, store_asset=store_asset, kb_id=kb_id)
        elif ft == DocumentFileType.MD.value:
            blocks = _extract_markdown_layout(_decode_bytes(content))
        elif ft == DocumentFileType.TXT.value:
            blocks = _extract_plain_layout(_decode_bytes(content))
        elif ft == DocumentFileType.DOC.value:
            text = _extract_doc(content)
            blocks = _extract_plain_layout(text)
        else:
            # 未知类型回退纯文本
            text = extract_text(filename, content, ft)
            blocks = _extract_plain_layout(text)
    except UnsupportedFileTypeError:
        raise
    except Exception as exc:
        logger.exception("extract_layout failed filename=%s type=%s", filename, ft)
        raise UnsupportedFileTypeError(f"{ft}(版面解析失败: {exc})") from exc

    blocks = [b for b in blocks if (b.content or "").strip() or b.asset_path]
    if not blocks:
        return "", []
    return serialize_blocks(blocks), blocks


def _text_block(text: str, **extra: Any) -> ContentBlock | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    return ContentBlock(block_type=ContentBlockType.TEXT.value, content=cleaned, extra=dict(extra))


def _table_block(headers: list[str], rows: list[list[str]], **extra: Any) -> ContentBlock | None:
    md = table_rows_to_markdown(headers, rows)
    if not md.strip():
        return None
    html = table_rows_to_html(headers, rows)
    return ContentBlock(
        block_type=ContentBlockType.TABLE.value,
        content=md,
        markdown=md,
        html=html,
        extra=dict(extra),
    )


def _extract_plain_layout(text: str) -> list[ContentBlock]:
    """纯文本：识别 Markdown 管道表，其余按段落合并为 text 块。"""
    blocks: list[ContentBlock] = []
    lines = (text or "").splitlines()
    i = 0
    buf: list[str] = []
    while i < len(lines):
        table = _try_read_pipe_table(lines, i)
        if table:
            if buf:
                tb = _text_block("\n".join(buf))
                if tb:
                    blocks.append(tb)
                buf = []
            headers, rows, consumed = table
            tb = _table_block(headers, rows)
            if tb:
                blocks.append(tb)
            i += consumed
            continue
        buf.append(lines[i])
        i += 1
    if buf:
        tb = _text_block("\n".join(buf))
        if tb:
            blocks.append(tb)
    return blocks


def _extract_markdown_layout(text: str) -> list[ContentBlock]:
    return _extract_plain_layout(text)


def _try_read_pipe_table(lines: list[str], start: int) -> tuple[list[str], list[list[str]], int] | None:
    if start >= len(lines):
        return None
    header_line = lines[start].strip()
    if "|" not in header_line:
        return None
    if start + 1 >= len(lines):
        return None
    sep = lines[start + 1].strip()
    if not re.match(r"^\|?[\s:-]+\|[\s|:-]*$", sep):
        return None

    def _cells(line: str) -> list[str]:
        raw = line.strip().strip("|")
        return [c.strip() for c in raw.split("|")]

    headers = _cells(header_line)
    rows: list[list[str]] = []
    i = start + 2
    while i < len(lines) and "|" in lines[i]:
        rows.append(_cells(lines[i]))
        i += 1
    return headers, rows, i - start


def _extract_html(content: bytes, *, store_asset=None, kb_id: str | None = None) -> list[ContentBlock]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 未安装，使用标准库 HTMLParser 解析 HTML")
        return _extract_html_stdlib(content, store_asset=store_asset)

    html = _decode_bytes(content)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    blocks: list[ContentBlock] = []
    body = soup.body or soup

    # 先摘顶层表与图，再抽剩余文本
    for table in list(body.find_all("table")):
        if table.find_parent("table"):
            continue
        md = html_table_to_markdown(str(table))
        html_s = str(table)
        if md.strip():
            blocks.append(
                ContentBlock(
                    block_type=ContentBlockType.TABLE.value,
                    content=md,
                    markdown=md,
                    html=html_s,
                )
            )
        table.decompose()

    for img in list(body.find_all("img")):
        src = (img.get("src") or "").strip()
        alt = (img.get("alt") or "").strip()
        asset = ""
        mime = "image/png"
        if src.startswith("data:") and store_asset:
            asset, mime = _store_data_uri(src, store_asset)
        caption = alt or "HTML 内嵌图片"
        blocks.append(
            ContentBlock(
                block_type=ContentBlockType.IMAGE.value,
                content=caption,
                caption=caption,
                asset_path=asset,
                mime_type=mime,
                extra={"src": src[:200] if not src.startswith("data:") else "data-uri"},
            )
        )
        img.decompose()

    text = body.get_text("\n", strip=True)
    ordered: list[ContentBlock] = []
    tb = _text_block(text)
    if tb:
        ordered.append(tb)
    ordered.extend(blocks)
    if not ordered:
        fallback = _text_block(soup.get_text("\n", strip=True))
        if fallback:
            ordered.append(fallback)
    return ordered


def _extract_html_stdlib(content: bytes, *, store_asset=None) -> list[ContentBlock]:
    """无 bs4 时的 HTML 版面解析（标准库 html.parser）。"""
    from html.parser import HTMLParser

    class _LayoutHTMLParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.blocks: list[ContentBlock] = []
            self._text_parts: list[str] = []
            self._in_script = False
            self._in_table = 0
            self._table_html: list[str] = []
            self._row: list[str] = []
            self._cell: list[str] = []
            self._in_cell = False
            self._matrix: list[list[str]] = []
            self._capture_cell = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            t = tag.lower()
            if t in {"script", "style", "noscript"}:
                self._in_script = True
                return
            if t == "table":
                self._flush_text()
                self._in_table += 1
                if self._in_table == 1:
                    self._table_html = ["<table>"]
                    self._matrix = []
                return
            if self._in_table:
                if t in {"tr"}:
                    self._row = []
                elif t in {"td", "th"}:
                    self._cell = []
                    self._in_cell = True
                self._table_html.append(self.get_starttag_text() or f"<{t}>")
                return
            if t == "img":
                self._flush_text()
                ad = dict(attrs)
                src = (ad.get("src") or "").strip()
                alt = (ad.get("alt") or "").strip() or "HTML 内嵌图片"
                asset = ""
                mime = "image/png"
                if src.startswith("data:") and store_asset:
                    asset, mime = _store_data_uri(src, store_asset)
                self.blocks.append(
                    ContentBlock(
                        block_type=ContentBlockType.IMAGE.value,
                        content=alt,
                        caption=alt,
                        asset_path=asset,
                        mime_type=mime,
                    )
                )
                return
            if t in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "div"}:
                self._text_parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            t = tag.lower()
            if t in {"script", "style", "noscript"}:
                self._in_script = False
                return
            if self._in_table:
                self._table_html.append(f"</{t}>")
                if t in {"td", "th"} and self._in_cell:
                    self._row.append("".join(self._cell).strip())
                    self._in_cell = False
                    self._cell = []
                elif t == "tr":
                    if self._row:
                        self._matrix.append(self._row)
                    self._row = []
                elif t == "table":
                    self._in_table = max(0, self._in_table - 1)
                    if self._in_table == 0 and self._matrix:
                        headers = self._matrix[0]
                        rows = self._matrix[1:] if len(self._matrix) > 1 else []
                        tb = _table_block(headers, rows)
                        if tb:
                            # 覆盖 html 为原始片段
                            tb.html = "".join(self._table_html)
                            self.blocks.append(tb)
                        self._matrix = []
                        self._table_html = []
                return

        def handle_data(self, data: str) -> None:
            if self._in_script:
                return
            if self._in_table and self._in_cell:
                self._cell.append(data)
                return
            if not self._in_table:
                self._text_parts.append(data)

        def _flush_text(self) -> None:
            text = "".join(self._text_parts)
            text = re.sub(r"[ \t]+\n", "\n", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            self._text_parts = []
            tb = _text_block(text)
            if tb:
                self.blocks.append(tb)

        def close(self) -> None:
            self._flush_text()
            super().close()

    parser = _LayoutHTMLParser()
    parser.feed(_decode_bytes(content))
    parser.close()
    return parser.blocks


def _store_data_uri(src: str, store_asset) -> tuple[str, str]:
    import base64

    try:
        header, b64 = src.split(",", 1)
        mime = "image/png"
        m = re.match(r"data:([^;]+);base64", header)
        if m:
            mime = m.group(1)
        raw = base64.b64decode(b64)
        ext = mime.split("/")[-1] if "/" in mime else "bin"
        path = store_asset(f"embed_{uuid.uuid4().hex[:8]}.{ext}", raw, mime)
        return path, mime
    except Exception:
        logger.debug("data-uri image store failed", exc_info=True)
        return "", "image/png"


def _extract_docx_layout(content: bytes, *, store_asset=None, kb_id: str | None = None) -> list[ContentBlock]:
    from docx import Document as DocxDocument
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = DocxDocument(io.BytesIO(content))
    blocks: list[ContentBlock] = []

    def iter_block_items(parent):
        body = parent.element.body
        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield Table(child, parent)

    for item in iter_block_items(doc):
        if isinstance(item, Table):
            matrix: list[list[str]] = []
            for row in item.rows:
                matrix.append([cell.text.strip() for cell in row.cells])
            if not matrix:
                continue
            headers, rows = matrix[0], matrix[1:]
            tb = _table_block(headers, rows)
            if tb:
                blocks.append(tb)
        else:
            text = (item.text or "").strip()
            # 段内图片
            blips = item._element.findall(".//" + qn("a:blip"))
            if blips and store_asset:
                for blip in blips:
                    embed = blip.get(qn("r:embed"))
                    if not embed:
                        continue
                    try:
                        part = doc.part.related_parts[embed]
                        blob = part.blob
                        content_type = getattr(part, "content_type", "image/png") or "image/png"
                        ext = content_type.split("/")[-1] if "/" in content_type else "png"
                        path = store_asset(f"docx_{uuid.uuid4().hex[:8]}.{ext}", blob, content_type)
                        caption = text or "Word 文档内嵌图片"
                        blocks.append(
                            ContentBlock(
                                block_type=ContentBlockType.IMAGE.value,
                                content=caption,
                                caption=caption,
                                asset_path=path,
                                mime_type=content_type,
                            )
                        )
                    except Exception:
                        logger.debug("docx image extract failed", exc_info=True)
            if text and not blips:
                tb = _text_block(text)
                if tb:
                    blocks.append(tb)
            elif text and blips:
                # 图片已单独成块；旁注文字保留
                tb = _text_block(text)
                if tb:
                    blocks.append(tb)
    return blocks


def _extract_pdf_layout(content: bytes, *, store_asset=None, kb_id: str | None = None) -> list[ContentBlock]:
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(content))
    blocks: list[ContentBlock] = []
    page_texts: list[str] = []
    for page_idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            page_texts.append(text)
            # 页内管道表尝试
            page_blocks = _extract_plain_layout(text)
            for b in page_blocks:
                b.page = page_idx
                blocks.append(b)
        # 抽取嵌入图片
        if store_asset:
            try:
                resources = page.get("/Resources")
                if resources and "/XObject" in resources:
                    xobject = resources["/XObject"].get_object()
                    for obj_name in xobject:
                        obj = xobject[obj_name]
                        if obj.get("/Subtype") != "/Image":
                            continue
                        data = obj.get_data()
                        filt = str(obj.get("/Filter", ""))
                        if "DCT" in filt or "JPX" in filt or "Flate" in filt:
                            ext = "jpg" if "DCT" in filt else "png"
                            mime = "image/jpeg" if ext == "jpg" else "image/png"
                            path = store_asset(
                                f"pdf_p{page_idx}_{uuid.uuid4().hex[:8]}.{ext}",
                                data,
                                mime,
                            )
                            blocks.append(
                                ContentBlock(
                                    block_type=ContentBlockType.IMAGE.value,
                                    content=f"PDF 第 {page_idx} 页图片",
                                    caption=f"PDF 第 {page_idx} 页图片",
                                    asset_path=path,
                                    mime_type=mime,
                                    page=page_idx,
                                )
                            )
            except Exception:
                logger.debug("pdf image extract failed page=%s", page_idx, exc_info=True)

    # 若版面拆块为空，回退整页文本
    if not blocks and page_texts:
        tb = _text_block("\n\n".join(page_texts))
        if tb:
            blocks.append(tb)
    return blocks

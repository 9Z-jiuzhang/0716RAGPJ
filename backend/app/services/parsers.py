"""多格式文本抽取。【对齐手册 §5.5 P0 格式】"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from app.models.enums import DocumentFileType
from app.utils.exceptions import UnsupportedFileTypeError

logger = logging.getLogger(__name__)


def extract_text(filename: str, content: bytes, file_type: str) -> str:
    """从上传字节中抽取纯文本。"""
    ft = file_type.lower().lstrip(".")
    if ft == DocumentFileType.TXT.value or ft == DocumentFileType.MD.value:
        return _decode_bytes(content)
    if ft == DocumentFileType.PDF.value:
        return _extract_pdf(content)
    if ft == DocumentFileType.DOCX.value:
        return _extract_docx(content)
    if ft == DocumentFileType.DOC.value:
        return _extract_doc(content)
    raise UnsupportedFileTypeError(ft)


def _decode_bytes(content: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_pdf(content: bytes) -> str:
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def _extract_docx(content: bytes) -> str:
    from docx import Document as DocxDocument

    doc = DocxDocument(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text and p.text.strip())


def _extract_doc(content: bytes) -> str:
    """旧版 .doc：尽力抽取；失败则明确报错。【P1 可增强】"""
    # 尝试按 zip/docx 误标场景
    try:
        return _extract_docx(content)
    except Exception:
        logger.warning("doc as docx failed, fallback decode")
    text = _decode_bytes(content)
    # 过滤大量不可打印字符
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in text)
    cleaned = "\n".join(line for line in cleaned.splitlines() if line.strip())
    if len(cleaned.strip()) < 16:
        raise UnsupportedFileTypeError("doc(无法解析，请转换为 docx)")
    return cleaned


def detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext

"""多格式文本抽取。【对齐手册 §5.5 P0 格式】"""

from __future__ import annotations

import io
import logging
import re
import zlib
from pathlib import Path

from app.models.enums import DocumentFileType
from app.utils.exceptions import UnsupportedFileTypeError

logger = logging.getLogger(__name__)


def extract_text(filename: str, content: bytes, file_type: str) -> str:
    """从上传字节中抽取纯文本；失败时抛出明确错误，避免返回乱码。"""
    ft = file_type.lower().lstrip(".")
    try:
        if ft == DocumentFileType.TXT.value or ft == DocumentFileType.MD.value:
            return _decode_bytes(content)
        if ft == DocumentFileType.PDF.value:
            return _extract_pdf(content)
        if ft == DocumentFileType.DOCX.value:
            return _extract_docx(content)
        if ft == DocumentFileType.DOC.value:
            return _extract_doc(content)
    except UnsupportedFileTypeError:
        raise
    except Exception as exc:
        logger.exception("extract_text failed filename=%s type=%s", filename, ft)
        raise UnsupportedFileTypeError(f"{ft}(解析失败: {exc})") from exc
    raise UnsupportedFileTypeError(ft)


def _decode_bytes(content: bytes) -> str:
    """统一字节解码：优先 chardet，再回退常见中文编码。"""
    if not content:
        return ""
    detected = _detect_encoding(content)
    candidates: list[str] = []
    if detected:
        candidates.append(detected)
    candidates.extend(["utf-8", "utf-8-sig", "gb18030", "gbk", "gb2312", "big5", "latin-1"])
    seen: set[str] = set()
    for enc in candidates:
        key = enc.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            text = content.decode(enc)
            if _looks_garbled(text):
                continue
            return text
        except UnicodeDecodeError:
            continue
    # 最后兜底：不把大量替换符当作成功结果
    text = content.decode("utf-8", errors="replace")
    if _looks_garbled(text):
        raise UnsupportedFileTypeError("txt(编码无法识别，请另存为 UTF-8 或 GBK)")
    return text


def _detect_encoding(content: bytes) -> str | None:
    sample = content[:65536]
    try:
        import chardet

        result = chardet.detect(sample) or {}
        enc = result.get("encoding")
        conf = float(result.get("confidence") or 0)
        if enc and conf >= 0.5:
            return str(enc)
    except Exception:
        logger.debug("chardet unavailable or failed", exc_info=True)
    return None


def _looks_garbled(text: str) -> bool:
    if not text:
        return True
    # 替换符过多、或几乎无可打印中英文字符时视为失败
    replacement = text.count("\ufffd")
    if replacement > max(8, len(text) // 20):
        return True
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\t\r")
    return printable / max(len(text), 1) < 0.6


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
    """旧版 Word .doc（OLE）抽取。

    python-docx 仅支持 .docx；此处按顺序尝试：
    1) 误标为 doc 的 docx
    2) olefile 抽取 WordDocument 流 + 编码检测
    3) 原始字节流编码检测（严格校验，避免乱码冒充成功）
    """
    if content[:2] == b"PK":
        try:
            return _extract_docx(content)
        except Exception:
            logger.warning("doc marked as zip/docx but parse failed")

    ole_text = _extract_doc_via_ole(content)
    if ole_text and not _looks_garbled(ole_text) and len(ole_text.strip()) >= 16:
        return ole_text

    # 非 OLE 或 OLE 失败：禁止把二进制当 latin-1 直接当正文
    try:
        text = _decode_bytes(content)
    except UnsupportedFileTypeError as exc:
        raise UnsupportedFileTypeError("doc(无法解析，请转换为 docx 后上传)") from exc
    cleaned = _clean_extracted_text(text)
    if len(cleaned.strip()) < 16 or _looks_garbled(cleaned):
        raise UnsupportedFileTypeError("doc(无法解析，请转换为 docx 后上传)")
    return cleaned


def _extract_doc_via_ole(content: bytes) -> str | None:
    try:
        import olefile
    except ImportError:
        logger.warning("olefile not installed; skip OLE .doc parse")
        return None

    if not olefile.isOleFile(io.BytesIO(content)):
        return None

    try:
        with olefile.OleFileIO(io.BytesIO(content)) as ole:
            stream_names = (
                "WordDocument",
                "1Table",
                "0Table",
                "RawText",
            )
            blobs: list[bytes] = []
            for name in stream_names:
                if ole.exists(name):
                    try:
                        blobs.append(ole.openstream(name).read())
                    except Exception:
                        continue
            if not blobs:
                return None
            # WordDocument 流中常夹杂 UTF-16LE 文本
            pieces: list[str] = []
            for blob in blobs:
                pieces.append(_extract_utf16_pieces(blob))
                pieces.append(_decode_bytes(blob) if _mostly_text_bytes(blob) else "")
            merged = _clean_extracted_text("\n".join(p for p in pieces if p))
            return merged or None
    except Exception:
        logger.warning("olefile doc extract failed", exc_info=True)
        return None


def _mostly_text_bytes(data: bytes) -> bool:
    if not data:
        return False
    sample = data[:4096]
    # 可打印 ASCII / 常见换行占比
    good = sum(1 for b in sample if 32 <= b <= 126 or b in (9, 10, 13))
    return good / max(len(sample), 1) > 0.75


def _extract_utf16_pieces(data: bytes) -> str:
    """从 WordDocument 二进制中提取可读的 UTF-16LE 片段。"""
    # 连续可打印 UTF-16LE 字符
    pattern = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
    chunks: list[str] = []
    for match in pattern.finditer(data):
        try:
            chunks.append(match.group().decode("utf-16-le", errors="ignore"))
        except Exception:
            continue
    # 再尝试 zlib 压缩块（部分 .doc 使用）
    for i in range(len(data) - 2):
        if data[i] == 0x78 and data[i + 1] in (0x01, 0x9C, 0xDA):
            try:
                inflated = zlib.decompress(data[i : i + 65536])
                for match in pattern.finditer(inflated):
                    chunks.append(match.group().decode("utf-16-le", errors="ignore"))
            except Exception:
                continue
    return _clean_extracted_text("\n".join(chunks))


def _clean_extracted_text(text: str) -> str:
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t\r" else " " for ch in text)
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if line)


def detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext

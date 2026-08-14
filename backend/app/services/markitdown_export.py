"""用微软 MarkItDown / 页面栅格化将原文件导出为可打开的 Markdown。

- 修复：剔除 \\0 与控制字符，避免 Cursor/编辑器把 MD 当二进制
- PDF 图表：整页栅格化为 PNG，在 MD 中用相对链接打开，同时保留文字/图数据描述
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.models.enums import DocumentFileType
from app.services import parsers
from app.utils.exceptions import DocumentError, UnsupportedFileTypeError

logger = logging.getLogger(__name__)

_TEXT_TYPES = frozenset(
    {
        DocumentFileType.TXT.value,
        DocumentFileType.MD.value,
        DocumentFileType.HTML.value,
        DocumentFileType.HTM.value,
        DocumentFileType.CSV.value,
    }
)
_MARKITDOWN_TYPES = frozenset(
    {
        DocumentFileType.PDF.value,
        DocumentFileType.DOCX.value,
        DocumentFileType.DOC.value,
        DocumentFileType.PPTX.value,
        DocumentFileType.XLSX.value,
        DocumentFileType.XLS.value,
    }
)
_PAGE_RENDER_TYPES = frozenset({DocumentFileType.PDF.value})

_DEFAULT_CHART_PROMPT = (
    "你是文档图表与插图分析助手。请用中文详细描述这张页面截图中的图表与文字，要求："
    "1) 说明图表类型（柱状图/折线图/饼图/表格/架构图等）；"
    "2) 列出坐标轴、图例、关键数值与趋势，尽量整理成 Markdown 表格；"
    "3) 提炼图表结论；"
    "4) 保留图中可读标题与标注；"
    "5) 只输出可粘贴进 Markdown 的正文，不要代码块围栏。"
)

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class MarkdownExportResult:
    """导出结果：正文 + 可选图表资源（相对路径 → 字节）。"""

    text: str
    download_name: str
    assets: dict[str, bytes] = field(default_factory=dict)

    @property
    def has_assets(self) -> bool:
        return bool(self.assets)


def convert_document_to_markdown(*, filename: str, content: bytes, file_type: str) -> str:
    """兼容旧调用：仅返回 Markdown 正文。"""
    return export_document_bundle(filename=filename, content=content, file_type=file_type).text


def export_document_bundle(*, filename: str, content: bytes, file_type: str) -> MarkdownExportResult:
    """导出 Markdown；PDF 额外附带 charts/page-XX.png 资源。"""
    ft = (file_type or "").lower().lstrip(".")
    if not content:
        raise DocumentError("文件内容为空，无法导出 Markdown", http_status=422)

    stem = Path(filename or "document").stem or "document"
    md_name = f"{stem}.md"

    if ft in _TEXT_TYPES:
        # HTML / CSV：优先走版面拆块（保留表格结构），失败再纯文本
        if ft in {
            DocumentFileType.HTML.value,
            DocumentFileType.HTM.value,
            DocumentFileType.CSV.value,
        }:
            try:
                from app.services.layout_parser import extract_layout

                serialized, _ = extract_layout(filename, content, ft, store_asset=None)
                text = sanitize_markdown_text(serialized)
            except Exception:
                text = sanitize_markdown_text(parsers.extract_text(filename, content, ft))
        else:
            text = sanitize_markdown_text(parsers.extract_text(filename, content, ft))
        if not text:
            raise DocumentError("文本内容为空，无法导出 Markdown", http_status=422)
        return MarkdownExportResult(text=text, download_name=md_name)

    if ft in {DocumentFileType.XLSX.value, DocumentFileType.XLS.value}:
        try:
            from app.services.layout_parser import extract_layout

            serialized, _ = extract_layout(filename, content, ft, store_asset=None)
            text = sanitize_markdown_text(serialized)
        except Exception:
            text = sanitize_markdown_text(parsers.extract_text(filename, content, ft))
        if not text:
            raise DocumentError("表格内容为空，无法导出 Markdown", http_status=422)
        return MarkdownExportResult(text=text, download_name=md_name)

    if ft not in _MARKITDOWN_TYPES:
        raise UnsupportedFileTypeError(ft)

    if ft in _PAGE_RENDER_TYPES:
        return _export_pdf_with_chart_links(filename=filename, content=content, stem=stem)

    try:
        text = sanitize_markdown_text(_convert_with_markitdown(content, ft))
    except DocumentError:
        raise
    except Exception as exc:
        if ft == DocumentFileType.DOC.value:
            logger.warning("markitdown failed for doc, fallback=parsers filename=%s err=%s", filename, exc)
            text = sanitize_markdown_text(parsers.extract_text(filename, content, ft))
            if not text:
                raise DocumentError(f"Markdown 转换失败: {exc}", http_status=422) from exc
            return MarkdownExportResult(text=text, download_name=md_name)
        logger.exception("markitdown convert failed filename=%s type=%s", filename, ft)
        raise DocumentError(f"Markdown 转换失败: {exc}", http_status=422) from exc

    if not text:
        raise DocumentError("Markdown 转换结果为空", http_status=422)
    return MarkdownExportResult(text=text, download_name=md_name)


def markdown_download_filename(original_filename: str) -> str:
    stem = Path(original_filename or "document").stem or "document"
    return f"{stem}.md"


def markdown_zip_filename(original_filename: str) -> str:
    stem = Path(original_filename or "document").stem or "document"
    return f"{stem}_markdown.zip"


def build_markdown_zip(result: MarkdownExportResult) -> bytes:
    """打包 MD + charts/*.png 为 zip（相对链接可本地打开）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(result.download_name, result.text.encode("utf-8"))
        for rel_path, data in sorted(result.assets.items()):
            zf.writestr(rel_path.replace("\\", "/"), data)
    return buf.getvalue()


def sanitize_markdown_text(text: str) -> str:
    """去掉 NUL/控制字符，保证编辑器可当文本打开。"""
    if not text:
        return ""
    cleaned = _CONTROL_RE.sub("", text.replace("\x00", ""))
    # 统一换行
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    # 去掉 UTF-8 替换残留过多的孤立控制感字符
    cleaned = "".join(ch for ch in cleaned if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    lines = [ln.rstrip() for ln in cleaned.split("\n")]
    # 压缩过多空行
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank <= 2:
                out.append("")
            continue
        blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def _export_pdf_with_chart_links(*, filename: str, content: bytes, stem: str) -> MarkdownExportResult:
    """PDF：栅格化每页为 PNG（链接打开）+ 保留文字/LLM 图数据。"""
    pages = _rasterize_pdf_pages(content)
    if not pages:
        raise DocumentError("PDF 无有效页面，无法导出", http_status=422)

    page_texts = _extract_pdf_page_texts(content)
    assets: dict[str, bytes] = {}
    sections: list[str] = [
        f"# {stem}",
        "",
        "> 本导出包含图表页截图：点击下方链接或图片可打开 PNG；同时保留本页文字与图数据描述。",
        "",
        f"- 源文件：`{filename}`",
        f"- 页数：{len(pages)}",
        "",
    ]

    llm = _markitdown_llm_kwargs()
    client = llm.get("llm_client")
    model = llm.get("llm_model")
    prompt = llm.get("llm_prompt") or _DEFAULT_CHART_PROMPT

    for idx, png in enumerate(pages, start=1):
        rel = f"charts/page-{idx:02d}.png"
        assets[rel] = png
        raw_text = sanitize_markdown_text(page_texts[idx - 1] if idx - 1 < len(page_texts) else "")
        vision_text = ""
        if client is not None and model:
            try:
                vision_text = sanitize_markdown_text(
                    _llm_describe_png(png, client=client, model=str(model), prompt=str(prompt))
                )
            except Exception as exc:
                logger.warning("page %s vision describe failed: %s", idx, exc)
                vision_text = f"（本页图表 LLM 描述失败：{exc}）"

        sections.extend(
            [
                f"## 第 {idx} 页",
                "",
                f"- [打开本页图表（PNG）]({rel})",
                "",
                f"![第 {idx} 页图表]({rel})",
                "",
                "### 本页文字与图数据",
                "",
            ]
        )
        if vision_text:
            sections.extend(["#### 图表识别（多模态）", "", vision_text, ""])
        if raw_text and _text_looks_usable(raw_text):
            sections.extend(["#### 页面抽取文本", "", raw_text, ""])
        elif not vision_text:
            sections.extend(["（本页未能抽到可用文本；请通过上方链接查看图表截图。）", ""])
        sections.append("")

    text = sanitize_markdown_text("\n".join(sections))
    if not text or "\x00" in text:
        raise DocumentError("导出 Markdown 含非法字符，已中止", http_status=500)
    return MarkdownExportResult(text=text, download_name=f"{stem}.md", assets=assets)


def _text_looks_usable(text: str) -> bool:
    """过滤 CID 乱码：需有足够中文，或纯 ASCII 数字轴标签。"""
    if not text or len(text.strip()) < 8:
        return False
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk >= 8:
        return True
    ascii_keep = sum(1 for ch in text if ch.isascii() and (ch.isalnum() or ch in " \n\t.%-+/"))
    non_ascii = sum(1 for ch in text if (not ch.isascii()) and ch not in "\n\t")
    # 纯英文/数字刻度可用；夹杂错误解码的非 ASCII 则丢弃
    return non_ascii == 0 and ascii_keep >= 20


def _rasterize_pdf_pages(content: bytes, *, zoom: float = 2.0) -> list[bytes]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise DocumentError("缺少 PyMuPDF，无法将 PDF 图表栅格化为图片", http_status=500) from exc

    doc = fitz.open(stream=content, filetype="pdf")
    try:
        matrix = fitz.Matrix(zoom, zoom)
        pages: list[bytes] = []
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pages.append(pix.tobytes("png"))
        return pages
    finally:
        doc.close()


def _extract_pdf_page_texts(content: bytes) -> list[str]:
    try:
        import fitz
    except ImportError:
        return []
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        return [(page.get_text("text") or "").strip() for page in doc]
    finally:
        doc.close()


def _llm_describe_png(png: bytes, *, client, model: str, prompt: str) -> str:
    import base64

    data_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
    ]
    response = client.chat.completions.create(model=model, messages=messages)
    return (response.choices[0].message.content or "").strip()


def _convert_with_markitdown(content: bytes, file_type: str) -> str:
    from markitdown import MarkItDown

    ext = f".{file_type.lower().lstrip('.')}"
    kwargs = _markitdown_llm_kwargs()
    md = MarkItDown(enable_plugins=True, **kwargs)
    stream = io.BytesIO(content)
    stream_info = _build_stream_info(ext)
    if stream_info is not None:
        result = md.convert_stream(stream, stream_info=stream_info)
    else:
        result = md.convert_stream(stream, file_extension=ext)
    text = getattr(result, "text_content", None) or getattr(result, "markdown", None) or ""
    return sanitize_markdown_text(str(text))


def _markitdown_llm_kwargs() -> dict:
    if not settings.MARKITDOWN_LLM_ENABLED:
        logger.warning("MARKITDOWN_LLM_ENABLED=false：导出将跳过图表 LLM 描述")
        return {}

    api_key = (settings.MARKITDOWN_LLM_API_KEY or settings.LLM_API_KEY or "").strip()
    if not api_key or api_key in {"change-me", "<请填写>"}:
        raise DocumentError(
            "未配置可用的 LLM API Key，无法对 PDF/PPT 等文件中的图表做看图描述。"
            "请设置 MARKITDOWN_LLM_API_KEY 或 LLM_API_KEY。",
            http_status=503,
        )

    base_url = (
        settings.MARKITDOWN_LLM_BASE_URL or settings.LLM_BASE_URL or "https://api.openai.com/v1"
    ).strip().rstrip("/")
    model = (settings.MARKITDOWN_LLM_MODEL or "").strip() or "qwen-vl-plus"
    prompt = (settings.MARKITDOWN_LLM_PROMPT or "").strip() or _DEFAULT_CHART_PROMPT
    timeout = max(30, int(settings.MARKITDOWN_LLM_TIMEOUT_SECONDS or 180))

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    logger.info("markitdown LLM vision enabled model=%s base=%s", model, base_url)
    return {"llm_client": client, "llm_model": model, "llm_prompt": prompt}


def _build_stream_info(extension: str):
    try:
        from markitdown import StreamInfo

        return StreamInfo(extension=extension)
    except Exception:
        pass
    try:
        from markitdown._stream_info import StreamInfo

        return StreamInfo(extension=extension)
    except Exception:
        return None

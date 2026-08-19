"""文档模块单元测试（无外部依赖）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.models.enums import DocumentStatus
from app.services.chunking import merge_rules, split_text
from app.services.document_service import _validate_upload, delete_document, prepare_retry
from app.services.document_state import apply_status, assert_transition
from app.services.normalize import normalize_text
from app.utils.exceptions import (
    DocumentError,
    FileTooLargeError,
    InvalidTransitionError,
    UnsupportedFileTypeError,
)


class DummyDoc:
    def __init__(self, status: str):
        self.status = status
        self.error_message = None
        self.id = uuid4()
        self.kb_id = uuid4()
        self.filename = "a.txt"
        self.file_path = "kb/a.txt"
        self.creator_id = uuid4()


def test_normalize_compresses_blank_and_spaces():
    text = "标题\n\n\n\n内容   多余\n\n内容   多余\n"
    result, stats = normalize_text(text)
    assert "多余" in result
    assert stats.char_count_after <= stats.char_count_before
    assert stats.removed_blank_lines >= 1


def test_split_fixed_respects_chunk_size():
    text = "第一段。\n\n第二段。\n\n第三段内容比较长需要切开。" * 20
    chunks = split_text(text, {"chunk_size": 80, "chunk_overlap": 10, "split_mode": "fixed"})
    assert chunks
    assert all(c.char_count <= 100 for c in chunks)


def test_split_heading_and_paragraph():
    md = "# 标题一\n内容A\n## 标题二\n内容B\n\n段落二"
    heading_chunks = split_text(md, {"chunk_size": 500, "chunk_overlap": 0, "split_mode": "heading"})
    para_chunks = split_text(md, {"chunk_size": 500, "chunk_overlap": 0, "split_mode": "paragraph"})
    assert len(heading_chunks) >= 1
    assert len(para_chunks) >= 1


def test_split_sliding():
    text = "abcdefghij" * 10
    chunks = split_text(text, {"chunk_size": 20, "chunk_overlap": 5, "split_mode": "sliding"})
    assert len(chunks) >= 2


def test_enable_semantic_ignored_still_splits():
    """P2：enable_semantic 仅存储，不改变切分行为。"""
    rules = merge_rules(None, {"enable_semantic": True, "chunk_size": 50, "split_mode": "fixed"})
    assert rules["enable_semantic"] is True
    chunks = split_text("hello world " * 20, rules)
    assert chunks


def test_state_machine_happy_path():
    doc = DummyDoc(DocumentStatus.UPLOADED.value)
    for target in [
        DocumentStatus.PARSING.value,
        DocumentStatus.PROCESSING.value,
        DocumentStatus.PENDING_SEGMENT.value,
        DocumentStatus.VECTORIZING.value,
        DocumentStatus.READY.value,
    ]:
        apply_status(doc, target)
    assert doc.status == DocumentStatus.READY.value
    assert doc.error_message is None


def test_state_machine_rejects_illegal():
    with pytest.raises(InvalidTransitionError):
        assert_transition(DocumentStatus.UPLOADED.value, DocumentStatus.READY.value)


def test_state_machine_error_sets_message():
    doc = DummyDoc(DocumentStatus.PARSING.value)
    apply_status(doc, DocumentStatus.ERROR.value, "boom")
    assert doc.error_message == "boom"


def test_error_can_retry_to_parsing():
    assert_transition(DocumentStatus.ERROR.value, DocumentStatus.PARSING.value)
    doc = DummyDoc(DocumentStatus.ERROR.value)
    doc.error_message = "fail"
    apply_status(doc, DocumentStatus.PARSING.value)
    assert doc.status == DocumentStatus.PARSING.value
    assert doc.error_message is None


def test_upload_rejects_unknown_and_oversized(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(UnsupportedFileTypeError):
        _validate_upload("a.exe", b"abc")
    assert _validate_upload("demo.xlsx", b"PK") == "xlsx"
    assert _validate_upload("demo.csv", b"a,b\n1,2\n") == "csv"
    assert _validate_upload("deck.pptx", b"PK") == "pptx"
    with pytest.raises(FileTooLargeError):
        _validate_upload("a.txt", b"0123456789012345")
    assert _validate_upload("note.md", b"hello") == "md"
    assert _validate_upload("x.pdf", b"%PDF") == "pdf"


@pytest.mark.asyncio
async def test_delete_cascades_vector_and_storage():
    """删除需同步清理 DB + MinIO + Chroma。"""
    db = AsyncMock()
    user = MagicMock()
    user.id = uuid4()
    doc = DummyDoc(DocumentStatus.READY.value)

    with (
        patch("app.services.document_service.get_document_detail", AsyncMock(return_value=doc)),
        patch("app.services.document_service.take_auto_snapshot", AsyncMock()),
        patch("app.services.document_service.vector_store") as vs,
        patch("app.services.document_service.storage") as st,
        patch("app.services.document_service.write_audit", AsyncMock()),
        patch("app.services.document_service.record_metric"),
        # 删除文档会同步清理引用该文档的 FAQ；单元测试无需连接真实数据库。
        patch("app.services.kb_faq_service.kb_faq_service.prune_by_document", AsyncMock()),
    ):
        await delete_document(db, doc.kb_id, doc.id, user)
        vs.delete_document_vectors.assert_called_once_with(doc.kb_id, doc.id)
        db.delete.assert_awaited()
        st.delete_object.assert_called_once_with(doc.file_path)
        db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_prepare_retry_only_from_error():
    db = AsyncMock()
    user = MagicMock()
    user.id = uuid4()
    ready = DummyDoc(DocumentStatus.READY.value)
    with patch("app.services.document_service.get_document_detail", AsyncMock(return_value=ready)):
        with pytest.raises(DocumentError):
            await prepare_retry(db, ready.kb_id, ready.id, user)

    err = DummyDoc(DocumentStatus.ERROR.value)
    err.error_message = "x"
    with (
        patch("app.services.document_service.get_document_detail", AsyncMock(return_value=err)),
        patch("app.services.document_service.write_audit", AsyncMock()),
    ):
        doc = await prepare_retry(db, err.kb_id, err.id, user)
        assert doc.status == DocumentStatus.PARSING.value
        db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_segment_preview_file_returns_offsets_without_persistence():
    """按文件预览分段：返回每段起止下标，且不写库、不提交、不落向量。"""
    from app.services.document_service import preview_segment_source

    db = AsyncMock()
    text = "第一段内容。\n\n第二段内容更长一些用于验证切分效果。\n\n第三段结尾。"
    content = text.encode("utf-8")

    with patch("app.repositories.document.get_knowledge_base", AsyncMock(return_value=MagicMock())):
        resp = await preview_segment_source(
            db,
            uuid4(),
            filename="note.txt",
            content=content,
            rule_overrides={"chunk_size": 200, "chunk_overlap": 0, "split_mode": "paragraph"},
        )

    assert resp.document_id is None
    assert resp.file_type == "txt"
    assert resp.preview_source == "normalized_text"
    assert resp.total_chunks == len(resp.chunks) >= 1
    prev_start = -1
    for c in resp.chunks:
        assert 0 <= c.start <= c.end <= resp.total_chars
        assert c.char_count == len(c.content)
        assert c.start >= prev_start
        prev_start = c.start
    db.add.assert_not_called()
    db.commit.assert_not_called()
    db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_segment_preview_by_doc_id_uses_existing_text():
    """按已上传文档 id 预览：复用既有 normalized_text，不触发提交。"""
    from app.services.document_service import preview_segment_source

    db = AsyncMock()
    doc = DummyDoc(DocumentStatus.READY.value)
    doc.file_type = "txt"
    doc.raw_text = None
    doc.normalized_text = "标题段落。\n\n正文内容第一段。\n\n正文内容第二段收尾。"
    doc.segment_rules = {"chunk_size": 100, "chunk_overlap": 0, "split_mode": "paragraph"}

    with (
        patch("app.repositories.document.get_knowledge_base", AsyncMock(return_value=MagicMock())),
        patch("app.services.document_service.get_document_detail", AsyncMock(return_value=doc)),
    ):
        resp = await preview_segment_source(db, doc.kb_id, doc_id=doc.id)

    assert resp.document_id == str(doc.id)
    assert resp.preview_source == "normalized_text"
    assert resp.total_chunks >= 1
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_segment_preview_requires_file_or_doc_id():
    """file 与 doc_id 均缺失时报 DocumentError。"""
    from app.services.document_service import preview_segment_source

    db = AsyncMock()
    with patch("app.repositories.document.get_knowledge_base", AsyncMock(return_value=MagicMock())):
        with pytest.raises(DocumentError):
            await preview_segment_source(db, uuid4())


def test_convert_md_txt_direct_decode():
    from app.services.markitdown_export import convert_document_to_markdown, markdown_download_filename

    assert convert_document_to_markdown(filename="a.md", content=b"# Hello\n", file_type="md") == "# Hello"
    assert convert_document_to_markdown(filename="a.txt", content="中文".encode(), file_type="txt") == "中文"
    assert markdown_download_filename("报告.docx") == "报告.md"
    with pytest.raises(DocumentError):
        convert_document_to_markdown(filename="a.md", content=b"   \n", file_type="md")


def test_convert_docx_uses_markitdown():
    from app.services import markitdown_export as mod

    with patch.object(mod, "_convert_with_markitdown", return_value="# From MD") as conv:
        text = mod.convert_document_to_markdown(filename="x.docx", content=b"PK fake", file_type="docx")
    assert text == "# From MD"
    conv.assert_called_once()


def test_markitdown_llm_kwargs_requires_key(monkeypatch):
    from app.core import config
    from app.services import markitdown_export as mod

    monkeypatch.setattr(config.settings, "MARKITDOWN_LLM_ENABLED", True)
    monkeypatch.setattr(config.settings, "LLM_API_KEY", "")
    monkeypatch.setattr(config.settings, "MARKITDOWN_LLM_API_KEY", "")
    with pytest.raises(DocumentError):
        mod._markitdown_llm_kwargs()


def test_convert_doc_falls_back_to_parsers():
    from app.services import markitdown_export as mod

    with (
        patch.object(mod, "_convert_with_markitdown", side_effect=RuntimeError("no doc support")),
        patch.object(mod.parsers, "extract_text", return_value="plain body") as ext,
    ):
        text = mod.convert_document_to_markdown(filename="old.doc", content=b"ole", file_type="doc")
    assert text == "plain body"
    ext.assert_called_once()


@pytest.mark.asyncio
async def test_export_document_markdown_orchestration():
    from app.services.document_service import export_document_markdown
    from app.services.markitdown_export import MarkdownExportResult

    db = AsyncMock()
    doc = DummyDoc(DocumentStatus.READY.value)
    doc.filename = "竞品.docx"
    doc.file_type = "docx"
    doc.file_path = "kb/obj.docx"

    fake = MarkdownExportResult(text="# ok", download_name="竞品.md")
    with (
        patch("app.services.document_service.get_document_detail", AsyncMock(return_value=doc)),
        patch("app.services.document_service.storage.download_bytes", return_value=b"bytes"),
        patch(
            "app.services.markitdown_export.export_document_bundle",
            return_value=fake,
        ) as conv,
    ):
        result = await export_document_markdown(db, doc.kb_id, doc.id)
    assert result.text == "# ok"
    assert result.download_name == "竞品.md"
    conv.assert_called_once()


def test_sanitize_markdown_strips_nuls():
    from app.services.markitdown_export import sanitize_markdown_text

    dirty = "## Page 1\n\n\x00中文\x00\x03ok"
    clean = sanitize_markdown_text(dirty)
    assert "\x00" not in clean
    assert "ok" in clean

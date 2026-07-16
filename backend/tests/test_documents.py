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


def test_upload_rejects_p1_formats_and_oversized(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "MAX_UPLOAD_BYTES", 10)
    for name in ("a.csv", "b.xlsx", "c.pptx"):
        with pytest.raises(UnsupportedFileTypeError):
            _validate_upload(name, b"abc")
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

"""快照差异计算单测（绑定 utils.snapshot_diff，避免与 Service 漂移）。"""

from types import SimpleNamespace
from uuid import uuid4

from app.utils.snapshot_diff import compute_document_diff


def test_preview_detects_added_removed_modified():
    a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
    current = {
        a: SimpleNamespace(
            id=a, filename="a.pdf", chunk_count=3, content_hash="h1", status="ready", file_type="pdf"
        ),
        b: SimpleNamespace(
            id=b, filename="b.pdf", chunk_count=5, content_hash="h2", status="ready", file_type="pdf"
        ),
        d: SimpleNamespace(
            id=d, filename="d.pdf", chunk_count=2, content_hash="h4", status="ready", file_type="pdf"
        ),
    }
    snap = {
        a: SimpleNamespace(
            document_id=a,
            filename="a.pdf",
            chunk_count=3,
            content_hash="h1",
            file_type="pdf",
            doc_metadata={"status": "ready"},
        ),
        b: SimpleNamespace(
            document_id=b,
            filename="b.pdf",
            chunk_count=6,
            content_hash="h2x",
            file_type="pdf",
            doc_metadata={"status": "ready"},
        ),
        c: SimpleNamespace(
            document_id=c,
            filename="c.pdf",
            chunk_count=1,
            content_hash="h3",
            file_type="pdf",
            doc_metadata={"status": "ready"},
        ),
    }

    diffs = compute_document_diff(current, snap)
    by_type = {}
    for item in diffs:
        by_type.setdefault(item.change_type, []).append(item)

    assert len(by_type["unchanged"]) == 1
    assert len(by_type["modified"]) == 1
    assert len(by_type["added"]) == 1
    assert len(by_type["removed"]) == 1
    assert by_type["added"][0].filename == "c.pdf"
    assert by_type["removed"][0].filename == "d.pdf"

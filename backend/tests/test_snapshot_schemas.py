"""快照 / 审计模块单元测试（不依赖真实 PostgreSQL）。"""

import pytest
from pydantic import ValidationError

from app.schemas.snapshot import CreateSnapshotRequest, RollbackRequest
from app.models.enums import SnapshotTrigger


def test_create_snapshot_request_ok():
    body = CreateSnapshotRequest(name="发布前备份", description="手动")
    assert body.name == "发布前备份"


def test_rollback_requires_confirm_true():
    with pytest.raises(ValidationError):
        RollbackRequest(confirm=False)

    ok = RollbackRequest(confirm=True)
    assert ok.confirm is True
    assert ok.document_ids is None


def test_snapshot_trigger_enum_covers_handbook():
    """产品手册 5.8 触发方式应覆盖自动与保护场景。"""
    expected = {
        "auto_upload",
        "auto_delete",
        "auto_resegment",
        "auto_revectorize",
        "auto_permission",
        "manual",
        "rollback_protection",
    }
    actual = {t.value for t in SnapshotTrigger}
    assert expected.issubset(actual)


def test_rollback_selective_document_ids():
    from uuid import uuid4

    doc_id = uuid4()
    body = RollbackRequest(confirm=True, document_ids=[doc_id])
    assert body.document_ids == [doc_id]


def test_rollback_rejects_empty_document_ids():
    with pytest.raises(ValidationError):
        RollbackRequest(confirm=True, document_ids=[])


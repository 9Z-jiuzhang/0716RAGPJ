"""审计 Schema 测试。"""

from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.audit import AuditLogFilterParams, AuditLogResponse


def test_audit_filter_defaults():
    params = AuditLogFilterParams()
    assert params.page == 1
    assert params.page_size == 20


def test_audit_log_response_roundtrip():
    payload = {
        "id": uuid4(),
        "user_id": uuid4(),
        "action": "snapshot.rollback",
        "resource_type": "snapshot",
        "resource_id": str(uuid4()),
        "result": "success",
        "request_id": "req-1",
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "detail": {"new_index_version": "v20260716-001"},
    }
    model = AuditLogResponse(**payload)
    assert model.action == "snapshot.rollback"
    assert model.detail["new_index_version"] == "v20260716-001"

"""文档状态机。【对齐手册 §5.5.3】"""

from __future__ import annotations

from app.models.enums import DocumentStatus
from app.utils.exceptions import InvalidTransitionError

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    DocumentStatus.UPLOADED.value: {
        DocumentStatus.PARSING.value,
        DocumentStatus.ERROR.value,
    },
    DocumentStatus.PARSING.value: {
        DocumentStatus.PROCESSING.value,
        DocumentStatus.ERROR.value,
    },
    DocumentStatus.PROCESSING.value: {
        DocumentStatus.PENDING_SEGMENT.value,
        DocumentStatus.ERROR.value,
    },
    DocumentStatus.PENDING_SEGMENT.value: {
        DocumentStatus.VECTORIZING.value,
        DocumentStatus.ERROR.value,
        DocumentStatus.PROCESSING.value,  # 重新规范化后再分段
    },
    DocumentStatus.VECTORIZING.value: {
        DocumentStatus.READY.value,
        DocumentStatus.ERROR.value,
    },
    DocumentStatus.READY.value: {
        DocumentStatus.ARCHIVED.value,
        DocumentStatus.PENDING_SEGMENT.value,  # 重分段前回到预览
        DocumentStatus.VECTORIZING.value,
        DocumentStatus.ERROR.value,
    },
    DocumentStatus.ERROR.value: {
        DocumentStatus.PARSING.value,
        DocumentStatus.PROCESSING.value,
        DocumentStatus.PENDING_SEGMENT.value,
        DocumentStatus.VECTORIZING.value,
        DocumentStatus.ARCHIVED.value,
    },
    DocumentStatus.ARCHIVED.value: set(),
}


def assert_transition(current: str, target: str) -> None:
    """校验状态流转，非法则抛异常。"""
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(current, target)


def apply_status(document, target: str, error_message: str | None = None) -> None:
    """更新文档状态；进入 error 时写入失败原因，离开 error 时清空。"""
    assert_transition(document.status, target)
    document.status = target
    if target == DocumentStatus.ERROR.value:
        document.error_message = error_message or "未知错误"
    elif target != DocumentStatus.ERROR.value:
        document.error_message = None

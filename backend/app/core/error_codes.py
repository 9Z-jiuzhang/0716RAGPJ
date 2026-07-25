"""统一错误码（产品可展示文案与稳定 code）。"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    QA_MODEL_BUSY = "QA_MODEL_BUSY"
    QA_SESSION_FORBIDDEN = "QA_SESSION_FORBIDDEN"
    QA_SESSION_NOT_FOUND = "QA_SESSION_NOT_FOUND"
    QA_KB_FORBIDDEN = "QA_KB_FORBIDDEN"
    CACHE_PERMISSION_MISS = "CACHE_PERMISSION_MISS"
    VECTOR_PROVIDER_UNAVAILABLE = "VECTOR_PROVIDER_UNAVAILABLE"
    MODEL_REGISTRY_DISABLED = "MODEL_REGISTRY_DISABLED"
    SCHEDULER_NOT_LEADER = "SCHEDULER_NOT_LEADER"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.QA_MODEL_BUSY: "模型服务繁忙，请稍后重试",
    ErrorCode.QA_SESSION_FORBIDDEN: "无权访问该会话",
    ErrorCode.QA_SESSION_NOT_FOUND: "会话不存在或已删除",
    ErrorCode.QA_KB_FORBIDDEN: "指定的知识库不可检索",
    ErrorCode.CACHE_PERMISSION_MISS: "缓存权限校验未通过，已降级检索",
    ErrorCode.VECTOR_PROVIDER_UNAVAILABLE: "向量服务暂不可用",
    ErrorCode.MODEL_REGISTRY_DISABLED: "模型配置注册表未启用",
    ErrorCode.SCHEDULER_NOT_LEADER: "当前节点非调度主节点",
}

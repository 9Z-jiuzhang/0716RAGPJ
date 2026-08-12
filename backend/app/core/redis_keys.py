"""Redis Key 注册表：统一命名，禁止写入原始问题、密钥或邮箱明文。"""

from __future__ import annotations


def _part(value: str | None, fallback: str = "_") -> str:
    text = (value or fallback).strip() or fallback
    return text.replace(" ", "_")[:128]


def session_meta_key(*, tenant: str, conversation_id: str) -> str:
    return f"session:meta:v2:{_part(tenant)}:{_part(conversation_id)}"


def session_messages_key(*, tenant: str, conversation_id: str) -> str:
    return f"session:messages:v2:{_part(tenant)}:{_part(conversation_id)}"


def session_summary_key(*, tenant: str, conversation_id: str) -> str:
    return f"session:summary:v2:{_part(tenant)}:{_part(conversation_id)}"


def qa_exact_cache_key(*, tenant: str, scope_fingerprint: str, question_hash: str) -> str:
    return f"qa:exact:v2:{_part(tenant)}:{_part(scope_fingerprint)}:{_part(question_hash)}"


def qa_retrieval_cache_key(*, tenant: str, scope_fingerprint: str, query_hash: str) -> str:
    return f"qa:retrieval:v1:{_part(tenant)}:{_part(scope_fingerprint)}:{_part(query_hash)}"


def lock_role_cache_key(*, tenant: str, role_id: str, task_type: str) -> str:
    return f"lock:role-cache:v1:{_part(tenant)}:{_part(role_id)}:{_part(task_type)}"


def quota_model_key(*, provider: str, model_id: str) -> str:
    return f"quota:model:v1:{_part(provider)}:{_part(model_id)}"


def scheduler_leader_key(*, task_name: str) -> str:
    return f"lock:scheduler:v1:{_part(task_name)}"


def kb_faq_key(*, tenant: str, kb_id: str, question_hash: str) -> str:
    """知识库 FAQ 精确命中短时缓存。"""
    return f"kb:faq:v1:{_part(tenant)}:{_part(kb_id)}:{_part(question_hash)}"


def kb_faq_lock_key(*, tenant: str, kb_id: str) -> str:
    """知识库 FAQ 生成锁（同库同时仅一个任务）。"""
    return f"lock:kb-faq:v1:{_part(tenant)}:{_part(kb_id)}"


def kb_faq_queue_key(*, tenant: str) -> str:
    """FAQ 生成任务队列观察键。"""
    return f"queue:kb-faq:v1:{_part(tenant)}"

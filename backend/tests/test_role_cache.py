"""按角色缓存知识库的精确匹配、权限复核与文档结果解析测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.models.role_cache import RoleCachedQuestion
from app.services.role_cache import (
    CacheAnalysisResult,
    RoleCacheService,
    normalize_cache_question,
    run_role_cache_scheduler_once,
)


def _scalar_result(items: list[object]) -> MagicMock:
    """构造 SQLAlchemy scalars().all() 结果替身。"""
    result = MagicMock()
    result.all.return_value = items
    return result


def test_normalize_cache_question_only_ignores_formatting_differences() -> None:
    """空白、全半角和末尾标点应归一，但不同词序不会被误判为相同问题。"""
    assert normalize_cache_question(" 年假有几天？ ") == normalize_cache_question("年假有几天?")
    assert normalize_cache_question("年假有几天") != normalize_cache_question("几天年假")


@pytest.mark.asyncio
async def test_cache_lookup_rejects_cross_department_source_scope() -> None:
    """候选答案只要包含当前用户无权访问的来源知识库，就必须跳过。"""
    role_id = uuid4()
    allowed_kb_id = uuid4()
    forbidden_kb_id = uuid4()
    unauthorized = RoleCachedQuestion(
        id=uuid4(),
        cache_id=uuid4(),
        role_id=role_id,
        question="年假有几天？",
        normalized_question=normalize_cache_question("年假有几天？"),
        answer="无权访问的答案",
        source="document_generated",
        source_kb_ids=[allowed_kb_id, forbidden_kb_id],
        citations=[],
        occurrence_count=1,
        hit_count=0,
    )
    authorized = RoleCachedQuestion(
        id=uuid4(),
        cache_id=uuid4(),
        role_id=role_id,
        question="年假有几天？",
        normalized_question=normalize_cache_question("年假有几天？"),
        answer="已授权答案",
        source="history_frequent",
        source_kb_ids=[allowed_kb_id],
        citations=[],
        occurrence_count=3,
        hit_count=0,
    )
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_scalar_result([unauthorized, authorized]))
    user = SimpleNamespace(roles=[SimpleNamespace(id=role_id, is_enabled=True)])

    match = await RoleCacheService().lookup(
        db,
        question="年假有几天?",
        user=user,
        authorized_kb_ids=[allowed_kb_id],
    )

    assert match is not None
    assert match.answer == "已授权答案"
    assert unauthorized.hit_count == 0
    assert authorized.hit_count == 1
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_lookup_requires_nonempty_source_scope() -> None:
    """没有知识库来源范围的历史答案不能绕过正常 RAG 链路直接返回。"""
    role_id = uuid4()
    entry = RoleCachedQuestion(
        id=uuid4(),
        cache_id=uuid4(),
        role_id=role_id,
        question="测试问题",
        normalized_question="测试问题",
        answer="没有来源的答案",
        source="history_frequent",
        source_kb_ids=[],
        citations=[],
        occurrence_count=5,
        hit_count=0,
    )
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_scalar_result([entry]))
    user = SimpleNamespace(roles=[SimpleNamespace(id=role_id, is_enabled=True)])

    match = await RoleCacheService().lookup(
        db,
        question="测试问题",
        user=user,
        authorized_kb_ids=[uuid4()],
    )

    assert match is None
    assert entry.hit_count == 0


def test_parse_document_cache_items_maps_refs_to_citations() -> None:
    """模型 refs 必须映射为真实片段引用与知识库权限范围，无效 refs 项应被丢弃。"""
    kb_id = uuid4()
    doc_id = uuid4()
    materials = [
        {
            "ref": 1,
            "kb_id": str(kb_id),
            "doc_id": str(doc_id),
            "doc_name": "员工手册.md",
            "chunk_index": 2,
            "content": "员工每年可享受年假。",
        }
    ]
    raw = """```json
    {"items":[
      {"question":"员工是否有年假？","answer":"员工每年可享受年假。","refs":[1]},
      {"question":"无来源问题","answer":"无来源答案","refs":[99]}
    ]}
    ```"""

    parsed = RoleCacheService._parse_generated_items(raw, materials, limit=20)

    assert len(parsed) == 1
    assert parsed[0]["source_kb_ids"] == [kb_id]
    assert parsed[0]["citations"][0]["doc_id"] == str(doc_id)
    assert parsed[0]["citations"][0]["score"] == 1.0


def test_history_meta_source_ids_support_regular_and_cache_answers() -> None:
    """历史高频补充既可继承普通检索范围，也可继承已有缓存答案范围。"""
    first, second = uuid4(), uuid4()
    regular = RoleCacheService._source_kb_ids_from_meta({"authorized_kb_ids": [str(first), "invalid"]})
    cached = RoleCacheService._source_kb_ids_from_meta({"cache": {"source_kb_ids": [str(second)]}})

    assert regular == [first]
    assert cached == [second]


@pytest.mark.asyncio
async def test_scheduler_failure_does_not_skip_other_role_or_history_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单个角色的文档分析失败后，其他角色及历史分析仍必须继续执行。"""
    first_role_id, second_role_id = uuid4(), uuid4()
    configs = [
        SimpleNamespace(
            role_id=first_role_id,
            interval_days=7,
            last_document_analysis_at=None,
            last_history_analysis_at=None,
        ),
        SimpleNamespace(
            role_id=second_role_id,
            interval_days=7,
            last_document_analysis_at=None,
            last_history_analysis_at=None,
        ),
    ]
    config_db = AsyncMock()
    config_db.scalars = AsyncMock(return_value=_scalar_result(configs))

    def session_context(database: AsyncMock) -> MagicMock:
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=database)
        context.__aexit__ = AsyncMock(return_value=None)
        return context

    # 一次配置查询加四个独立分析事务，验证任何回滚都不会共享会话状态。
    session_factory = MagicMock(
        side_effect=[
            session_context(config_db),
            session_context(AsyncMock()),
            session_context(AsyncMock()),
            session_context(AsyncMock()),
            session_context(AsyncMock()),
        ]
    )
    document_analysis = AsyncMock(
        side_effect=[
            RuntimeError("模拟首个角色文档分析失败"),
            CacheAnalysisResult(second_role_id, "document_generated", 20, 30, "完成"),
        ]
    )
    history_analysis = AsyncMock(
        side_effect=[
            CacheAnalysisResult(first_role_id, "history_frequent", 5, 10, "完成"),
            CacheAnalysisResult(second_role_id, "history_frequent", 5, 10, "完成"),
        ]
    )
    monkeypatch.setattr("app.services.role_cache.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.role_cache.ensure_role_cache_configs", AsyncMock())
    monkeypatch.setattr("app.services.role_cache.role_cache_service.analyze_documents", document_analysis)
    monkeypatch.setattr("app.services.role_cache.role_cache_service.analyze_history", history_analysis)

    stats = await run_role_cache_scheduler_once()

    assert stats == {"scheduled": 4, "completed": 3, "failed": 1}
    assert [call.args[1] for call in document_analysis.await_args_list] == [
        first_role_id,
        second_role_id,
    ]
    assert [call.args[1] for call in history_analysis.await_args_list] == [
        first_role_id,
        second_role_id,
    ]
    assert session_factory.call_count == 5

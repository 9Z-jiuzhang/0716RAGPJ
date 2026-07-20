"""Query 预处理独立模型与管理员策略测试。"""

import pytest
from app.core.config import settings
from app.services.llm import (
    guard_llm_service,
    llm_service,
    query_processing_llm_service,
)
from app.services.query_processing import QueryProcessingOptions, QueryProcessor


def test_guard_and_query_processing_use_independent_fast_clients() -> None:
    """两类短任务必须与主回答模型使用不同客户端，并读取各自模型配置。"""
    assert guard_llm_service is not llm_service
    assert query_processing_llm_service is not llm_service
    assert guard_llm_service is not query_processing_llm_service
    assert guard_llm_service.model == settings.LLM_GUARD_MODEL
    assert query_processing_llm_service.model == settings.QA_QUERY_PROCESSING_MODEL


@pytest.mark.asyncio
async def test_disabled_query_features_do_not_call_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管理员关闭全部能力后应直接使用原问题，不产生任何预处理模型开销。"""

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("所有 Query 预处理开关关闭时不应调用模型")

    monkeypatch.setattr(
        "app.services.query_processing.query_processing_llm_service.chat",
        fail_if_called,
    )
    result = await QueryProcessor().process(
        "年假有几天？",
        [],
        options=QueryProcessingOptions(
            rewrite_enabled=False,
            expansion_enabled=False,
            expansion_count=0,
            hyde_enabled=False,
        ),
    )

    assert result.rewritten_query == "年假有几天？"
    assert result.applied is False
    assert result.options["expansion_enabled"] is False

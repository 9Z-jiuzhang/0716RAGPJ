"""RAGAS 0.4 指标调用与真实问答样本抽取测试。"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.core.config import settings
from app.services.ragas_evaluation import (
    RagasEvaluationService,
    RagasSample,
    RagasSampleSpec,
)


class FakeMetric:
    """模拟 RAGAS collections 指标的异步 ascore 接口。"""

    def __init__(self, value: float = 0.8, reason: str = "评分原因", error: Exception | None = None):
        self.value = value
        self.reason = reason
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def ascore(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(value=self.value, reason=self.reason)


def _scalar_result(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = items
    return result


@pytest.mark.asyncio
async def test_score_sample_uses_collections_ascore_and_keeps_partial_results() -> None:
    """每项指标独立调用，单项异常不应丢弃其他 RAGAS 分数。"""
    faithfulness = FakeMetric(value=0.92, reason="回答由上下文支持")
    relevancy = FakeMetric(error=RuntimeError("模拟失败"))
    recall = FakeMetric(value=0.7)
    sample = RagasSample(
        qa_message_id=uuid4(),
        user_input="年假有几天？",
        response="员工可享受年假。",
        retrieved_contexts=["员工依法享受年假。"],
    )

    result = await RagasEvaluationService.score_sample(
        {
            "faithfulness": faithfulness,
            "answer_relevancy": relevancy,
            "context_recall": recall,
        },
        sample,
    )

    assert result.scores["faithfulness"] == 0.92
    assert result.reasons["faithfulness"] == "回答由上下文支持"
    assert result.errors["answer_relevancy"] == "RuntimeError"
    # 缺少 reference 时上下文召回率不运行，不能拿生成答案冒充标准答案。
    assert recall.calls == []


@pytest.mark.asyncio
async def test_context_recall_receives_reference_when_available() -> None:
    """有标准答案时才向 Context Recall 传入 reference。"""
    recall = FakeMetric(value=1.2, reason="完整覆盖")
    sample = RagasSample(
        qa_message_id=uuid4(),
        user_input="申请流程是什么？",
        response="先提交申请。",
        retrieved_contexts=["申请人应先提交申请。"],
        reference="申请人先提交申请。",
    )

    result = await RagasEvaluationService.score_sample({"context_recall": recall}, sample)

    # 外部指标异常超出 0-1 时做边界保护。
    assert result.scores["context_recall"] == 1.0
    assert recall.calls[0]["reference"] == sample.reference


@pytest.mark.asyncio
async def test_each_collection_metric_receives_only_its_supported_arguments() -> None:
    """RAGAS 0.4 指标签名不同，禁止用同一个通用参数字典调用全部指标。"""
    metrics = {
        "faithfulness": FakeMetric(),
        "answer_relevancy": FakeMetric(),
        "context_precision": FakeMetric(),
        "context_recall": FakeMetric(),
    }
    sample = RagasSample(
        qa_message_id=uuid4(),
        user_input="年假有几天？",
        response="员工依法享受年假。",
        retrieved_contexts=["员工依法享受年假。"],
        reference="员工享有法定年假。",
    )

    result = await RagasEvaluationService.score_sample(metrics, sample)

    assert set(result.scores) == set(metrics)
    assert set(metrics["faithfulness"].calls[0]) == {
        "user_input",
        "response",
        "retrieved_contexts",
    }
    assert set(metrics["answer_relevancy"].calls[0]) == {
        "user_input",
        "response",
    }
    assert set(metrics["context_precision"].calls[0]) == {
        "user_input",
        "response",
        "retrieved_contexts",
    }
    assert set(metrics["context_recall"].calls[0]) == {
        "user_input",
        "retrieved_contexts",
        "reference",
    }


@pytest.mark.asyncio
async def test_collect_samples_filters_citations_by_target_knowledge_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """评估目标知识库时，只能把该库文档片段放入 retrieved_contexts。"""
    target_kb_id = uuid4()
    target_doc_id = uuid4()
    other_doc_id = uuid4()
    assistant = SimpleNamespace(
        id=uuid4(),
        content="员工每年可享受年假。",
        citations=[
            {"doc_id": str(target_doc_id), "content": "目标知识库片段"},
            {"doc_id": str(other_doc_id), "content": "其他知识库片段"},
        ],
        retrieval_meta={"original_query": "员工是否有年假？"},
        request_id="request-1",
        created_at=SimpleNamespace(),
    )
    db = AsyncMock()
    db.scalars = AsyncMock(
        side_effect=[
            _scalar_result([target_doc_id]),
            _scalar_result([assistant]),
        ]
    )
    monkeypatch.setattr(settings, "RAGAS_MAX_CONTEXTS_PER_SAMPLE", 10)
    monkeypatch.setattr(settings, "RAGAS_CONTEXT_MAX_CHARS", 3000)

    samples = await RagasEvaluationService().collect_samples(
        db,
        kb_id=target_kb_id,
        limit=5,
    )

    assert len(samples) == 1
    assert samples[0].user_input == "员工是否有年假？"
    assert samples[0].retrieved_contexts == ["目标知识库片段"]
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_samples_requires_cited_documents() -> None:
    """知识库没有文档时应直接返回空样本，不调用评估模型。"""
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_scalar_result([]))

    samples = await RagasEvaluationService().collect_samples(db, kb_id=uuid4(), limit=10)

    assert samples == []
    assert db.scalars.await_count == 1


def test_parse_generated_questions_keeps_only_grounded_items() -> None:
    """自动生成题必须引用真实片段编号，并去重。"""
    materials = [
        {"ref": 1, "doc_name": "手册", "content": "年假 5 天"},
        {"ref": 2, "doc_name": "手册", "content": "试用期 3 个月"},
    ]
    raw = """{
      "items": [
        {"question": "年假几天？", "reference": "5 天", "refs": [1]},
        {"question": "年假几天？", "reference": "重复", "refs": [1]},
        {"question": "无来源？", "reference": "x", "refs": [9]},
        {"question": "试用期多久？", "reference": "3 个月", "refs": [2]}
      ]
    }"""

    items = RagasEvaluationService._parse_generated_questions(raw, materials, limit=5)

    assert [item.question for item in items] == ["年假几天？", "试用期多久？"]
    assert items[0].reference == "5 天"
    assert items[0].source_chunk_count == 1


@pytest.mark.asyncio
async def test_resolve_samples_uses_specs_when_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    """提交样本规格时，应优先按规格解析，而不是自动抽历史。"""
    service = RagasEvaluationService()
    target = RagasSample(
        qa_message_id=None,
        user_input="自定义问题",
        response="自定义回答",
        retrieved_contexts=["证据"],
        reference="标准答案",
    )

    async def fake_materialize(*_args, **_kwargs):
        return target

    monkeypatch.setattr(service, "materialize_question", fake_materialize)
    monkeypatch.setattr(service, "collect_samples", AsyncMock(return_value=[]))

    samples = await service.resolve_samples(
        AsyncMock(),
        kb_id=uuid4(),
        sample_limit=10,
        sample_specs=[RagasSampleSpec(question="自定义问题", reference="标准答案")],
    )

    assert samples == [target]
    service.collect_samples.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_metrics_supplies_embeddings_for_answer_relevancy() -> None:
    """真实构造 RAGAS 指标，防止依赖安装后才暴露缺少 embedding 的问题。"""
    metrics, clients = await RagasEvaluationService._build_metrics()
    try:
        assert set(metrics) == {
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
        }
        # RAGAS 0.4 的 AnswerRelevancy 强制依赖向量模型，不能只传评估 LLM。
        assert metrics["answer_relevancy"].embeddings is not None
        # 生产样本通常无 reference，必须使用能接收 response 的官方无参考版本。
        assert metrics["context_precision"].__class__.__name__ == "ContextPrecisionWithoutReference"

        signature_sample = RagasSample(
            qa_message_id=uuid4(),
            user_input="年假有几天？",
            response="员工依法享受年假。",
            retrieved_contexts=["员工依法享受年假。"],
            reference="员工享有法定年假。",
        )
        for metric_name, metric in metrics.items():
            actual_parameters = set(inspect.signature(metric.ascore).parameters)
            supplied_parameters = set(
                RagasEvaluationService._metric_arguments(
                    metric_name,
                    signature_sample,
                )
            )
            assert supplied_parameters == actual_parameters
    finally:
        # 测试不发起外部请求，但仍应关闭 SDK 内部的 HTTP 连接池。
        for client in clients:
            await client.close()

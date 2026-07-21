"""命中率测试口径：命中列看命中率，得分列看命中片段相关度均值。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.schemas.hit_tests import TestQuestion as HitTestQuestion
from app.services.hit_test_service import HitTestService


def test_unlabeled_question_smoke_hit_uses_any_recall() -> None:
    """临时/纯问题冒烟：有召回即命中，相关度取命中位次分数。"""
    service = HitTestService(AsyncMock())
    is_hit, rank = service._check_hit(
        results=[{"doc_id": str(uuid4()), "chunk_id": str(uuid4()), "score": 0.99}],
        expected_doc_ids=None,
        expected_chunk_ids=None,
    )

    assert is_hit is True
    assert rank == 1


def test_ground_truth_validation_reports_question_position() -> None:
    """用例中任一题缺少标准答案时，应明确报告题号。"""
    labeled_doc = uuid4()
    questions = [
        HitTestQuestion(question="已标注题", expected_doc_ids=[labeled_doc]),
        HitTestQuestion(question="未标注题"),
    ]

    with pytest.raises(ValueError, match="第 2 题"):
        HitTestService._validate_ground_truth(questions)


def test_run_score_is_average_of_hit_relevance() -> None:
    """运行级 score 应为命中片段相关度均值，而不是命中率。"""
    now = datetime.now(timezone.utc)
    run = SimpleNamespace(
        id=uuid4(),
        case_id=uuid4(),
        kb_ids=[uuid4()],
        strategy="hybrid",
        top_k=5,
        status="completed",
        total_questions=4,
        hit_count=3,
        recall_at_k=0.75,
        mrr=0.625,
        avg_elapsed_ms=12.5,
        created_at=now,
        completed_at=now,
        results=[
            SimpleNamespace(score=0.9),
            SimpleNamespace(score=0.6),
            SimpleNamespace(score=None),
            SimpleNamespace(score=0.8),
        ],
    )

    response = HitTestService(AsyncMock())._convert_run_to_response(run)

    assert response.hit_rate == 0.75
    assert response.score == pytest.approx((0.9 + 0.6 + 0.8) / 3)
    assert response.score != response.hit_rate


def test_run_score_zero_when_no_hits() -> None:
    """全部未命中时综合得分为 0。"""
    now = datetime.now(timezone.utc)
    run = SimpleNamespace(
        id=uuid4(),
        case_id=None,
        kb_ids=[uuid4()],
        strategy="hybrid",
        top_k=5,
        status="completed",
        total_questions=2,
        hit_count=0,
        recall_at_k=0.0,
        mrr=None,
        avg_elapsed_ms=10.0,
        created_at=now,
        completed_at=now,
        results=[SimpleNamespace(score=None), SimpleNamespace(score=None)],
    )

    response = HitTestService(AsyncMock())._convert_run_to_response(run)

    assert response.hit_rate == 0.0
    assert response.score == 0.0

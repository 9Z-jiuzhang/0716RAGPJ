"""命中率测试口径专项测试：必须基于标准答案，得分等于命中率。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.schemas.hit_tests import TestQuestion as HitTestQuestion
from app.schemas.hit_tests import TestRunRequest as HitTestRunRequest
from app.services.hit_test_service import HitTestService


def test_unlabeled_question_is_not_counted_as_hit() -> None:
    """即使检索有结果，未标注期望文档/分段也不能被当作命中。"""
    service = HitTestService(AsyncMock())
    is_hit, rank = service._check_hit(
        results=[{"doc_id": str(uuid4()), "chunk_id": str(uuid4()), "score": 0.99}],
        expected_doc_ids=None,
        expected_chunk_ids=None,
    )

    assert is_hit is False
    assert rank is None


def test_ground_truth_validation_reports_question_position() -> None:
    """用例中任一题缺少标准答案时，应明确报告题号并拒绝执行。"""
    labeled_doc = uuid4()
    questions = [
        HitTestQuestion(question="已标注题", expected_doc_ids=[labeled_doc]),
        HitTestQuestion(question="未标注题"),
    ]

    with pytest.raises(ValueError, match="第 2 题"):
        HitTestService._validate_ground_truth(questions)


@pytest.mark.asyncio
async def test_temporary_questions_are_rejected() -> None:
    """临时问题没有标准答案，不能再通过“有召回即命中”生成虚假 100%。"""
    service = HitTestService(AsyncMock())
    request = HitTestRunRequest(
        kb_ids=[uuid4()],
        strategy="hybrid",
        questions=["未标注的临时问题"],
    )

    with pytest.raises(ValueError, match="不能用于命中率测试"):
        await service.execute_test_run(request)


def test_run_score_equals_displayed_hit_rate() -> None:
    """运行级 score 与 hit_rate 必须使用同一计算结果。"""
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
    )

    response = HitTestService(AsyncMock())._convert_run_to_response(run)

    assert response.hit_rate == 0.75
    assert response.score == response.hit_rate

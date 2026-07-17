"""5.6 问答测试用例表（可参数化执行的用例元数据 + 断言辅助）。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class QACase:
    case_id: str
    question: str
    expect_hit: bool
    expect_keywords: tuple[str, ...]
    strategy: str = "hybrid"
    notes: str = ""


# 与 testdata/qa_kb/TEST_CASES.md 对齐
HIT_CASES: list[QACase] = [
    QACase("A1", "司龄满 10 年不满 20 年的员工年假多少天？", True, ("10", "天"), "hybrid"),
    QACase("A2", "年假未休完可以结转到什么时候？", True, ("3", "月", "31"), "hybrid"),
    QACase("A3", "一线城市差旅住宿上限是多少？", True, ("550",), "fulltext"),
    QACase("A4", "出差餐饮补助标准？", True, ("100",), "fulltext"),
    QACase("A5", "外包人员临时账号最长有效期？", True, ("90",), "hybrid"),
    QACase("A6", "连续年假超过 5 天需要谁审批？", True, ("人力资源",), "hybrid"),
]

MISS_CASES: list[QACase] = [
    QACase("B1", "公司股票期权行权价怎么算？", False, ("知识库未命中",), "hybrid"),
    QACase("B2", "火星基地外派补贴多少？", False, ("知识库未命中",), "hybrid"),
]


@pytest.mark.parametrize("case", HIT_CASES, ids=lambda c: c.case_id)
def test_hit_case_catalog(case: QACase) -> None:
    """用例目录完整性：命中类问题应带期望关键词。"""
    assert case.expect_hit is True
    assert case.question.strip()
    assert case.expect_keywords


@pytest.mark.parametrize("case", MISS_CASES, ids=lambda c: c.case_id)
def test_miss_case_catalog(case: QACase) -> None:
    """用例目录完整性：未命中类问题应声明知识库未命中。"""
    assert case.expect_hit is False
    assert "知识库未命中" in case.expect_keywords

"""cite_validation overlap 轻校验单元测试。"""

from __future__ import annotations

from unittest.mock import patch

from app.services.cite_validation import (
    citations_with_index,
    inline_citation_prompt_rule,
    overlap_score,
    validate_answer_citations,
)


def test_overlap_score_exact_substring() -> None:
    score = overlap_score("2019年全球半导体销售总额为4121亿美元", "2019年全球半导体销售总额为4121亿美元。")
    assert score >= 0.3


def test_overlap_score_unrelated_is_low() -> None:
    score = overlap_score("完全不同的句子", "2019年全球半导体销售总额为4121亿美元")
    assert score < 0.1


def test_validate_answer_citations_verdicts() -> None:
    citations = [
        {"cite_index": 1, "content": "2019年全球半导体销售总额为4121亿美元"},
        {"cite_index": 2, "content": "集成电路产业自主化需求迫切"},
    ]
    answer = "2019年全球半导体销售总额为4121亿美元[1]。"
    results = validate_answer_citations(answer, citations)
    assert len(results) == 2
    assert results[0]["verdict"] == "grounded"
    assert results[1]["verdict"] in {"uncertain", "unverified"}


def test_citations_with_index_matches_evidence_order() -> None:
    class _Hit:
        def __init__(self, i: int) -> None:
            self.i = i

        def to_cite(self) -> dict:
            return {"content": f"body-{self.i}"}

    hits = [_Hit(1), _Hit(2)]
    out = citations_with_index(hits, lambda h: h.to_cite())
    assert [c["cite_index"] for c in out] == [1, 2]


def test_inline_citation_prompt_rule_non_empty() -> None:
    assert "[1]" in inline_citation_prompt_rule()


def test_record_metrics_on_unverified() -> None:
    from app.services.cite_validation import record_cite_validation_metrics

    with patch("app.services.cite_validation.cite_validation_unverified_total") as counter:
        record_cite_validation_metrics([{"verdict": "unverified"}, {"verdict": "grounded"}])
        counter.inc.assert_called_once()

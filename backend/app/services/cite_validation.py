"""引用 overlap 轻校验（E 模块）：默认仅观测，不降级 confidence。"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings
from app.core.metrics import cite_validation_unverified_total
from app.retrieval.fulltext import FulltextRetriever

_GROUNDED_THRESHOLD = 0.3
_UNCERTAIN_THRESHOLD = 0.1
_CITE_BRACKET_RE = re.compile(r"\[(\d{1,2})\]")


def overlap_score(answer_text: str, chunk_content: str) -> float:
    """字面覆盖率 fast path（与全文 ILIKE 降级同口径）。"""
    return FulltextRetriever._lexical_coverage_score(answer_text or "", chunk_content or "")


def _snippet_around_cite(answer: str, cite_index: int, *, radius: int = 120) -> str:
    """取 [N] 附近文本；无标记时退回整段答案。"""
    text = answer or ""
    pattern = re.compile(rf"\[{cite_index}\]")
    match = pattern.search(text)
    if not match:
        return text.strip()
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end].strip()


def _verdict(score: float) -> str:
    if score >= _GROUNDED_THRESHOLD:
        return "grounded"
    if score >= _UNCERTAIN_THRESHOLD:
        return "uncertain"
    return "unverified"


def validate_answer_citations(answer: str, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对每条引用计算 overlap；返回带 cite_validation 的结果（内部用）。"""
    if not answer or not citations:
        return []
    results: list[dict[str, Any]] = []
    for cite in citations:
        idx = int(cite.get("cite_index") or 0)
        chunk = str(cite.get("content") or "")
        snippet = _snippet_around_cite(answer, idx) if idx > 0 else answer
        score = overlap_score(snippet, chunk)
        verdict = _verdict(score)
        results.append(
            {
                "cite_index": idx,
                "score": round(score, 4),
                "verdict": verdict,
                "method": "ngram_coverage",
            }
        )
    return results


def record_cite_validation_metrics(validations: list[dict[str, Any]]) -> None:
    """enforce=false 时仍计数 unverified（RUNBOOK）。"""
    for item in validations:
        if item.get("verdict") == "unverified":
            cite_validation_unverified_total.inc()


def annotate_citations_if_enforce(
    citations: list[dict[str, Any]],
    validations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """enforce=true 时在 citation 上暴露 unverified（首期默认不暴露）。"""
    if not settings.CITE_VALIDATION_ENFORCE or not validations:
        return citations
    by_index = {int(v.get("cite_index") or 0): v for v in validations}
    out: list[dict[str, Any]] = []
    for cite in citations:
        patched = dict(cite)
        idx = int(patched.get("cite_index") or 0)
        validation = by_index.get(idx)
        if validation:
            patched["cite_validation"] = validation
            if validation.get("verdict") == "unverified":
                patched["unverified"] = True
        out.append(patched)
    return out


def citations_with_index(hits: list[Any], hit_to_citation: Any) -> list[dict[str, Any]]:
    """按证据顺序附加 cite_index（与提示词 [1]…[N] 对齐）。"""
    citations: list[dict[str, Any]] = []
    for i, hit in enumerate(hits, start=1):
        cite = hit_to_citation(hit)
        cite["cite_index"] = i
        citations.append(cite)
    return citations


def inline_citation_prompt_rule() -> str:
    """INLINE_CITATION_ENABLED 时追加到 RAG system prompt。"""
    return (
        "11. 在陈述具体事实、数字或制度条款时，请在句末标注对应证据编号，格式为 [1]、[2]；"
        "编号必须与「检索证据」中的 [1]、[2]… 一致，不要编造未出现的编号。"
    )

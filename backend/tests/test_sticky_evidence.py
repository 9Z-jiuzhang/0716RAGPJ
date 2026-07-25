"""粘性证据、跟进问查询增强与提示词约束回归。"""

from __future__ import annotations

from uuid import uuid4

from app.core.qa_pipeline import _RAG_SYSTEM_PROMPT
from app.memory.models import ContextMessage, SessionMemory
from app.retrieval.types import RetrievalHit
from app.services.sticky_evidence import (
    augment_followup_query,
    merge_retrieval_hits,
)


def _hit(chunk_id: str, *, score: float = 0.8, source: str = "hybrid", sticky: bool = False) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        doc_id=str(uuid4()),
        doc_name="手册.md",
        kb_id=str(uuid4()),
        chunk_index=1,
        content="工作时间相关",
        score=score,
        source="sticky" if sticky else source,  # type: ignore[arg-type]
        metadata={"sticky": sticky} if sticky else {},
    )


def test_merge_keeps_sticky_first_and_dedupes() -> None:
    sticky = [_hit("s1", sticky=True, score=0.5)]
    primary = [_hit("s1", score=0.9), _hit("p2", score=0.85)]
    merged = merge_retrieval_hits(primary, sticky, cap=8)
    assert [h.chunk_id for h in merged] == ["s1", "p2"]


def test_merge_respects_cap() -> None:
    sticky = [_hit(f"s{i}", sticky=True) for i in range(3)]
    primary = [_hit(f"p{i}") for i in range(10)]
    merged = merge_retrieval_hits(primary, sticky, cap=5)
    assert len(merged) == 5
    assert merged[0].chunk_id.startswith("s")


def test_augment_followup_query_keeps_time_keywords() -> None:
    original = "明天几点上班"
    rewritten = "员工仪容仪表与工作纪律规定"
    out = augment_followup_query(original, rewritten)
    assert "上班" in out
    assert "几点" in out
    assert "仪容" in out


def test_augment_noop_when_keywords_present() -> None:
    q = "公司几点上班"
    assert augment_followup_query(q, q) == q


def test_rag_prompt_forbids_calling_history_hallucination() -> None:
    assert "幻觉" in _RAG_SYSTEM_PROMPT
    assert "不得将对话历史中的助手回答称为" in _RAG_SYSTEM_PROMPT
    assert "本轮检索依据不足" in _RAG_SYSTEM_PROMPT


def test_history_assistant_messages_marked_non_evidence() -> None:
    memory = SessionMemory(
        session_id=str(uuid4()),
        messages=[
            ContextMessage(role="user", content="几点上班"),
            ContextMessage(role="assistant", content="根据手册，上班时间为 9:00。"),
        ],
    )
    msgs = memory.to_llm_messages()
    assistant = next(m for m in msgs if m["role"] == "assistant")
    assert "非本轮检索证据" in assistant["content"]
    assert "9:00" in assistant["content"]


def test_followup_top_k_setting_default() -> None:
    from app.core.config import settings

    assert settings.QA_FOLLOWUP_TOP_K >= 5
    assert settings.QA_STICKY_EVIDENCE_ENABLED is True
    assert settings.QA_NEIGHBOR_CHUNKS_ENABLED is True

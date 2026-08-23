"""2.1.13 功能单测：asset / 推荐追问 / CJK / 澄清路由。"""

from __future__ import annotations

from unittest.mock import patch

from app.services.asset_citation import (
    asset_api_url,
    citation_asset_image,
    merge_citation_images,
)
from app.services.conversation_router import conversation_router
from app.services.cjk_fulltext import prepare_query_for_tsvector
from app.services.suggested_questions import (
    _strip_template,
    build_suggested_questions,
)


def test_asset_api_url_format() -> None:
    url = asset_api_url("doc-1", "abc123def456")
    assert url == "/api/v1/qa/documents/doc-1/assets/abc123def456"


def test_merge_citation_images_asset_first() -> None:
    asset = citation_asset_image(doc_id="d1", asset_id="a1")
    page = {"kind": "page", "page": 2, "url": "/charts/page-02.png"}
    merged = merge_citation_images({}, asset_images=[asset], page_images=[page])
    assert merged[0]["kind"] == "asset"
    assert merged[1]["kind"] == "page"


def test_strip_template() -> None:
    assert _strip_template("除了「具身数据…」，还有哪些值得关注的背景信息？") == "具身数据…"
    assert _strip_template("K线项目具体定位？") == "K线项目具体定位？"


def test_no_nested_repetition() -> None:
    with patch("app.services.suggested_questions.suggested_questions_enabled", return_value=True):
        qs = build_suggested_questions(
            question="除了「具身数据…」，还有哪些值得关注的背景信息？",
            answer="具身数据与文本语料在生成方式上存在差异。",
            citations=[{"doc_name": "doc1"}],
        )
    assert all("除了「除了" not in q for q in qs)
    assert all("还有哪些值得关注的背景信息" not in q for q in qs)


def test_rejects_rag_meta_phrases_in_suggestions() -> None:
    with patch("app.services.suggested_questions.suggested_questions_enabled", return_value=True):
        qs = build_suggested_questions(
            question="某个问题",
            answer="根据检索证据，本轮检索依据不足，无法回答用户询问。",
            citations=[
                {
                    "doc_name": "集成电路报告.pdf",
                    "content": "2019年集成电路设计企业达1780家，同比增长26.7%。",
                }
            ],
        )
    assert qs
    assert all("检索证据" not in q for q in qs)
    assert all("用户询问" not in q for q in qs)
    assert all("在知识库中如何定义 在知识库" not in q for q in qs)
    assert any("2019" in q or "1780" in q or "集成电路报告" in q for q in qs)


def test_build_suggested_questions_from_answer_entities() -> None:
    with patch("app.services.suggested_questions.suggested_questions_enabled", return_value=True):
        qs = build_suggested_questions(
            question="半导体市场规模",
            answer="2019年全球半导体销售总额为4121亿美元。",
            citations=[
                {
                    "doc_name": "流片线计划",
                    "block_type": "text",
                    "content": "全球半导体销售总额4121亿美元。",
                },
            ],
        )
    assert qs
    assert len(qs) <= 3
    assert any("2019" in q for q in qs)
    assert not any("除了「" in q for q in qs)


def test_cjk_prepare_query_inserts_spaces_not_jieba_lib() -> None:
    """zh_jieba 后端 = 查询侧 CJK 插空格，非 Python jieba 分词。"""
    with patch("app.services.cjk_fulltext.active_backend", return_value="zh_jieba"):
        out = prepare_query_for_tsvector("多项目晶圆MPW")
    assert " " in out
    assert "多" in out and "项" in out


def test_clarify_vague_kb_query() -> None:
    decision = conversation_router.route(
        question="那个集成电路政策到底怎么样？",
        has_last_answer=False,
        clarify_enabled=True,
    )
    assert decision.should_clarify
    assert decision.reason_code == "vague_kb_query"
    assert conversation_router.template_reply(decision)


def test_clarify_disabled_skips_vague() -> None:
    decision = conversation_router.route(
        question="那个集成电路政策到底怎么样？",
        has_last_answer=False,
        clarify_enabled=False,
    )
    assert decision.reason_code != "vague_kb_query"

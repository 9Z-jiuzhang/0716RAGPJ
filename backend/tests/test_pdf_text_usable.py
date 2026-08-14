"""PDF 乱码检测与抽取兜底。"""

from __future__ import annotations

from app.services.parsers import is_unusable_pdf_text


def test_detects_uni_cid_garbage() -> None:
    garbage = "/uni00000037/uni00000017 /uni0000001f/uni0000001e " * 20
    assert is_unusable_pdf_text(garbage) is True


def test_accepts_chinese_body() -> None:
    text = "锦盈四季 · 竞品对比分析测试报告\n本测试 PDF 用于验证知识库文档。"
    assert is_unusable_pdf_text(text) is False


def test_accepts_ascii_numeric_page() -> None:
    text = "Q1 120\nQ2 145\nQ3 168\nQ4 190\nSales comparison chart values 98 112 130 155"
    assert is_unusable_pdf_text(text) is False


def test_empty_is_unusable() -> None:
    assert is_unusable_pdf_text("") is True
    assert is_unusable_pdf_text(None) is True

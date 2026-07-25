"""全模式分段覆盖率与防丢内容回归测试。"""

from __future__ import annotations

import re

import pytest

from app.services.chunking import (
    ChunkCoverageError,
    content_coverage_ratio,
    ensure_chunk_coverage,
    merge_rules,
    split_text,
)


ALL_MODES = ("markdown", "paragraph", "fixed", "sliding", "heading")


def _dense_list_doc(n: int = 40) -> str:
    items = "\n".join(f"（{i}）条款内容第{i}条，说明文字若干。" for i in range(1, n + 1))
    return (
        "### 集团公司员工管理手册\n\n"
        "#### 1.总则\n\n"
        "为使本公司员工更好地遵守公司管理制度，特制定本守则。\n\n"
        "#### 2.员工守则\n\n"
        "**2.1仪容仪表规定**\n"
        f"{items}\n"
    )


@pytest.mark.parametrize("mode", ALL_MODES)
def test_all_modes_cover_dense_single_newline_lists(mode: str) -> None:
    """团队报告场景：单换行连续条款在任意模式下不得丢内容。"""
    text = _dense_list_doc()
    chunks = split_text(
        text,
        {
            "chunk_size": 220,
            "chunk_overlap": 40,
            "separators": ["\n\n", "\n", "。", ".", " "],
            "split_mode": mode,
        },
    )
    joined = "\n".join(c.content for c in chunks)
    assert "（1）" in joined
    assert "（20）" in joined
    assert f"（{40}）" in joined
    assert content_coverage_ratio(text, [c.content for c in chunks]) >= 0.99


@pytest.mark.parametrize("mode", ALL_MODES)
def test_all_modes_cover_plain_no_blank_lines(mode: str) -> None:
    text = "引言。" + "".join(f"这是第{i}句用于验证无空行长文切分。" for i in range(1, 60))
    chunks = split_text(
        text,
        {"chunk_size": 120, "chunk_overlap": 20, "split_mode": mode},
    )
    assert chunks
    assert content_coverage_ratio(text, [c.content for c in chunks]) >= 0.99


@pytest.mark.parametrize("mode", ALL_MODES)
def test_all_modes_cover_crlf(mode: str) -> None:
    text = "第一段内容。\r\n\r\n第二段内容。\r\n（1）条目A。\r\n（2）条目B。\r\n"
    chunks = split_text(text, {"chunk_size": 80, "chunk_overlap": 10, "split_mode": mode})
    assert content_coverage_ratio(text, [c.content for c in chunks]) >= 0.99
    joined = "".join(c.content for c in chunks)
    assert "条目A" in joined and "条目B" in joined


def test_empty_separator_is_sanitized() -> None:
    text = "甲段。乙段。丙段。" + ("补充" * 40)
    chunks = split_text(
        text,
        {
            "chunk_size": 50,
            "chunk_overlap": 5,
            "separators": ["\n\n", "", "。", " "],
            "split_mode": "fixed",
        },
    )
    assert chunks
    assert content_coverage_ratio(text, [c.content for c in chunks]) >= 0.99


def test_overlap_ge_chunk_size_still_covers() -> None:
    text = "甲" * 40 + "乙" * 40
    chunks = split_text(
        text,
        {"chunk_size": 15, "chunk_overlap": 15, "split_mode": "sliding"},
    )
    assert chunks
    assert content_coverage_ratio(text, [c.content for c in chunks]) >= 0.99


def test_heading_only_sections_merged_into_following() -> None:
    text = "# 手册\n\n## 第一章\n\n本章正文应保留。\n"
    chunks = split_text(text, {"chunk_size": 500, "chunk_overlap": 0, "split_mode": "markdown"})
    # 不应出现仅含「# 手册」的空洞段
    assert not any(c.content.strip() == "# 手册" for c in chunks)
    assert any("本章正文应保留" in c.content for c in chunks)
    assert any("# 手册" in c.content for c in chunks)


def test_ensure_chunk_coverage_raises_on_loss() -> None:
    with pytest.raises(ChunkCoverageError):
        ensure_chunk_coverage("完整原文应全部保留ABCDEFG", ["AB"])


def test_merge_rules_drops_empty_separators() -> None:
    rules = merge_rules(None, {"separators": ["\n", "", "。"]})
    assert "" not in rules["separators"]
    assert "\n" in rules["separators"]


def test_unclosed_fence_not_lost() -> None:
    text = "# 示例\n\n```python\ndef hello():\n    return 42\n"
    chunks = split_text(text, {"chunk_size": 40, "chunk_overlap": 5, "split_mode": "markdown"})
    joined = "\n".join(c.content for c in chunks)
    assert "def hello" in joined
    assert content_coverage_ratio(text, [c.content for c in chunks]) >= 0.99


def test_file_type_defaults_still_high_coverage() -> None:
    """模拟各文件类型默认模式对同一正文的切分均需高覆盖。"""
    text = _dense_list_doc(25)
    for file_type, mode in (
        ("md", "markdown"),
        ("txt", "paragraph"),
        ("pdf", "paragraph"),
        ("docx", "paragraph"),
    ):
        chunks = split_text(
            text,
            {"chunk_size": 300, "chunk_overlap": 50, "split_mode": mode},
        )
        ratio = content_coverage_ratio(text, [c.content for c in chunks])
        assert ratio >= 0.99, (file_type, mode, ratio)


def test_legacy_regex_bug_fixture_no_clause_skip() -> None:
    """复现报告中的条款跳跃：修复后中间编号必须存在。"""
    body_lines = []
    for i in range(1, 25):
        body_lines.append(f"（{i}）条款{i}。")
        if i in {3, 16}:
            body_lines.append("")  # 仅少数空行，大部分仍是单换行
    text = "#### 2.员工守则\n\n**2.1**\n" + "\n".join(body_lines)
    chunks = split_text(
        text,
        {
            "chunk_size": 500,
            "chunk_overlap": 50,
            "separators": ["\n\n", "\n", "。", ".", " "],
            "split_mode": "markdown",
        },
    )
    joined = "\n".join(c.content for c in chunks)
    for i in range(1, 25):
        assert f"（{i}）" in joined, i
    # 忽略空白后，分段合计不应远小于原文
    src_len = len(re.sub(r"\s+", "", text))
    out_len = len(re.sub(r"\s+", "", joined))
    assert out_len >= src_len * 0.95

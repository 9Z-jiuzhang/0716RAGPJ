"""多模态版面 / 表图分块单测。"""

from __future__ import annotations

from app.services.chunking import split_text
from app.services.layout_blocks import (
    ContentBlock,
    evidence_content_from_metadata,
    serialize_blocks,
    split_table_with_header,
    table_rows_to_markdown,
)
from app.services.layout_parser import extract_layout


def test_html_layout_extracts_table_and_text():
    html = b"""
    <html><body>
      <p>intro</p>
      <table>
        <tr><th>Q</th><th>Rev</th></tr>
        <tr><td>Q1</td><td>100</td></tr>
        <tr><td>Q2</td><td>150</td></tr>
      </table>
      <p>end</p>
    </body></html>
    """
    serialized, blocks = extract_layout("demo.html", html, "html")
    assert any(b.block_type == "table" for b in blocks)
    assert any(b.block_type == "text" for b in blocks)
    assert "KB_BLOCK" in serialized
    assert "Q1" in serialized


def test_markdown_pipe_table_becomes_table_block():
    md = b"""# Title

| Name | Score |
| --- | --- |
| A | 90 |
| B | 85 |

Body text.
"""
    _, blocks = extract_layout("a.md", md, "md")
    types = [b.block_type for b in blocks]
    assert "table" in types
    table = next(b for b in blocks if b.block_type == "table")
    assert "A" in table.content
    assert "<table>" in table.html


def test_split_layout_keeps_table_atomic():
    md = table_rows_to_markdown(["A", "B"], [["1", "2"], ["3", "4"]])
    serialized = serialize_blocks(
        [
            ContentBlock(block_type="text", content=("intro " * 20).strip()),
            ContentBlock(block_type="table", content=md, markdown=md, html="<table></table>"),
        ]
    )
    chunks = split_text(serialized, {"split_mode": "paragraph", "chunk_size": 80, "chunk_overlap": 10})
    table_chunks = [c for c in chunks if (c.metadata or {}).get("block_type") == "table"]
    assert table_chunks
    assert all("|" in c.content for c in table_chunks)


def test_table_header_repeat_on_split():
    headers = ["C1", "C2"]
    rows = [[str(i), str(i * 2)] for i in range(40)]
    md = table_rows_to_markdown(headers, rows)
    parts = split_table_with_header(md, max_chars=200)
    assert len(parts) > 1
    for part in parts:
        assert part.splitlines()[0].startswith("| C1")


def test_evidence_prefers_parent_content():
    body = evidence_content_from_metadata(
        "summary",
        {
            "block_type": "table",
            "parent_content": "| Q | V |\n|---|---|\n| 1 | 2 |",
            "summary": "summary",
        },
    )
    assert "表格原文" in body or "parent" in body.lower() or "| Q | V |" in body
    assert "| Q | V |" in body

"""Excel/CSV 版面解析单测。"""

from __future__ import annotations

import io

from openpyxl import Workbook

from app.services.layout_parser import extract_layout
from app.services.spreadsheet_parser import extract_spreadsheet_blocks


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "营收"
    ws.append(["季度", "营收万元", "增长率"])
    ws.append(["Q1", 120, "5%"])
    ws.append(["Q2", 180, "50%"])
    ws.append(["Q3", 260, "44%"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_layout_extracts_table():
    content = _xlsx_bytes()
    text, blocks = extract_layout("rev.xlsx", content, "xlsx")
    assert any(b.block_type == "table" for b in blocks)
    assert any(b.block_type == "text" and "营收" in b.content for b in blocks)
    assert "Q3" in text and "260" in text
    assert any("<table" in (b.html or "") for b in blocks if b.block_type == "table")


def test_csv_layout_extracts_table():
    csv = "产品,销量\nA,10\nB,20\n".encode("utf-8")
    blocks = extract_spreadsheet_blocks(csv, "csv")
    assert any(b.block_type == "table" for b in blocks)
    table = next(b for b in blocks if b.block_type == "table")
    assert "A" in table.content and "10" in table.content

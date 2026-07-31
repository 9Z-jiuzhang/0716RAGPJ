# -*- coding: utf-8 -*-
"""Generate two unrelated isolation-test document groups (pdf/doc/docx/txt/md)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

GROUP_A = {
    "id": "A_qinglan_tea",
    "title": "青岚茶园运营手册",
    "org": "青岚茶园（浙江杭州）",
    "code": "TEA-QL-2024",
    "product": "青岚龙井特级",
    "hours": "每日 09:00–17:00（周一闭园养护）",
    "contact": "值班热线 0571-8800-2401",
    "rule": "会员凭实体卡入园，每卡每日限购青岚龙井特级 2 两。",
    "note": "本手册仅描述青岚茶园内部流程，不涉及海洋、深潜或科考站业务。",
    "pdf_title": "Qinglan Tea Garden Operations Manual",
}

GROUP_B = {
    "id": "B_xinggang_dive",
    "title": "星港深潜科考站作业规程",
    "org": "星港一号深潜科考站（南海试验区）",
    "code": "SEA-XG-2024",
    "product": "星港载人舱 XG-3",
    "hours": "下潜窗口每日 06:00–18:00（风力＞6 级取消）",
    "contact": "指挥室电台频道 XG-CTRL-7",
    "rule": "单次下潜最大作业深度 3000 米，舱内氧气余量低于 35% 必须上浮。",
    "note": "本规程仅描述星港科考站下潜作业，不涉及茶园、茶叶销售或陆地文旅业务。",
    "pdf_title": "Xinggang Deep-Dive Research Station SOP",
}


def body_paragraphs(g: dict) -> list[str]:
    return [
        g["title"],
        f"编制单位：{g['org']}",
        f"文档编号：{g['code']}",
        "",
        "一、概述",
        f"{g['org']}发布本文件，用于内部培训与现场执行。关键隔离标识词：{g['code']}。",
        "",
        "二、核心对象",
        f"主对象名称：{g['product']}",
        f"开放/作业时间：{g['hours']}",
        f"联系方式：{g['contact']}",
        "",
        "三、执行规则",
        g["rule"],
        "",
        "四、边界说明",
        g["note"],
        "",
        "五、检查清单",
        f"1. 确认文档编号为 {g['code']}；",
        f"2. 确认主对象为 {g['product']}；",
        f"3. 作业前复核时间窗：{g['hours']}。",
    ]


def md_text(g: dict) -> str:
    lines = body_paragraphs(g)
    out = [f"# {lines[0]}", ""]
    for line in lines[1:]:
        if line.startswith(("一、", "二、", "三、", "四、", "五、")):
            out.append(f"## {line}")
        else:
            out.append(line)
    out.append("")
    out.append(f"> 隔离测试标记：`{g['code']}`")
    out.append("")
    return "\n".join(out)


def txt_text(g: dict) -> str:
    return "\n".join(body_paragraphs(g)) + f"\n\n[隔离测试标记] {g['code']}\n"


def _escape_xml(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_docx_bytes(g: dict) -> bytes:
    paragraphs = body_paragraphs(g) + [f"隔离测试标记：{g['code']}"]
    p_xml: list[str] = []
    for i, line in enumerate(paragraphs):
        if not line:
            p_xml.append("<w:p/>")
            continue
        style = "Title" if i == 0 else "Normal"
        p_xml.append(
            "<w:p>"
            f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{_escape_xml(line)}</w:t></w:r>'
            "</w:p>"
        )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(p_xml)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
        "</w:body></w:document>"
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf_bytes(g: dict) -> bytes:
    """Minimal PDF; Chinese kept via unicode_escape so Helvetica can embed, plus unique codes."""
    eng = [
        f"Title: {g['pdf_title']}",
        f"Document Code: {g['code']}",
        f"Organization: {g['org']}",
        f"Primary Asset: {g['product']}",
        f"Schedule: {g['hours']}",
        f"Contact: {g['contact']}",
        f"Rule: {g['rule']}",
        f"Boundary: {g['note']}",
        f"Isolation Marker: {g['code']}",
    ]
    # Helvetica cannot render CJK glyphs; store CJK as unicode_escape while keeping
    # isolation codes / digits / ASCII intact for reliable PDF text extraction.
    safe_lines: list[str] = []
    for line in eng:
        buf: list[str] = []
        for ch in line:
            if ord(ch) < 128:
                buf.append(ch)
            else:
                buf.append(ch.encode("unicode_escape").decode("ascii"))
        safe_lines.append("".join(buf))

    parts = ["BT /F1 10 Tf"]
    for i, line in enumerate(safe_lines):
        safe = _pdf_escape(line)
        if i == 0:
            parts.append(f"40 740 Td ({safe}) Tj")
        else:
            parts.append(f"0 -14 Td ({safe}) Tj")
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1", errors="replace")

    objs = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        ),
        (
            f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
            + stream
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


def write_group(g: dict) -> None:
    folder = ROOT / g["id"]
    folder.mkdir(parents=True, exist_ok=True)
    stem = g["id"]
    (folder / f"{stem}.md").write_text(md_text(g), encoding="utf-8")
    (folder / f"{stem}.txt").write_text(txt_text(g), encoding="utf-8")
    docx = build_docx_bytes(g)
    (folder / f"{stem}.docx").write_bytes(docx)
    # Project parser accepts OOXML zip as .doc when header is PK
    (folder / f"{stem}.doc").write_bytes(docx)
    (folder / f"{stem}.pdf").write_bytes(build_pdf_bytes(g))


def main() -> None:
    for p in ROOT.iterdir():
        if p.name.startswith("_"):
            continue
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    f.unlink()
            for d in sorted(p.rglob("*"), reverse=True):
                if d.is_dir():
                    d.rmdir()
            p.rmdir()

    write_group(GROUP_A)
    write_group(GROUP_B)
    (ROOT / "README.md").write_text(
        "\n".join(
            [
                "# testdoc — 知识库隔离测试语料",
                "",
                "两组主题互不相关、组内事实自洽无矛盾，用于验证不同知识库检索隔离。",
                "",
                "| 分组 | 主题 | 隔离标记 | 路径 |",
                "|------|------|----------|------|",
                f"| A | {GROUP_A['title']} | `{GROUP_A['code']}` | `A_qinglan_tea/` |",
                f"| B | {GROUP_B['title']} | `{GROUP_B['code']}` | `B_xinggang_dive/` |",
                "",
                "每组均含全部上传支持格式：`pdf` / `doc` / `docx` / `txt` / `md`。",
                "",
                "建议用法：",
                "1. 知识库 A 只上传 `A_qinglan_tea/`；知识库 B 只上传 `B_xinggang_dive/`。",
                "2. 在 A 中问「星港」「3000 米」「SEA-XG-2024」不应命中 B。",
                "3. 在 B 中问「青岚龙井」「TEA-QL-2024」不应命中 A。",
                "",
                "说明：`.doc` 为可被本项目解析器识别的 OOXML 内容（与 `.docx` 同源），便于无 antiword 环境也能抽取。",
                "PDF 因内置字体限制，中文以 unicode_escape 形式写入，隔离标记与核心事实仍可被抽取。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and not p.name.startswith("_"))
    print("generated:")
    for f in files:
        print(" ", f)


if __name__ == "__main__":
    main()

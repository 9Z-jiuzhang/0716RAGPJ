"""文件类型默认分段与 Markdown 结构化切分测试。"""

from app.services.chunking import (
    adapt_rules_for_file_type,
    default_rules_for_file_type,
    recommended_split_mode_for_file_type,
    split_text,
)


def test_recommended_split_mode_by_file_type() -> None:
    """各支持类型应映射到最合适的默认分段方式。"""
    assert recommended_split_mode_for_file_type("md") == "markdown"
    assert recommended_split_mode_for_file_type(".MD") == "markdown"
    assert recommended_split_mode_for_file_type("txt") == "paragraph"
    assert recommended_split_mode_for_file_type("pdf") == "paragraph"
    assert recommended_split_mode_for_file_type("doc") == "paragraph"
    assert recommended_split_mode_for_file_type("docx") == "paragraph"
    assert recommended_split_mode_for_file_type("unknown") == "fixed"


def test_upload_defaults_always_follow_file_type() -> None:
    """上传默认规则始终按扩展名设 mode，不受其它规则影响。"""
    assert default_rules_for_file_type("md")["split_mode"] == "markdown"
    assert default_rules_for_file_type("pdf")["split_mode"] == "paragraph"
    assert default_rules_for_file_type("txt")["split_mode"] == "paragraph"
    assert default_rules_for_file_type(None)["split_mode"] == "fixed"
    assert default_rules_for_file_type("md")["chunk_size"] == 500


def test_markdown_file_uses_markdown_mode_by_default() -> None:
    """Markdown 文档遇到历史默认 fixed 时应自动升级为结构化切分。"""
    rules = adapt_rules_for_file_type(
        {"chunk_size": 500, "chunk_overlap": 50, "split_mode": "fixed"},
        "md",
    )

    assert rules["split_mode"] == "markdown"


def test_office_and_text_files_use_paragraph_by_default() -> None:
    """TXT / PDF / Word 在仍为 fixed 时自动改为按段落切分。"""
    for file_type in ("txt", "pdf", "doc", "docx", ".PDF"):
        rules = adapt_rules_for_file_type(
            {"chunk_size": 500, "chunk_overlap": 50, "split_mode": "fixed"},
            file_type,
        )
        assert rules["split_mode"] == "paragraph", file_type


def test_markdown_split_keeps_heading_hierarchy() -> None:
    """每个章节分段都应携带完整标题路径，便于后续检索理解上下文。"""
    text = """# 员工手册

总则内容。

## 年假制度

员工每年可申请年假。

### 申请流程

在系统中提交申请。
"""
    chunks = split_text(
        text,
        {"chunk_size": 200, "chunk_overlap": 0, "split_mode": "markdown"},
    )

    paths = [chunk.metadata.get("heading_path") for chunk in chunks]
    assert ["员工手册"] in paths
    assert ["员工手册", "年假制度"] in paths
    assert ["员工手册", "年假制度", "申请流程"] in paths
    assert all(chunk.metadata["split_mode"] == "markdown" for chunk in chunks)


def test_markdown_sibling_headings_do_not_nest() -> None:
    """同级标题应替换栈顶，而不是追加成父子关系。"""
    text = """### 手册

#### 1.总则

总则正文。

#### 2.员工守则

守则正文。
"""
    chunks = split_text(
        text,
        {"chunk_size": 500, "chunk_overlap": 0, "split_mode": "markdown"},
    )
    paths = [tuple(c.metadata.get("heading_path") or []) for c in chunks]
    assert ("手册", "1.总则") in paths
    assert ("手册", "2.员工守则") in paths
    assert ("手册", "1.总则", "2.员工守则") not in paths


def test_markdown_split_preserves_single_newline_lists() -> None:
    """单换行连接的长列表不得被静默丢弃（历史 bug：条款编号跳跃、总字数骤减）。"""
    items = "\n".join(f"（{i}）条款内容第{i}条，说明文字。" for i in range(1, 31))
    text = f"#### 2.员工守则\n\n**2.1仪容**\n{items}\n"
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
    assert "（1）" in joined
    assert "（15）" in joined
    assert "（30）" in joined
    # 允许 overlap 导致合计略大于原文，但不允许远小于原文
    assert sum(c.char_count for c in chunks) >= len(text) * 0.9


def test_markdown_split_does_not_break_fenced_code_block() -> None:
    """围栏代码块即使超过目标长度也必须保持起止围栏完整。"""
    text = """# 接口示例

以下为调用代码。

```python
def request_example():
    payload = {"question": "如何申请年假"}
    return payload
```
"""
    chunks = split_text(
        text,
        {"chunk_size": 40, "chunk_overlap": 0, "split_mode": "markdown"},
    )

    code_chunks = [chunk.content for chunk in chunks if "```python" in chunk.content]
    assert len(code_chunks) == 1
    assert code_chunks[0].startswith("```python")
    assert code_chunks[0].endswith("```")
    assert "return payload" in code_chunks[0]


def test_explicit_non_default_mode_is_preserved() -> None:
    """管理员明确选择 heading 等模式时，不应被文件类型适配覆盖。"""
    rules = adapt_rules_for_file_type(
        {"chunk_size": 500, "chunk_overlap": 0, "split_mode": "heading"},
        ".md",
    )

    assert rules["split_mode"] == "heading"


def test_explicit_sliding_on_pdf_is_preserved() -> None:
    """用户在重分段中显式选择 sliding 时，PDF 也不应被改回 paragraph。"""
    rules = adapt_rules_for_file_type(
        {"chunk_size": 300, "chunk_overlap": 40, "split_mode": "sliding"},
        "pdf",
    )
    assert rules["split_mode"] == "sliding"


def test_adapt_does_not_override_kb_inherited_paragraph_on_md() -> None:
    """历史文档若已是 paragraph，重分段时保留用户/历史选择（不因 md 强制改 markdown）。"""
    rules = adapt_rules_for_file_type(
        {"chunk_size": 500, "chunk_overlap": 50, "split_mode": "paragraph"},
        "md",
    )
    assert rules["split_mode"] == "paragraph"

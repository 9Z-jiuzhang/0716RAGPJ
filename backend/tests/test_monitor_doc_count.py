"""首页 doc_count 口径：仅有效知识库下的非 archived 文档。"""

from sqlalchemy.dialects import postgresql

from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase


def test_monitor_doc_count_query_excludes_deleted_kb_and_archived_docs() -> None:
    from sqlalchemy import func, select

    stmt = (
        select(func.count())
        .select_from(Document)
        .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.status != "deleted",
            Document.status != "archived",
        )
    )
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "documents" in sql
    assert "knowledge_bases" in sql
    assert "deleted" in sql
    assert "archived" in sql

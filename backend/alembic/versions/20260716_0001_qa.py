"""新增智能问答表，并为文档分段启用全文检索 tsvector。

Revision ID: 20260716_0001_qa
Revises:
Create Date: 2026-07-16

变更说明：
1. 创建 qa_sessions / qa_messages，支撑多用户会话隔离与历史回看；
2. 为 document_chunks 增加 STORED 生成列 content_tsv + GIN 索引；
3. 为 content 增加 pg_trgm GIN 索引，辅助关键词模糊匹配。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260716_0001_qa"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """升级：创建问答表结构并扩展全文检索能力。"""
    # ---------- 确保扩展可用（与 docker/postgres/init.sql 对齐） ----------
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ---------- 问答会话表（幂等：与 lifespan create_all 并存时跳过） ----------
    if "qa_sessions" not in existing_tables:
        op.create_table(
            "qa_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
            ),
            sa.Column("guest_id", sa.String(length=64), nullable=True, comment="访客匿名标识，注册用户会话为空"),
            sa.Column("title", sa.String(length=100), nullable=False, server_default="新会话", comment="会话标题"),
            sa.Column("summary", sa.Text(), nullable=True, comment="长期记忆摘要（超窗历史压缩结果）"),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="active",
                comment="active/expired/deleted",
            ),
            sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, comment="最后活跃时间"),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default="0", comment="消息条数"),
            sa.Column(
                "kb_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True, comment="关联知识库 ID"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("user_id IS NOT NULL OR guest_id IS NOT NULL", name="ck_qa_sessions_owner"),
            comment="智能问答会话",
        )
        op.create_index("ix_qa_sessions_user_id", "qa_sessions", ["user_id"])
        op.create_index("ix_qa_sessions_guest_id", "qa_sessions", ["guest_id"])
        op.create_index("ix_qa_sessions_status", "qa_sessions", ["status"])
        op.create_index("ix_qa_sessions_last_active_at", "qa_sessions", ["last_active_at"])
        op.create_index("ix_qa_sessions_user_last_active", "qa_sessions", ["user_id", "last_active_at"])
        op.create_index("ix_qa_sessions_guest_last_active", "qa_sessions", ["guest_id", "last_active_at"])

    # ---------- 问答消息表 ----------
    if "qa_messages" not in existing_tables:
        op.create_table(
            "qa_messages",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "session_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("qa_sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=20), nullable=False, comment="user/assistant/system"),
            sa.Column("content", sa.Text(), nullable=False, comment="消息正文"),
            sa.Column("citations", postgresql.JSON(astext_type=sa.Text()), nullable=True, comment="引用来源片段"),
            sa.Column(
                "retrieval_meta", postgresql.JSON(astext_type=sa.Text()), nullable=True, comment="检索与生成元数据"
            ),
            sa.Column("token_count", sa.Integer(), nullable=True, comment="大致 token 消耗"),
            sa.Column("request_id", sa.String(length=64), nullable=True, comment="请求追踪 ID"),
            sa.Column("strategy", sa.String(length=20), nullable=True, comment="检索策略"),
            sa.Column("latency_ms", sa.Integer(), nullable=True, comment="端到端耗时毫秒"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            comment="智能问答消息",
        )
        op.create_index("ix_qa_messages_session_id", "qa_messages", ["session_id"])
        op.create_index("ix_qa_messages_request_id", "qa_messages", ["request_id"])
        op.create_index("ix_qa_messages_session_created", "qa_messages", ["session_id", "created_at"])

    # ---------- document_chunks 全文检索列与索引 ----------
    # 刷新 inspector，避免前面建表后缓存过期
    inspector = sa.inspect(bind)
    if "document_chunks" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("document_chunks")}
        if "content_tsv" not in columns:
            # STORED 生成列：content 变更时自动刷新，无需应用层维护
            op.execute("""
                ALTER TABLE document_chunks
                ADD COLUMN content_tsv tsvector
                GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED
                """)
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("document_chunks")}
        if "ix_document_chunks_content_tsv" not in existing_indexes:
            op.execute("CREATE INDEX ix_document_chunks_content_tsv ON document_chunks USING GIN (content_tsv)")
        if "ix_document_chunks_content_trgm" not in existing_indexes:
            op.execute(
                "CREATE INDEX ix_document_chunks_content_trgm ON document_chunks USING GIN (content gin_trgm_ops)"
            )


def downgrade() -> None:
    """回滚：移除问答表与全文检索索引/列。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_chunks" in inspector.get_table_names():
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("document_chunks")}
        if "ix_document_chunks_content_trgm" in existing_indexes:
            op.drop_index("ix_document_chunks_content_trgm", table_name="document_chunks")
        if "ix_document_chunks_content_tsv" in existing_indexes:
            op.drop_index("ix_document_chunks_content_tsv", table_name="document_chunks")
        columns = {c["name"] for c in inspector.get_columns("document_chunks")}
        if "content_tsv" in columns:
            op.drop_column("document_chunks", "content_tsv")

    op.drop_index("ix_qa_messages_session_created", table_name="qa_messages")
    op.drop_index("ix_qa_messages_request_id", table_name="qa_messages")
    op.drop_index("ix_qa_messages_session_id", table_name="qa_messages")
    op.drop_table("qa_messages")

    op.drop_index("ix_qa_sessions_guest_last_active", table_name="qa_sessions")
    op.drop_index("ix_qa_sessions_user_last_active", table_name="qa_sessions")
    op.drop_index("ix_qa_sessions_last_active_at", table_name="qa_sessions")
    op.drop_index("ix_qa_sessions_status", table_name="qa_sessions")
    op.drop_index("ix_qa_sessions_guest_id", table_name="qa_sessions")
    op.drop_index("ix_qa_sessions_user_id", table_name="qa_sessions")
    op.drop_table("qa_sessions")

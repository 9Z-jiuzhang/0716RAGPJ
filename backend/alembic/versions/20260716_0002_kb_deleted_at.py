"""add knowledge_bases.deleted_at for soft delete

Revision ID: 20260716_0002_kb
Revises: 20260716_0001_qa
Create Date: 2026-07-16
"""

from alembic import op

revision = "20260716_0002_kb"
down_revision = "20260716_0001_qa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_name_active
        ON knowledge_bases (name)
        WHERE deleted_at IS NULL
        """
    )
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS raw_text TEXT NULL")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS normalized_text TEXT NULL")
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS segment_rules JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_version VARCHAR(64) NULL")
    op.execute("ALTER TABLE index_versions ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_kb_name_active")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS raw_text")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS normalized_text")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS segment_rules")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS index_version")
    op.execute("ALTER TABLE index_versions DROP COLUMN IF EXISTS is_current")

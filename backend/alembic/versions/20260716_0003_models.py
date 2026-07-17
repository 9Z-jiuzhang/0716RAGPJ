"""add model_configs and related schema patches

Revision ID: 20260716_0003_models
Revises: 20260716_0002_kb
Create Date: 2026-07-16
"""

from alembic import op

revision = "20260716_0003_models"
down_revision = "20260716_0002_kb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS model_configs (
          id UUID PRIMARY KEY,
          name VARCHAR(100) NOT NULL,
          model_type VARCHAR(20) NOT NULL,
          provider VARCHAR(50) NOT NULL,
          model_name VARCHAR(200) NOT NULL,
          base_url VARCHAR(500) NULL,
          is_default BOOLEAN NOT NULL DEFAULT FALSE,
          is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
          config JSONB NOT NULL DEFAULT '{}'::jsonb,
          timeout_seconds INTEGER NOT NULL DEFAULT 60,
          api_key_env VARCHAR(100) NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_model_configs_model_type ON model_configs (model_type)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_configs")

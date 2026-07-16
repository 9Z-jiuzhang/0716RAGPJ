"""异步 PostgreSQL 会话管理。"""
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """每个请求独立获取并关闭数据库会话。"""
    async with SessionLocal() as session:
        yield session


AsyncSessionLocal = SessionLocal


async def ensure_schema_patches() -> None:
    """
    对已有库补齐 create_all 无法自动 ALTER 的列（幂等）。

    本地/CI 早期用 create_all 建表后模型演进时，避免缺列导致 500。
    """
    statements = [
        "ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_name_active
        ON knowledge_bases (name)
        WHERE deleted_at IS NULL
        """,
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64) NULL",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS raw_text TEXT NULL",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS normalized_text TEXT NULL",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS segment_rules JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_version VARCHAR(64) NULL",
        "ALTER TABLE index_versions ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT FALSE",
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='document_chunks' AND column_name='content_tsv'
          ) THEN
            ALTER TABLE document_chunks
              ADD COLUMN content_tsv tsvector
              GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED;
          END IF;
        END $$;
        """,
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_tsv ON document_chunks USING gin (content_tsv)",
        """
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
        """,
        "CREATE INDEX IF NOT EXISTS ix_model_configs_model_type ON model_configs (model_type)",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))

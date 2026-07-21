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


async def ensure_postgres_extensions() -> None:
    """
    安装业务所需扩展（幂等）。

    CI 的 Postgres service 不会执行 docker/postgres/init.sql，
    必须在 create_all 之前装好 pg_trgm，否则 gin_trgm_ops 索引会失败。
    """
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))


async def ensure_schema_patches() -> None:
    """
    对已有库补齐 create_all 无法自动 ALTER 的列（幂等）。

    须在 create_all 之后调用。
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
        "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 100",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(50) NULL",
        "ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS department VARCHAR(50) NULL",
        # 快照表：旧库可能缺统计/分段规则列（create_all 不会 ALTER）
        "ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS document_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS segment_rules JSONB NOT NULL DEFAULT '{}'::jsonb",
        # 向量化任务表：旧库缺 TimestampMixin.updated_at
        "ALTER TABLE vectorize_tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NULL",
        "UPDATE vectorize_tasks SET updated_at = COALESCE(updated_at, created_at, NOW()) WHERE updated_at IS NULL",
        "ALTER TABLE test_questions ADD COLUMN IF NOT EXISTS expected_answer TEXT NULL",
        "ALTER TABLE test_questions ADD COLUMN IF NOT EXISTS context TEXT NULL",
        """
        DO $$ BEGIN
          ALTER TABLE vectorize_tasks
            ALTER COLUMN updated_at SET DEFAULT NOW();
        EXCEPTION WHEN others THEN NULL;
        END $$;
        """,
        """
        DO $$ BEGIN
          ALTER TABLE vectorize_tasks
            ALTER COLUMN updated_at SET NOT NULL;
        EXCEPTION WHEN others THEN NULL;
        END $$;
        """,
        """
        CREATE TABLE IF NOT EXISTS departments (
          id UUID PRIMARY KEY,
          code VARCHAR(50) NOT NULL UNIQUE,
          name VARCHAR(100) NOT NULL,
          description TEXT NULL,
          is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_departments_code ON departments (code)",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))

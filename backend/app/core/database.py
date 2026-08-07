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
        "ALTER TABLE guard_blocked_events ADD COLUMN IF NOT EXISTS actor_label VARCHAR(100) NOT NULL DEFAULT '访客'",
        "ALTER TABLE guard_blocked_events ADD COLUMN IF NOT EXISTS client_ip VARCHAR(64) NULL",
        "CREATE INDEX IF NOT EXISTS ix_guard_blocked_events_client_ip ON guard_blocked_events (client_ip)",
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
        """
        CREATE TABLE IF NOT EXISTS kb_departments (
          id UUID PRIMARY KEY,
          kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
          department_code VARCHAR(50) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          CONSTRAINT uq_kb_departments_kb_code UNIQUE (kb_id, department_code)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_kb_departments_kb_id ON kb_departments (kb_id)",
        "CREATE INDEX IF NOT EXISTS ix_kb_departments_department_code ON kb_departments (department_code)",
        # 问答 strategy 需容纳 route/transform 等短路径标识
        "ALTER TABLE qa_messages ALTER COLUMN strategy TYPE VARCHAR(64)",
        # 六维优化：问答事件 / 反馈 / 主题簇 / 模型发布版本
        """
        CREATE TABLE IF NOT EXISTS qa_request_events (
          id UUID PRIMARY KEY,
          request_id VARCHAR(64) NOT NULL,
          trace_id VARCHAR(64) NULL,
          conversation_id UUID NULL,
          message_id UUID NULL,
          actor_hash VARCHAR(128) NULL,
          tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
          role_ids JSONB NULL,
          question_hash VARCHAR(64) NULL,
          question_preview VARCHAR(240) NULL,
          route_intent VARCHAR(64) NULL,
          route_confidence DOUBLE PRECISION NULL,
          should_retrieve BOOLEAN NULL,
          top_k INTEGER NULL,
          rewrite_enabled BOOLEAN NULL,
          cache_level VARCHAR(16) NULL,
          cache_hit_id VARCHAR(64) NULL,
          normalized_similarity DOUBLE PRECISION NULL,
          miss_reason VARCHAR(128) NULL,
          retrieval_hit_count INTEGER NULL,
          citation_count INTEGER NULL,
          model_snapshot_id VARCHAR(64) NULL,
          latency_ms INTEGER NULL,
          result_status VARCHAR(32) NOT NULL DEFAULT 'ok',
          error_code VARCHAR(64) NULL,
          detail JSONB NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_qa_request_events_request_id ON qa_request_events (request_id)",
        "CREATE INDEX IF NOT EXISTS ix_qa_request_events_created_at ON qa_request_events (created_at)",
        """
        CREATE TABLE IF NOT EXISTS qa_feedback_events (
          id UUID PRIMARY KEY,
          message_id UUID NOT NULL,
          actor_hash VARCHAR(128) NOT NULL,
          rating VARCHAR(16) NOT NULL,
          reason VARCHAR(64) NULL,
          comment TEXT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          CONSTRAINT uq_qa_feedback_message_actor UNIQUE (message_id, actor_hash)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS qa_topic_clusters (
          id UUID PRIMARY KEY,
          name VARCHAR(200) NOT NULL,
          keywords JSONB NULL,
          representative_question TEXT NULL,
          sample_count INTEGER NOT NULL DEFAULT 0,
          embedding_model_version VARCHAR(100) NULL,
          cluster_version VARCHAR(64) NOT NULL DEFAULT 'v1',
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS model_config_versions (
          id UUID PRIMARY KEY,
          model_id UUID NOT NULL,
          version VARCHAR(64) NOT NULL,
          model_type VARCHAR(32) NOT NULL,
          provider VARCHAR(50) NOT NULL,
          model_name VARCHAR(200) NOT NULL,
          params JSONB NOT NULL DEFAULT '{}'::jsonb,
          is_published BOOLEAN NOT NULL DEFAULT TRUE,
          published_by UUID NULL,
          published_at TIMESTAMPTZ NULL,
          note VARCHAR(500) NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_model_config_versions_model_id ON model_config_versions (model_id)",
        "ALTER TABLE role_cached_questions ADD COLUMN IF NOT EXISTS matching_mode VARCHAR(32) NOT NULL DEFAULT 'exact'",
        "ALTER TABLE role_cached_questions ADD COLUMN IF NOT EXISTS quality_score DOUBLE PRECISION NULL",
        "ALTER TABLE role_cached_questions ADD COLUMN IF NOT EXISTS observe_only BOOLEAN NOT NULL DEFAULT FALSE",
        # 外部数据源 / 开放接口：文档来源字段
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_type VARCHAR(32) NOT NULL DEFAULT 'upload'",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
        # Wave1：仅旧默认 rewrite=true 且未开启扩展/HyDE 的单例配置迁到关闭
        """
        UPDATE query_processing_configs
        SET rewrite_enabled = FALSE, updated_at = NOW()
        WHERE config_key = 'default'
          AND rewrite_enabled = TRUE
          AND expansion_enabled = FALSE
          AND hyde_enabled = FALSE
          AND expansion_count = 1
        """,
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))

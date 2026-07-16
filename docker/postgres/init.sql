-- PostgreSQL 初始化脚本
-- 在首次创建数据卷时由 docker-entrypoint-initdb.d 执行
--
-- 说明：
-- 1. 业务表优先由 Alembic 迁移或应用 lifespan 中的 create_all 创建；
-- 2. 此处仅安装扩展与预置全文检索相关能力，避免依赖镜像内未打包的中文分词插件；
-- 3. 智能问答模块（5.6）依赖 uuid-ossp（UUID）与 pg_trgm（模糊匹配辅助）。

-- 扩展：UUID 与全文检索辅助
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ---------------------------------------------------------------------------
-- 全文检索约定（document_chunks.content_tsv）
-- ---------------------------------------------------------------------------
-- 迁移脚本 / ORM 会为 document_chunks 增加：
--   content_tsv tsvector GENERATED ALWAYS AS (
--     to_tsvector('simple', coalesce(content, ''))
--   ) STORED
-- 以及：
--   GIN (content_tsv)          -- @@ / ts_rank 主路径
--   GIN (content gin_trgm_ops) -- 模糊关键词辅助
--
-- 使用 simple 配置的原因：默认镜像不含 zhparser，simple 按空白与标点切词，
-- 对法规条文编号、英文术语、空格分隔关键词效果稳定。
-- 若后续自行安装中文分词扩展，可将 Generated 表达式改为对应 text search config。
--
-- 典型查询示例（应用层实现，此处仅作文档）：
--   SELECT id, ts_rank_cd(content_tsv, query) AS score
--   FROM document_chunks,
--        plainto_tsquery('simple', '权限 配置') AS query
--   WHERE is_enabled = true
--     AND kb_id = ANY(:authorized_kb_ids)
--     AND content_tsv @@ query
--   ORDER BY score DESC
--   LIMIT :top_k;

SELECT 1;

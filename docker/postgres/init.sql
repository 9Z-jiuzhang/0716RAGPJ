-- PostgreSQL 初始化脚本
-- 在首次创建数据卷时由 docker-entrypoint-initdb.d 执行

-- 扩展：UUID 与全文检索
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- 说明：业务表由 Alembic 迁移创建。
-- 以下为内置角色种子数据占位（表创建后由迁移或启动脚本插入）：
--   admin     — 系统管理员
--   user      — 注册用户
--   kb_admin  — 知识库维护员
--
-- INSERT INTO roles (id, name, description, is_builtin, created_at, updated_at) VALUES
--   (uuid_generate_v4(), 'admin', '系统管理员', true, NOW(), NOW()),
--   (uuid_generate_v4(), 'user', '注册用户', true, NOW(), NOW()),
--   (uuid_generate_v4(), 'kb_admin', '知识库维护员', true, NOW(), NOW());

SELECT 1;

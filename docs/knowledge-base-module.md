# 知识库管理模块 — 技术文档

> 版本：2.1.0
> 日期：2026-07-16
> 状态：框架契约阶段

---

## 1. 模块简介

知识库管理模块是 AI 知识库 RAG 平台的核心模块之一，负责知识库的创建、编辑、删除、权限配置，以及文档的上传、预处理、分段和向量化等功能。

该模块基于产品手册 `5.4 知识库管理` 章节设计，实现了以下核心能力：

- 知识库 CRUD 操作（支持软删除）
- 文档上传与处理流水线
- 分段规则配置与重新分段
- 异步向量化任务管理
- 索引版本原子切换
- 知识库权限精细化控制

---

## 2. 功能列表

依据产品手册 `5.4.1` 节，本模块包含以下功能：

| 功能 | 说明 | API 端点 |
|------|------|----------|
| 创建知识库 | 设置名称、类型、标签、简介、可见性、Embedding 模型等 | `POST /knowledge-bases` |
| 编辑知识库 | 修改知识库元信息 | `PUT /knowledge-bases/{id}` |
| 删除知识库 | 软删除（可恢复）或物理删除 | `DELETE /knowledge-bases/{id}` |
| 知识库列表 | 分页展示，支持按名称/类型/标签筛选 | `GET /knowledge-bases` |
| 知识库详情 | 查看文档数量、分段数量、最近构建时间、构建状态等 | `GET /knowledge-bases/{id}` |
| 权限配置 | 配置哪些用户/角色可以访问/管理该知识库 | `PUT /knowledge-bases/{id}/permissions` |
| 重新向量化 | 按修改后的分段规则对知识库内所有文档重新向量化 | `POST /knowledge-bases/{id}/re-vectorize` |
| 向量化进度 | 实时展示向量化任务进度 | `GET /knowledge-bases/{id}/vectorize-status` |
| 文档上传 | 上传 PDF、DOC、DOCX、TXT、Markdown 文档 | `POST /knowledge-bases/{kb_id}/documents/upload` |
| 文档列表 | 展示知识库下所有文档，支持分页和搜索 | `GET /knowledge-bases/{kb_id}/documents` |
| 文档删除 | 删除文档及其关联的向量数据 | `DELETE /knowledge-bases/{kb_id}/documents/{id}` |
| 分段规则配置 | 修改文档的分段规则 | `PUT /knowledge-bases/{kb_id}/documents/{id}/segment-rules` |
| 重新分段 | 修改规则后对单个文档重新分段和向量化 | `POST /knowledge-bases/{kb_id}/documents/{id}/re-segment` |
| 文档规范化 | 去除多余空格/换行、统一编码等处理 | `POST /knowledge-bases/{kb_id}/documents/{id}/normalize` |
| 分段预览 | 查看文档的所有分段 | `GET /knowledge-bases/{kb_id}/documents/{id}/chunks` |
| 编辑分段 | 编辑/禁用单个分段 | `PUT /knowledge-bases/{kb_id}/documents/{id}/chunks/{chunk_id}` |

---

## 3. 数据表结构说明

### 3.1 核心表

#### knowledge_bases

依据产品手册 `5.4.2` 节定义：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 唯一标识 |
| name | string (255) | 知识库名称 |
| type | string (50) | 类型（technical/product/faq/general） |
| tags | JSON | 标签列表 |
| description | text | 简介/描述 |
| visibility | string (20) | 可见性（public/restricted） |
| embedding_model | string (100) | 使用的 Embedding 模型名称 |
| chunk_size | int | 默认分段大小（字符数），默认 500 |
| chunk_overlap | int | 默认分段重叠（字符数），默认 50 |
| status | string (20) | 状态（active/vectorizing/archived/deleted） |
| current_index_version | string (50) | 当前索引版本号 |
| creator_id | UUID | 创建者 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 最后更新时间 |
| deleted_at | datetime | 软删除时间（新增） |

#### documents

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 唯一标识 |
| kb_id | UUID | 所属知识库 |
| filename | string (512) | 原始文件名 |
| file_type | string (20) | 文件类型 |
| file_size | int | 文件大小（字节） |
| file_path | string (1024) | MinIO 对象存储路径 |
| chunk_count | int | 分段数量 |
| status | string (20) | 状态 |
| error_message | text | 处理失败原因 |
| creator_id | UUID | 上传者用户 ID |
| created_at | datetime | 上传时间 |
| updated_at | datetime | 最后更新时间 |

#### document_chunks

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 唯一标识 |
| document_id | UUID | 所属文档 |
| chunk_index | int | 分段序号 |
| content | text | 分段内容 |
| metadata | JSON | 元数据 |
| is_active | boolean | 是否启用 |
| index_version | string (50) | 索引版本 |
| created_at | datetime | 创建时间 |

### 3.2 关联表

| 表名 | 说明 |
|------|------|
| kb_permissions | 知识库权限表（用户/角色 -> 知识库 -> 权限标识） |
| index_versions | 索引版本表 |
| snapshots | 快照表 |
| snapshot_documents | 快照-文档关联表 |
| audit_logs | 操作审计日志表 |
| vectorize_tasks | 向量化任务表 |

---

## 4. API 端点汇总

### 4.1 知识库管理

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/v1/knowledge-bases` | 创建知识库 | `kb:write` |
| GET | `/api/v1/knowledge-bases` | 知识库列表（分页） | 需登录 |
| GET | `/api/v1/knowledge-bases/{id}` | 知识库详情 | `kb:read` |
| PUT | `/api/v1/knowledge-bases/{id}` | 修改知识库元信息 | `kb:write` |
| DELETE | `/api/v1/knowledge-bases/{id}` | 删除知识库 | `kb:write` |
| POST | `/api/v1/knowledge-bases/{id}/re-vectorize` | 重新向量化 | `kb:vectorize` |
| GET | `/api/v1/knowledge-bases/{id}/vectorize-status` | 向量化进度查询 | `kb:vectorize` |
| PUT | `/api/v1/knowledge-bases/{id}/permissions` | 配置知识库权限 | `kb:write` |

### 4.2 文档管理

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/v1/knowledge-bases/{kb_id}/documents` | 文档列表（分页+搜索） | `doc:read` |
| POST | `/api/v1/knowledge-bases/{kb_id}/documents/upload` | 上传文档 | `kb:upload` |
| GET | `/api/v1/knowledge-bases/{kb_id}/documents/{id}` | 文档详情 | `doc:read` |
| DELETE | `/api/v1/knowledge-bases/{kb_id}/documents/{id}` | 删除文档 | `doc:write` |
| PUT | `/api/v1/knowledge-bases/{kb_id}/documents/{id}/segment-rules` | 修改分段规则 | `doc:segment` |
| POST | `/api/v1/knowledge-bases/{kb_id}/documents/{id}/re-segment` | 重新分段并向量化 | `doc:segment` |
| POST | `/api/v1/knowledge-bases/{kb_id}/documents/{id}/normalize` | 文档规范化 | `doc:write` |
| GET | `/api/v1/knowledge-bases/{kb_id}/documents/{id}/chunks` | 分段预览 | `doc:read` |
| PUT | `/api/v1/knowledge-bases/{kb_id}/documents/{id}/chunks/{chunk_id}` | 编辑/禁用单个分段 | `doc:segment` |

### 4.3 统一响应格式

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## 5. 异步任务流程说明

### 5.1 重新向量化流程

依据产品手册 `5.4.3` 节：

```
管理员修改分段规则 -> 点击"重新向量化"
  -> 创建变更快照
  -> 后端创建异步任务 -> 更新知识库状态为 "vectorizing"
  -> 逐文档按新规则分段 -> 重新生成 Embedding -> 写入新索引版本
  -> 校验成功后以原子方式切换当前索引版本
  -> 完成后更新状态为 "active"，记录操作日志
  -> 失败时保留上一个可用版本
```

### 5.2 任务状态流转

| 状态 | 说明 |
|------|------|
| pending | 任务已创建，等待执行 |
| running | 任务执行中 |
| completed | 任务完成 |
| failed | 任务失败 |

### 5.3 索引版本原子切换机制

`IndexSwitchService.switch_index_version()` 方法使用 PostgreSQL 事务和行锁确保原子性：

1. 开始嵌套事务
2. 使用 `SELECT ... FOR UPDATE` 锁定 `knowledge_bases` 表中对应行
3. 将旧版本的 `index_versions.is_current` 更新为 `False`
4. 将新版本的 `index_versions.is_current` 更新为 `True`
5. 更新 `knowledge_bases.current_index_version`
6. 提交事务

**关键约束：**
- 构建应以后台任务执行，不能中断在线问答
- 重建成功后以原子方式切换当前索引版本
- 失败时保留上一个可用版本
- 在线旧索引在新版本发布前仍可用

---

## 6. 环境变量依赖说明

本模块依赖以下环境变量：

### 6.1 数据库

```ini
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=knowledge_base
POSTGRES_USER=kb_user
POSTGRES_PASSWORD=<密码>
```

### 6.2 Redis（任务队列）

```ini
REDIS_HOST=redis
REDIS_PORT=6379
```

### 6.3 对象存储（MinIO）

```ini
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=<key>
MINIO_SECRET_KEY=<key>
MINIO_BUCKET=knowledge-base-docs
```

### 6.4 Embedding 模型

```ini
EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=<key>
EMBEDDING_MODEL_NAME=text-embedding-3-small
EMBEDDING_API_BASE=<自定义 API 地址>
```

### 6.5 JWT 认证

```ini
JWT_SECRET_KEY=<随机生成>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

---

## 7. 本地开发启动步骤

### 7.1 环境准备

1. 安装 Docker 和 Docker Compose
2. 复制 `.env.example` 为 `.env`，填写必要的配置项

### 7.2 启动服务

```bash
cd 0716RAGPJ
docker-compose up -d
```

### 7.3 执行数据库迁移

```bash
docker-compose exec api alembic upgrade head
```

### 7.4 访问服务

- 后端 API：`http://localhost:8000/api/v1`
- 前端管理页面：`http://localhost:8080/admin/knowledge-bases`

### 7.5 开发模式

后端支持热重载，代码修改后自动生效：

```bash
docker-compose up api
```

---

## 8. 常见问题与注意事项

### 8.1 软删除恢复

知识库支持软删除，删除时 `deleted_at` 字段被设置为当前时间，数据并未真正删除。如需恢复软删除的知识库，需在数据库层面操作，将 `deleted_at` 设为 `NULL`。

### 8.2 索引版本保留

每次重新向量化会创建新的索引版本，旧版本保留在 `index_versions` 表中。通过 `is_current` 字段标识当前使用的版本，支持回退到历史版本。

### 8.3 权限生效机制

权限校验在后端严格实施，前端仅做 UI 隐藏，不能作为真实的权限控制。权限检查时，系统按以下优先级合并用户的权限：

1. 用户直接绑定的知识库权限
2. 用户所属角色的知识库权限
3. 两项取并集（宽松策略，任一来源授权即放行）

### 8.4 向量化任务并发

同一知识库同时只能有一个向量化任务执行，重复触发会被忽略。任务状态持久化至 PostgreSQL，支持进度查询和失败重试。

### 8.5 文件格式限制

首期支持 PDF、DOC、DOCX、TXT、Markdown 格式。CSV、XLSX、PPTX 为 P1 预留格式，数据库枚举已包含但上传接口首期拒绝。

### 8.6 审计日志

所有异步任务的关键操作（创建、更新、删除、向量化、分段等）必须记录到 `audit_logs` 表，包含操作者、时间、对象、前后版本、请求标识、结果与失败原因。
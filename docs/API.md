# AI 知识库 RAG 平台 — 接口文档（中文）

> 版本：`2.1.0`　与 [`openapi.json`](./openapi.json) 同步  
> 本文档逐接口详解路径、方法、鉴权、请求/响应字段与约束，字段名与类型取自 `backend/app/schemas/*` 与路由签名。  
> 契约说明见 [`CONTRACT.md`](./CONTRACT.md)。

---

## 目录

1. [总则](#1-总则)
2. [权限模型](#2-权限模型)
3. [认证与用户中心 `/auth`](#3-认证与用户中心-auth)
4. [用户管理 `/users`](#4-用户管理-users)
5. [角色与权限 `/roles`](#5-角色与权限-roles)
6. [部门管理 `/departments`](#6-部门管理-departments)
7. [大模型管理 `/models`](#7-大模型管理-models)
8. [知识库管理 `/knowledge-bases`](#8-知识库管理-knowledge-bases)
9. [文档管理 `/knowledge-bases/{kb_id}/documents`](#9-文档管理-knowledge-baseskb_iddocuments)
10. [智能问答 `/qa`](#10-智能问答-qa)
11. [命中率测试 `/hit-tests`](#11-命中率测试-hit-tests)
12. [快照管理 `/knowledge-bases/{kb_id}/snapshots`](#12-快照管理-knowledge-baseskb_idsnapshots)
13. [审计日志 `/audit`](#13-审计日志-audit)
14. [系统监控 `/monitor`](#14-系统监控-monitor)
15. [Query 预处理 `/query-processing`](#15-query-预处理-query-processing)
16. [角色缓存 `/role-caches`](#16-角色缓存-role-caches)
17. [RAGAS 评估 `/ragas`](#17-ragas-评估-ragas)
18. [联调检查清单](#18-联调检查清单)
19. [变更记录](#19-变更记录)

---

## 1. 总则

### 1.1 Base URL

| 环境 | Base URL |
|------|----------|
| 本地 Docker 统一入口（本仓库默认映射） | `http://localhost:18080/api/v1` |
| 云端 HTTPS 域名 | `https://<你的域名>/api/v1` |
| 直连 API（仅调试） | `http://localhost:18000/api/v1` |

下文路径均相对 Base URL。云端部署步骤见 [`CLOUD_DEPLOY.md`](./CLOUD_DEPLOY.md)。

### 1.2 认证方式

```http
Authorization: Bearer <access_token>
```

- 登录返回 `access_token`（默认 30 分钟）与 `refresh_token`（默认 7 天）。
- 除标注「公开」或「可选认证」外，接口均需有效 Bearer Token。
- Token 无效/过期 → `401`；已登录但被禁用或无权限 → `403`。
- 客户端可携带 `X-Request-Id`（请求追踪）；问答接口可携带 `X-Guest-Id`（访客标识，≤64 字符）。

### 1.3 统一响应包装

除 **SSE 流式**、**CSV 导出**、**Prometheus 指标** 外，所有 JSON 接口统一为：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 业务码，`0` 成功；非 0 业务失败（可与 HTTP 状态码并存） |
| `message` | string | 人类可读提示 |
| `data` | object/array/null | 业务载荷 |
| `request_id` | string(UUID) | 请求追踪 ID，前后端日志对齐 |

> 实现层存在两个等价包装模型（`BaseResponse` 与 `APIResponse[T]`），对外 JSON 结构一致；文档模块返回相同形状的 plain dict。

### 1.4 分页约定

**请求查询参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 从 1 开始 |
| `page_size` | int | 20（部门列表 50、会话消息 50） | 范围 1–100 |

**响应 `data` 结构**：

```json
{ "items": [], "total": 100, "page": 1, "page_size": 20 }
```

### 1.5 常见 HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 202 | 异步任务已受理 |
| 400 | 参数/业务错误 |
| 401 | 未登录或 Token 无效/过期 |
| 403 | 已登录但无权限，或用户被禁用 |
| 404 | 资源不存在或不可见 |
| 409 | 冲突（如用户名/邮箱已存在、内置角色不可删、角色仍被绑定） |
| 413 | 上传文件过大（>100MB） |
| 422 | 字段校验失败 |
| 500 | 服务器错误 |
| 502 | 上游依赖失败（如 Langfuse 用量查询） |

### 1.6 访客端 vs 管理端

| 端 | 典型接口 | 说明 |
|----|----------|------|
| 访客端 | `/auth/*`、`/qa/ask` | 未登录仅可检索 `department=GUEST`（访客专用）的知识库 |
| 管理端 | `/users`、`/roles`、`/departments`、`/knowledge-bases`、`/hit-tests`、`/ragas`、`/role-caches`、`/query-processing`、`/audit`、`/monitor/*` 等 | 需对应权限标识 |

机器可读契约见 [`openapi.json`](./openapi.json)；第三方接入见 [`API_INTEGRATION_GUIDE.md`](./API_INTEGRATION_GUIDE.md)；云端部署见 [`CLOUD_DEPLOY.md`](./CLOUD_DEPLOY.md)。

---

## 2. 权限模型

权限判定须**同时满足**：

1. 用户角色拥有功能权限标识（如 `kb:read`）；
2. 若为知识库级操作，还须通过**部门驱动的访问控制**或 `KBPermission` 授权（详见 README 的访问控制一节）。

### 2.1 权限标识清单

| 权限标识 | 说明 | 作用域 |
|----------|------|--------|
| `user:read` / `user:write` | 用户查看 / 创建改删启停与角色绑定 | 全局 |
| `role:read` / `role:write` | 角色查看 / 创建修改删除 | 全局；**配置权限**另需超级管理员身份 |
| `department:read` / `department:write` | 部门查看 / 维护 | 全局 |
| `kb:read` / `kb:write` | 知识库查看 / 创建修改删除 | 读可按库隔离；写为全局 |
| `kb:upload` | 上传文档 | 可按库隔离 |
| `kb:vectorize` | 触发重向量化 / 查进度 | 可按库隔离 |
| `doc:read` / `doc:write` | 文档查看 / 修改删除规范化 | 可按库隔离 |
| `doc:segment` | 分段规则、重分段、编辑分段 | 可按库隔离 |
| `qa:ask` | 问答 | 全局功能；检索范围仍受可见性限制 |
| `test:read` / `test:write` | 命中率测试查看 / 执行 | 全局（范围受库授权） |
| `snapshot:read` / `snapshot:write` / `snapshot:restore` | 快照查看 / 创建删除 / 回退 | 可按库隔离 |
| `model:read` / `model:write` | 模型配置查看 / 写入 | 全局 |
| `system:read` | 系统统计 | 全局 |
| `audit:read` | 审计日志 | 全局 |

> `*` 与 `admin:*` 为通配权限，`super_admin` 角色直通所有校验。KB 级 `kb:admin` 授权可满足该库任意权限检查。

### 2.2 内置角色（种子数据）

| 角色 | 说明 |
|------|------|
| `super_admin` | 全量能力（含 `model:write`、角色权限配置），权限码 `*` |
| `admin` | 管理用户/部门/知识库/文档/快照/审计/系统；含 `role:read`，**不含** `role:write`、`model:write`；不可操作超管、不可配置角色权限 |
| `staff` | 问答 + 授权范围内知识库上传/向量化/文档/分段/测试/快照 |
| `guest` | 仅 `qa:ask` + `kb:read`（GUEST 部门知识库）；注册/管理员创建用户默认角色 |

角色等级（仅可管理等级**严格低于**自己的用户）：`super_admin(100) > admin(50) > staff(20) > guest(10)`。

内置角色不可删除或改名。启动时旧库中的 `user` 会迁移至 `guest`、`kb_admin` 会迁移至 `staff` 后删除。

---

## 3. 认证与用户中心 `/auth`

所有响应统一包装，`data` 为对应载荷。

### 3.1 用户注册

- `POST /auth/register` — **公开** — 成功 `201`

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| username | string | 是 | 3–50，唯一 |
| password | string | 是 | 8–128（须 HTTPS 传输） |
| email | EmailStr | 是 | 唯一 |
| nickname | string | 否 | ≤100 |

响应 `data`：用户对象（见 [3.4](#34-当前用户信息)）。默认绑定 **`guest`** 角色。用户名/邮箱冲突 → `409`。云端可设 `AUTH_REGISTER_ENABLED=false` 关闭本接口（返回 `403`）。

### 3.2 用户登录

- `POST /auth/login` — **公开** — 请求：`username`、`password`
- **统一入口**：访客 / 员工 / 管理员同一接口；前端根据 `landing` 分流。

响应 `data`（`LoginResponse`，在 Token 基础上扩展）：

| 字段 | 说明 |
|------|------|
| access_token | 访问 JWT |
| refresh_token | 刷新 JWT |
| token_type | 固定 `bearer` |
| expires_in | access 有效秒数 |
| user | 用户对象（同 [3.4](#34-当前用户信息)） |
| landing | `admin`=管理端，`app`=问答端 |
| landing_href | 前端跳转，如 `/admin/` 或 `/#/chat` |

凭证错误 → `401`（`detail`/`message` 为「用户名或密码错误」）；用户被禁用 → `403`。

### 3.3 刷新 Token

- `POST /auth/refresh` — **公开（需有效 refresh）** — 请求：`{ "refresh_token": "..." }` — 返回新的 Token 对。

### 3.4 当前用户信息

- `GET /auth/me` — 需登录

响应 `data`（`UserResponse`）：`id`、`username`、`email`、`nickname`、`status`、`roles[]`、`role_labels[]`、`permissions[]`、`department`、`is_super_admin`、`created_at`、`last_login_at`。前端据此渲染菜单/按钮（**不替代后端鉴权**）。

### 3.5 修改本人资料

- `PUT /auth/me` — 需登录 — 请求（`UserUpdateRequest`）：`nickname?`(≤100)、`email?`、`department?`(≤50) — 返回更新后的用户。

### 3.6 修改本人密码

- `POST /auth/change-password` — 需登录

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| old_password | string | 是 | 1–128 |
| new_password | string | 是 | 8–128 |
| confirm_password | string | 是 | 须与 `new_password` 一致 |

成功 `data`：`{ "changed": true }`。

约束：

- 固定超管账号（`super`）→ `403`（仅允许通过 `.env` 的 `SUPER_ADMIN_PASSWORD` 维护）；
- 原密码错误 / 新旧相同 / 两次确认不一致 → `400`。

---

## 4. 用户管理 `/users`

需 `user:read` / `user:write`；写操作记审计。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/users` | `user:write` | 创建用户（`201`）；未指定角色时默认 `guest` |
| GET | `/users` | `user:read` | 分页；Query：`keyword`、`status`(active\|disabled\|pending) |
| GET | `/users/{id}` | `user:read` | 详情 |
| PUT | `/users/{id}` | `user:write` | 改昵称/邮箱/部门 |
| DELETE | `/users/{id}` | `user:write` | 删除等级严格低于自己的用户；成功 `data: {deleted:true}` |
| PATCH | `/users/{id}/status` | `user:write` | Body：`status`(active\|disabled\|pending) |
| PUT | `/users/{id}/roles` | `user:write` | Body：`role_ids[]` 全量覆盖 |

**创建用户请求**（`AdminCreateUserRequest`）：`username`(3–50)、`password`(8–128)、`email`、`nickname?`(≤100)、`role_ids[]`（默认空 → `guest`）。

**等级与分配约束**：

- 启停 / 删 / 改角色：仅可操作权限等级**严格低于**自己的用户；不可操作自己。
- 普通管理员不可将他人设为 `admin` / `super_admin`；超级管理员可分配任意角色。
- 冲突 → `409`。

---

## 5. 角色与权限 `/roles`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/roles` | `role:read` | 分页列表 |
| GET | `/roles/permissions` | `role:read` | 权限清单：`data` 为 `[{code, name, scope}]` |
| POST | `/roles` | `role:write` | 创建（`201`） |
| PUT | `/roles/{id}` | `role:write` | 改名称/描述/启停 |
| DELETE | `/roles/{id}` | `role:write` | 内置禁删；仍有用户绑定 → `409` |
| PUT | `/roles/{id}/permissions` | **仅超管** | `permission_codes[]` 全量覆盖；非超管 → `403` |

**创建/更新角色请求**（`RoleRequest`）：`name`(2–100)、`description?`、`is_enabled`(默认 true)、`permission_codes[]`。

**角色响应**（`RoleResponse`）：`id`、`name`、`display_name`、`description?`、`is_builtin`、`is_enabled`、`permissions[]`。

**额外约束**：非超管不可编辑 `super_admin` 角色；内置角色不可改名/删除；种子中 `admin` **不含** `role:write`（角色 CRUD 实际仅超管具备）。

---

## 6. 部门管理 `/departments`

需 `department:read` / `department:write`。部门以 `code` 关联用户（`users.department`）与知识库（`knowledge_bases.department`）。**GUEST（访客专用）部门受保护**：不可改 code、不可删除。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/departments` | `department:read` | 分页（默认 `page_size=50`） |
| POST | `/departments` | `department:write` | 创建（`201`） |
| GET | `/departments/{dept_id}` | `department:read` | 详情（含成员与知识库） |
| PUT | `/departments/{dept_id}` | `department:write` | 更新 |
| DELETE | `/departments/{dept_id}` | `department:write` | 删除（解除关联，KB `department=null`、可见性回落 restricted）；返回 `{deleted:true}` |
| POST | `/departments/{dept_id}/members` | `department:write` | Body：`user_ids[]`（≥1） |
| DELETE | `/departments/{dept_id}/members/{user_id}` | `department:write` | 移除成员 |
| POST | `/departments/{dept_id}/knowledge-bases` | `department:write` | Body：`kb_ids[]`（≥1）；同步 KB 可见性 |
| DELETE | `/departments/{dept_id}/knowledge-bases/{kb_id}` | `department:write` | 解除 KB 关联 |

**创建请求**（`DepartmentCreate`）：`code`(1–50)、`name`(1–100)、`description?`、`is_enabled`(默认 true)。
**更新请求**（`DepartmentUpdate`）：以上字段均可选。
**列表项**（`DepartmentListItem`）：`id`、`code`、`name`、`description?`、`is_enabled`、`member_count`、`kb_count`、`created_at`、`updated_at`；详情另含 `members[]`、`knowledge_bases[]`。校验失败 → `422`。

---

## 7. 大模型管理 `/models`

密钥**不得**明文返回；仅以 `api_key_env`（环境变量名）与 `has_api_key`（是否已配置）体现。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/models/usage` | `model:read` | Langfuse 用量；Query：`days`(1–180,默认30)、`model?` |
| GET | `/models` | `model:read` | 分页；Query：`model_type`(llm\|embedding\|rerank) |
| POST | `/models` | `model:write` | 新增（`201`） |
| PUT | `/models/{model_id}` | `model:write` | 更新 |
| PATCH | `/models/{model_id}/status` | `model:write` | Body：`is_enabled` |
| PUT | `/models/{model_id}/default` | `model:write` | Body：`is_default`（默认 true）；同类型仅一个默认 |

**创建请求**（`CreateModelConfigRequest`）：`name`(1–100)、`model_type`、`provider`(1–50)、`model_name`(1–200)、`base_url?`(≤500)、`config`(dict)、`timeout_seconds`(5–600,默认60)、`api_key_env?`(≤100)、`is_default`(默认false)、`is_enabled`(默认true)、`priority`(0–10000,默认100)。更新请求同字段均可选。

**响应**（`ModelConfigResponse`）：以上字段 + `id`、`has_api_key`、`created_at`、`updated_at`（不含密钥明文）。

**`GET /models/usage` 响应 `data`**：`{ enabled, host, range:{from,to,days}, totals:{total_tokens,input_tokens,output_tokens,total_observations,total_traces,total_cost}, models:[{model, input_tokens, output_tokens, total_tokens, total_observations, total_traces, total_cost, daily:[...]}], notice? }`。`notice` 用于限流/缓存降级提示（如 Langfuse 429 时展示缓存数据）。Langfuse 未启用 → `enabled=false`；上游异常且无缓存 → `502`。

---

## 8. 知识库管理 `/knowledge-bases`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/knowledge-bases` | `kb:write` | 创建（`201`） |
| GET | `/knowledge-bases` | 需登录 | **仅返回当前用户可访问的库**；Query：`page`、`page_size`、`name?`、`type?`、`tag?` |
| GET | `/knowledge-bases/{kb_id}` | `kb:read` + 库访问 | 详情含统计 |
| PUT | `/knowledge-bases/{kb_id}` | `kb:write` | 改元信息 |
| DELETE | `/knowledge-bases/{kb_id}` | `kb:write` | Query：`permanent`(默认false)；默认软删 |
| POST | `/knowledge-bases/{kb_id}/re-vectorize` | `kb:vectorize` | 异步重向量化（Body 可选） |
| GET | `/knowledge-bases/{kb_id}/vectorize-status` | `kb:vectorize` | 进度 |
| PUT | `/knowledge-bases/{kb_id}/permissions` | `kb:write` | 配置用户/角色对库的权限 |

### 8.1 创建知识库请求（`KnowledgeBaseCreate`）

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 名称 |
| type | 是 | `technical`(technical_doc) / `product`(product_manual) / `faq` / `general` |
| embedding_model | 是 | 嵌入模型名 |
| tags | 否 | 标签数组 |
| description | 否 | 描述 |
| department | 否 | **访问控制核心**：`GUEST`=访客/全员可见；具体部门=部门隔离；留空=仅创建者/授权者 |
| visibility | 否 | 由 `department` 派生（GUEST→public，其余→restricted），一般无需手动传 |
| chunk_size | 否 | 默认 500（100–5000） |
| chunk_overlap | 否 | 默认 50（0–1000） |

> **重要**：可见性由部门派生，创建/更新时传入的 `visibility` 会被忽略并按 `department` 重新计算。

### 8.2 知识库响应（`KnowledgeBaseResponse`）

`id`、`name`、`type`、`tags[]`、`description?`、`visibility`、`department?`、`embedding_model`、`chunk_size`、`chunk_overlap`、`status`(active\|vectorizing\|archived\|deleted)、`current_index_version?`、`document_count`、`chunk_count`、`creator_id`、`created_at`、`updated_at`。

### 8.3 重向量化请求（`ReVectorizeRequest`，均可选）

`chunk_size?`(100–5000)、`chunk_overlap?`(0–1000)、`split_mode?`(fixed/sliding/paragraph/heading)、`separators?[]`、`embedding_model?`(≤200)、`apply_to_documents`(默认true)、`force_all`(默认false)。已有任务进行中 → `409`。

**向量化进度**（`VectorizeStatusResponse`）：`task_id`、`kb_id`、`status`、`progress`、`processed_count`、`total_count`、`error_message?`、`started_at?`、`completed_at?`、`target_version?`。

### 8.4 配置库权限请求（`KBPermissionUpdate`）

```json
{ "permissions": [ { "user_id": "uuid|null", "role_id": "uuid|null", "permission": "kb:upload" } ] }
```

全量覆盖语义；每项 `user_id` 与 `role_id` 至少一个。写入前自动创建快照。

---

## 9. 文档管理 `/knowledge-bases/{kb_id}/documents`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `.../documents` | `doc:read` | 分页 + `keyword` |
| POST | `.../documents/upload` | `kb:upload` | **multipart/form-data**，字段 `file`；`201` 并触发流水线 |
| GET | `.../documents/{doc_id}` | `doc:read` | 详情与状态 |
| GET | `.../documents/{doc_id}/content` | `doc:read` | 原文/规范化文本预览 |
| DELETE | `.../documents/{doc_id}` | `doc:write` | 删除文档 + 向量 + MinIO 对象 |
| PUT | `.../documents/{doc_id}/segment-rules` | `doc:segment` | 仅保存规则 |
| POST | `.../documents/{doc_id}/segment-preview` | `doc:segment` | 对已存文档试分段（不落库） |
| POST | `.../documents/segment-preview-file` | `doc:segment` | **multipart**：`file?` 或 `doc_id?` + `chunk_size?/chunk_overlap?/split_mode?`（Form）试分段 |
| POST | `.../documents/{doc_id}/re-segment` | `doc:segment` | 重分段 + 向量化，异步 `202` |
| POST | `.../documents/{doc_id}/retry` | `doc:write` | 失败重试，异步 `202`（error→parsing） |
| POST | `.../documents/{doc_id}/normalize` | `doc:write` | 规范化并返回统计 |
| GET | `.../documents/{doc_id}/chunks` | `doc:read` | 分段分页预览 |
| PUT | `.../documents/{doc_id}/chunks/{chunk_id}` | `doc:segment` | 编辑内容 / `is_enabled` |

### 9.1 上传说明

- **Content-Type**：`multipart/form-data`（字段名 `file`）。
- **体积**：反向代理 `client_max_body_size 100m`；超限 → `413`。
- **格式**：首期支持 `pdf/doc/docx/txt/md`；`csv/xlsx/pptx` 明确拒绝并返回错误。
- **流水线状态**：`uploaded → parsing → processing → pending_segment → vectorizing → ready`，失败为 `error`（带 `error_message`）。

### 9.2 主要响应结构

- **文档**（`DocumentResponse`）：`id`、`kb_id`、`filename`、`file_type`、`file_size`、`file_path`、`chunk_count`、`status`、`error_message?`、`creator_id`、`created_at`、`updated_at`。
- **内容预览**（`DocumentContentPreviewResponse`）：另含 `raw_text`、`normalized_text`、`raw_char_count`、`normalized_char_count`、`truncated`、`max_preview_chars`、`preview_source`、`segment_rules`。
- **分段**（`DocumentChunkResponse`）：`id`、`document_id`、`chunk_index`、`content`、`char_count`、`metadata`、`is_enabled`。禁用分段（`is_enabled=false`）**不参与检索与引用**。
- **分段规则请求**（`UpdateSegmentRulesRequest`）：`chunk_size`(100–5000)、`chunk_overlap`(0–1000)、`separators?[]`、`split_mode?`、`enable_semantic?`(默认false)。
- **规范化结果**（`NormalizeResult`）：`removed_blank_lines`、`removed_duplicate_blocks`、`char_count_before`、`char_count_after`。

---

## 10. 智能问答 `/qa`

### 10.1 发送问题（SSE）

- `POST /qa/ask` — **可选认证**（访客可访问，功能对应 `qa:ask`）
- 可选请求头：`X-Guest-Id`（访客归属标识，不自动复用旧会话）、`X-Request-Id`
- **响应**：`Content-Type: text/event-stream; charset=utf-8`（`Cache-Control: no-cache`、`X-Accel-Buffering: no`）

**请求体**（`AskRequest`）：

| 字段 | 必填 | 说明 |
|------|------|------|
| question | 是 | 1–2000 字符 |
| session_id | 否 | 不传则**始终新建会话**（不按 `X-Guest-Id` 自动复用）；传入则可多轮续聊（含已闲置过期的会话，会重新激活） |
| kb_ids | 否 | 限定知识库；默认全部可访问范围（与可访问集取交集） |
| strategy | 否 | `hybrid`(默认) / `vector` / `fulltext` |
| top_k | 否 | 默认 5（1–20） |
| temperature | 否 | 默认 0.7（0–2） |

**SSE 事件**：

| event | 说明 |
|-------|------|
| `intent` | Guard 放行后的意图识别结果 |
| `guard_blocked` | 被安全策略拒绝；含 `message`、`intent`、`reason_code`；流结束 |
| `query_processing` | Query 改写 / 扩展 / HyDE 等预处理元信息（可关） |
| `cache_hit` | 命中角色缓存问题，可直接返回答案 |
| `chunk` | 增量文本，字段 `content` |
| `citations` | 引用来源列表（`items` 与 `citations` 双键） |
| `done` | 结束，含 `session_id`、`message_id`、`request_id`、`performance`、`confidence`(high/medium/low) |
| `error` | 错误信息 |

典型顺序：`intent` →（可选 `query_processing` / `cache_hit`）→ `chunk*` → `citations` → `done`；被拦截时为 `guard_blocked`。

**引用对象**：`doc_id`、`doc_name`、`chunk_index`、`content`、`score`（向量相关度一般为 `1 - cosine_distance`）。

**范围规则**：

- 未登录：仅 `department=GUEST`（访客专用）知识库；
- 已登录：GUEST ∪ 本部门 ∪ 本人创建 ∪ 授权库；指定 `kb_ids` 时取交集；
- 仅检索**有 `current_index_version`（已建索引）**的库；无可检索目标时进入「无证据」兜底（严禁编造来源）。

**超时**：反向代理 SSE 读超时 600s。

### 10.2 会话与反馈

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/qa/sessions` | 需登录 | 仅本人会话（分页） |
| GET | `/qa/sessions/{session_id}` | 需登录 | 消息历史（含 citations，默认 `page_size=50`） |
| PUT | `/qa/sessions/{session_id}` | 需登录 | Body：`title`(1–100) |
| DELETE | `/qa/sessions/{session_id}` | 需登录 | 软删除并清理 Redis 缓存 |
| POST | `/qa/feedback` | 需登录 | `message_id`、`rating`(useful\|useless)、`comment?`(≤500) |

### 10.3 管理员会话分析

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/qa/admin/sessions` | `system:read` | 跨用户会话列表（分页）；项含 `owner`、`owner_type`(guest\|user)、`message_count`、`last_active_at` 等 |
| GET | `/qa/admin/sessions/{session_id}` | `system:read` | 会话详情 + 消息列表（含 `retrieval_meta.query_processing` 等预处理审计字段） |

> 上述管理端会话路径已在运行时提供；当前未写入 `openapi.json`（与 Query/角色缓存/RAGAS 同属扩展契约待补项）。

- **会话项**：`id`、`title`、`kb_names[]`、`message_count`、`created_at`、`updated_at`。
- **消息项**：`id`、`role`、`content`、`citations`、`token_count`、`created_at`、`request_id`、`strategy`、`latency_ms`。
- **会话生命周期**（`QASession.status`）：
  - `active`：进行中；管理员「活跃会话」仅统计此类。
  - `expired`：闲置超过 `QA_SESSION_IDLE_EXPIRE_MINUTES`（默认 30）未问答，由后台按 `QA_SESSION_EXPIRE_SWEEP_SECONDS` 扫描标记；同时清理 Redis 热缓存。**历史列表与消息查询仍包含 expired**（仅排除 `deleted`）。
  - `deleted`：用户软删除。
  - 携带 `session_id` 对 `expired` 会话继续提问 → 自动恢复为 `active`，并从 PG 回填上下文。
- 访客：请求可带 `X-Guest-Id` 做归属；会话与消息仍落 PG；Redis 仅作热缓存（TTL `QA_GUEST_SESSION_TTL_MINUTES`）。**长期历史列表仅登录用户**；只能访问本人会话。

---

## 11. 命中率测试 `/hit-tests`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/hit-tests/cases` | `test:read` | 用例列表 |
| POST | `/hit-tests/cases` | `test:write` | 创建用例（`201`；无问题 → `422`） |
| PUT | `/hit-tests/cases/{id}` | `test:write` | 编辑（无字段 → `422`） |
| DELETE | `/hit-tests/cases/{id}` | `test:write` | 删除 |
| POST | `/hit-tests/runs` | `test:write` | 执行（`202`）；需 `case_id` 或 `questions` |
| POST | `/hit-tests/compare` | `test:write` | 多策略对比（≥2 个不同策略） |
| GET | `/hit-tests/runs` | `test:read` | 运行记录列表 |
| DELETE | `/hit-tests/runs` | `test:write` | 删除全部运行记录 |
| GET | `/hit-tests/runs/{id}` | `test:read` | 汇总 + 每题明细 |
| DELETE | `/hit-tests/runs/{id}` | `test:write` | 删除单条运行 |
| GET | `/hit-tests/runs/{id}/export` | `test:read` | **CSV 下载**（`text/csv`，attachment） |

**用例请求**（`CreateTestCaseRequest`）：`name`、`description?`、`questions[]`；每个 `TestQuestion`：`question`、`expected_doc_ids?[]`、`expected_chunk_ids?[]`。

**执行请求**（`TestRunRequest`）：`case_id?`、`kb_ids[]`(≥1，须在授权范围)、`doc_ids?[]`、`strategy`(vector\|fulltext\|hybrid)、`top_k`(默认5,1–20)、`similarity_threshold`(默认0.5,0–1)、`questions?[]`。

**对比请求**（`CompareTestRequest`）：`case_id`、`kb_ids[]`、`doc_ids?[]`、`strategies[]`(默认三种,≥2)、`top_k`、`similarity_threshold`。

**运行响应**（`TestRunResponse`）：`id`、`case_id?`、`kb_ids`、`strategy`、`top_k`、`status`(running\|completed\|failed)、`total_questions`、`hit_count`、`hit_rate?`（命中题数/总题数）、**`score?`（综合得分 = 各题命中片段相关度的算术平均，0–1；全未命中为 0）**、`recall_at_k?`、`mrr?`、`avg_elapsed_ms?`、`created_at?`、`completed_at?`。

---

## 12. 快照管理 `/knowledge-bases/{kb_id}/snapshots`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `.../snapshots` | `snapshot:read` | 列表 |
| POST | `.../snapshots` | `snapshot:write` | 手动创建（`201`）；Body：`name`(1–200)、`description?`(≤2000) |
| POST | `.../snapshots/cleanup` | `snapshot:write` | 按保留策略清理 |
| GET | `.../snapshots/{snapshot_id}` | `snapshot:read` | 详情（文档列表、配置快照、权限快照、分段规则） |
| POST | `.../snapshots/{snapshot_id}/preview` | `snapshot:read` | 回退差异预览；Query：`document_ids?[]`（选择性） |
| POST | `.../snapshots/{snapshot_id}/rollback` | `snapshot:restore` | 回退；Body：`confirm`（**必须 true**）、`document_ids?[]` |
| DELETE | `.../snapshots/{snapshot_id}` | `snapshot:write` | 删除（回退保护快照不可手动删） |

**说明**：

- 快照含元数据、文档版本、分段规则、权限配置引用；**向量不落快照**，回退后重建索引。
- 自动触发类型：上传/删除/规范化/重分段/重向量化/权限/分段规则变更（`trigger` 前缀 `auto_*`）。
- 回退流程：先创建 `rollback_protection` 保护快照 → 恢复文档/配置/权限（含 name/tags/description）→ 创建 `building` 索引版本，KB 转 `vectorizing`；写入 `rollback_rebuild` 任务后异步重建。**选择性回退**也会把未选中但仍有效的文档迁入新版本集合，避免 activate 后检索丢失。重建只写目标版本集合。任一文档失败则不激活，并用保护快照补偿库表。
- **回退结果**（`RollbackResultResponse`）：`protection_snapshot_id`、`new_index_version`、`index_status`、`before_version?`、`after_version`、`restored_document_count`、`restored_document_ids`（实际为待重建文档 ID 列表）、`selective`、`rebuild_required`、`message`。

---

## 13. 审计日志 `/audit`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/audit/logs` | `audit:read` | 分页；筛选：`user_id`、`action`、`resource_type`、`resource_id`、`result`、`start_date`、`end_date` |
| GET | `/audit/logs/{log_id}` | `audit:read` | 详情，含 `detail` 变更对比、`ip_address`、`user_agent`、`error_message` |

**列表项**（`AuditLogListItem`）：`id`、`user_id?`、`user_name?`、`action`、`resource_type`、`resource_id?`、`result`(默认success)、`request_id?`、`created_at`。`action` 示例：`kb.create`、`kb.update`、`kb.delete`、`kb.permissions`、`kb.re_vectorize`、`doc.upload`、`doc.delete`、`auth.login`、`auth.change_password`、`user.status`、`snapshot.rollback`。

说明：文档写操作使用 `doc.*` 前缀（与管理端筛选 `doc.` 对齐）；知识库使用 `kb.*`；认证使用 `auth.*`。

---

## 14. 系统监控 `/monitor`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/monitor/health` | **公开** | `status`：healthy\|degraded\|unhealthy；`uptime_seconds`；`checks` 含 postgres/redis/chroma/langfuse/minio 连通性 |
| GET | `/monitor/stats` | `system:read` | `user_count`、`kb_count`、`doc_count`、**`active_sessions`（仅 `status=active`）**、`task_queue_size`、`qa_trend_7d` / `qa_trend_30d`、`hit_rate_trend_7d` / `hit_rate_trend_30d`、`error_24h`（4 桶）、`error_hourly_48h`（48 点）、`guard_blocked_24h`、`guard_blocked_7d`、`guard_recent_events` |
| GET | `/monitor/guard-events` | `system:read` | 分页 Guard 拦截明细；默认 `page_size=50` |
| GET | `/metrics`（应用根，非 `/api/v1`） | 内部 | Prometheus 文本指标，**不走统一包装**；云端可借 `METRICS_PUBLIC=false` 限制暴露 |

> `/api/v1/monitor/metrics` 为 `307` 重定向到 `/metrics`（隐藏于 schema）。

**Guard 事件项**（`GuardBlockedEventItem`）：`id`、`created_at`、`intent`、`reason_code`、`detector`、`confidence`、`actor_label`（用户名或「访客」）、`client_ip?`、`user_id?`、`is_registered`、`question_preview?`（脱敏短摘要，不含完整原文）。

---

## 15. Query 预处理 `/query-processing`

全局问答 Query 改写 / 扩展 / HyDE 开关（写入后对未命中缓存的下一次问答生效）。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/query-processing` | `system:read` | 当前配置 |
| PUT | `/query-processing` | `kb:write` | 完整替换：`rewrite_enabled`、`expansion_enabled`、`expansion_count`(0–5)、`hyde_enabled` |

响应另含 `updated_at`。

> 本模块路径已在运行时 API 提供；完整字段以路由实现为准（当前未全部写入 `openapi.json`）。

---

## 16. 角色缓存 `/role-caches`

按角色预生成高频问答缓存，命中时可走 `cache_hit` SSE 快捷路径。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/role-caches` | `system:read` | 各角色缓存配置与问题数量 |
| PATCH | `/role-caches/{role_id}` | `kb:write` | 更新 `enabled` / `interval_days` |
| GET | `/role-caches/{role_id}/questions` | `system:read` | 缓存问题明细 |
| POST | `/role-caches/{role_id}/analyze-documents` | `kb:write` | 手动从文档生成缓存问题 |
| POST | `/role-caches/{role_id}/analyze-history` | `kb:write` | 手动从历史高频问题生成 |

列表项含：`enabled`、`interval_days`、`document_question_limit`、`history_question_limit`、`question_count`、最近分析时间等。

> 同上，契约 JSON 可能尚未收录全部路径；联调以运行时与本文表为准。

---

## 17. RAGAS 评估 `/ragas`

基于知识库与样本的回答质量评估（Faithfulness / Answer Relevancy 等，具体指标见运行响应 `metric_scores`）。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/ragas/runs` | `system:read` | 评估运行列表；Query：`kb_id?` |
| GET | `/ragas/samples` | `system:read` | 可评估历史样本预览 |
| POST | `/ragas/generate-questions` | `system:read` | 从文档自动生成评估问题草稿；Body：`kb_id`、`count`(1–20) |
| POST | `/ragas/runs` | `system:read` | 执行评估；Body：`kb_id`、`sample_limit`、`samples?[]` |
| GET | `/ragas/runs/{run_id}` | `system:read` | 运行详情与逐样本指标 |

> 同上，完整 OpenAPI 条目可按需补入生成脚本。

---

## 18. 联调检查清单

1. 前端仅以 [`openapi.json`](./openapi.json) + 本文档字段名为准；扩展模块以本文 + 运行时为准。
2. 需鉴权接口先测 `401`，再测无权限 `403`。
3. 知识库列表不得返回未授权库；访客仅见 GUEST 部门库。
4. `/qa/ask` 覆盖：未登录仅 GUEST 库、登录后授权范围、非法 `kb_ids`、`guard_blocked`。
5. 上传超大文件 → `413`；不支持格式 → `400` 且 message 明确。
6. SSE 至少覆盖 `intent → chunk → citations → done`；拦截场景覆盖 `guard_blocked`。
7. 回退：`confirm=false` 必拒；`true` 后创建 `rollback_rebuild` 向量化任务，可通过 `GET /knowledge-bases/{kb_id}/vectorize-status` 查询进度；重建成功后原子激活新索引，失败则用保护快照补偿库表且不切换版本。
8. 部门：GUEST 部门不可删除/改 code；员工访问 GUEST 库不应被拒。
9. 用户：管理员不可删除/禁用同级或更高级用户；不可将他人设为 admin/超管；角色权限配置仅超管可调。
10. 改密：普通用户成功；`super` 返回 `403`。

---

## 19. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 2.1.0 | 2026-07-22 | 补充管理员会话分析 `/qa/admin/sessions*`；核对监控统计字段与登录文案 |
| 2.1.0 | 2026-07-22 | `/monitor/stats` 补充 30 天趋势与 48h 错误分桶；登录失败文案对齐「用户名或密码错误」 |
| 2.1.0 | 2026-07-21 | 对齐本机入口 `18080`；补充改密、Guard 事件、SSE Guard/预处理事件、命中率 `score`、Query/角色缓存/RAGAS 索引；重生成 openapi（61 paths） |
| 2.1.0 | 2026-07-19 | 补充会话闲置过期（active→expired）、访客不自动复用会话、`active_sessions` 定义；对齐 Langfuse 云端配置说明 |
| 2.1.0 | 2026-07-17 | 契约迁入 `docs/`；补充用户删除、角色等级与分配规则；`admin` 不含 `role:write`；默认角色改为 `guest`；废弃 `user` 角色 |
| 2.1.0 | 2026-07-17 | 全面对齐当前实现：新增部门管理与部门驱动访问控制、模型用量监测（Langfuse）、文档内容预览/分段预览/失败重试、命中率多策略对比与运行删除、快照清理与选择性回退；刷新全部字段与约束 |
| 2.1.0 | 2026-07-16 | 框架阶段首版契约与中文说明 |

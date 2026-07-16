# AI 知识库 RAG 平台 — 接口文档（中文）

> 版本：2.1.0  
> 与产品手册 V2.1、`contracts/openapi.json` 同步  
> 状态：核心模块已实现，响应以运行中的 API 与契约为准

---

## 1. 总则

### 1.1 Base URL

| 环境 | Base URL |
|------|----------|
| 本地 / Docker 统一入口 | `http://localhost:8080/api/v1` |

所有下文路径均相对于该 Base URL，例如登录完整地址为：

`POST http://localhost:8080/api/v1/auth/login`

### 1.2 认证方式

```http
Authorization: Bearer <access_token>
```

- 登录成功后获得 `access_token`（默认约 30 分钟）与 `refresh_token`（默认 7 天）
- 除标注「公开」或「可选认证」的接口外，均需携带有效 Bearer Token
- 禁用用户的 Token 应在服务端校验时拒绝（403）

### 1.3 统一响应包装

除 SSE 流式接口、CSV 导出、Prometheus 指标外，JSON 接口统一为：

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
| `code` | int | 业务码，`0` 表示成功；非 0 表示业务失败（可与 HTTP 状态码并存） |
| `message` | string | 人类可读提示 |
| `data` | object / array / null | 业务载荷 |
| `request_id` | string (UUID) | 请求追踪 ID，前后端日志应对齐 |

### 1.4 分页约定

**请求查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 从 1 开始 |
| `page_size` | int | 20 | 范围 1–100 |

**响应 `data` 结构：**

```json
{
  "items": [],
  "total": 100,
  "page": 1,
  "page_size": 20
}
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
| 404 | 资源不存在或不可见（勿泄露无权限细节时可统一 404） |
| 409 | 冲突（如用户名已存在、内置角色不可删） |
| 413 | 上传文件过大 |
| 422 | 字段校验失败 |
| 500 | 服务器错误 |
| 501 | 尚未实现（框架阶段占位，正式环境不应出现） |

### 1.6 访客端 vs 管理端

| 端 | 典型接口 | 说明 |
|----|----------|------|
| 访客端 | `/auth/*`、`/qa/ask`、公开知识库问答 | 未登录仅可检索 `visibility=public` 的知识库 |
| 管理端 | `/users`、`/roles`、`/knowledge-bases`、`/hit-tests`、`/audit`、`/monitor/stats` 等 | 需对应权限标识 |

机器可读契约见：[contracts/openapi.json](../contracts/openapi.json)

---

## 2. 权限模型（鉴权必读）

权限判定须**同时满足**：

1. 用户角色拥有功能权限标识（如 `kb:read`）
2. 若权限作用域为知识库级，还须对该知识库有授权记录

### 2.1 权限标识清单

| 权限标识 | 说明 | 作用域 |
|----------|------|--------|
| `user:read` / `user:write` | 用户查看 / 改删启停 | 全局 |
| `role:read` / `role:write` | 角色与功能权限配置 | 全局 |
| `kb:read` / `kb:write` | 知识库查看 / 创建修改删除 | 可读可按库隔离；写多为全局 |
| `kb:upload` | 上传文档到指定库 | 可按库隔离 |
| `kb:vectorize` | 触发重向量化 / 查进度 | 可按库隔离 |
| `doc:read` / `doc:write` | 文档查看 / 修改删除规范化 | 可按库隔离 |
| `doc:segment` | 分段规则与重分段、编辑分段 | 可按库隔离 |
| `qa:ask` | 问答 | 全局功能；实际检索范围仍受库可见性与授权限制 |
| `test:read` / `test:write` | 命中率测试查看 / 执行 | 全局（测试范围仍受库授权） |
| `snapshot:read` / `snapshot:write` / `snapshot:restore` | 快照查看 / 创建删除 / 回退 | 可按库隔离 |
| `model:read` / `model:write` | 模型配置 | 全局 |
| `system:read` | 系统统计 | 全局 |
| `audit:read` | 审计日志 | 全局 |

### 2.2 内置角色（种子数据）

| 角色 | 说明 |
|------|------|
| `admin` | 系统管理员，全量能力 |
| `user` | 注册用户，基础问答与授权范围内能力 |
| `kb_admin` | 知识库维护员，维护被授权库 |

内置角色**不可删除**。

---

## 3. 认证模块 `/auth`

### 3.1 用户注册

- **方法 / 路径：** `POST /auth/register`
- **权限：** 公开
- **请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|------|------|------|
| username | string | 是 | 3–50 | 唯一 |
| password | string | 是 | 8–128 | 明文传输，须 HTTPS |
| email | string | 是 | email | 唯一 |
| nickname | string | 否 | 1–100 | 昵称 |

- **成功：** `201`，`data` 为用户信息（不含密码）
- **错误：** 用户名/邮箱冲突 → `409`

### 3.2 用户登录

- **方法 / 路径：** `POST /auth/login`
- **权限：** 公开
- **请求体：** `username`、`password`
- **成功：** `200`，`data`：

| 字段 | 说明 |
|------|------|
| access_token | 访问 JWT |
| refresh_token | 刷新 JWT |
| token_type | 固定 `bearer` |
| expires_in | access 有效秒数 |

- **禁用用户：** `403`

### 3.3 刷新 Token

- **方法 / 路径：** `POST /auth/refresh`
- **权限：** 需有效 refresh（契约按需登录处理）
- **请求体：** `{ "refresh_token": "..." }`
- **成功：** 返回新的 Token 对

### 3.4 当前用户信息

- **方法 / 路径：** `GET /auth/me`
- **权限：** 需登录
- **成功 `data` 含：** `id`、`username`、`email`、`nickname`、`status`、`roles[]`、`permissions[]`、`created_at`  
  前端据此渲染菜单与按钮（**不能替代后端鉴权**）

---

## 4. 用户管理 `/users`

> 管理端接口，默认需要 `user:read` / `user:write`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/users` | `user:read` | 分页列表；Query：`keyword`、`status` |
| GET | `/users/{id}` | `user:read` | 详情 |
| PUT | `/users/{id}` | `user:write` | 改昵称/邮箱 |
| PATCH | `/users/{id}/status` | `user:write` | `status`: `active` \| `disabled`；禁用后立即拒绝新请求 |
| PUT | `/users/{id}/roles` | `user:write` | Body：`role_ids` 全量覆盖；记审计 |
| POST | `/users/{id}/reset-password` | `user:write` | Body：`new_password` |

---

## 5. 角色管理 `/roles`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/roles` | `role:read` | 分页列表 |
| POST | `/roles` | `role:write` | 创建；Body：`name`、`description?`、`permission_codes[]` |
| PUT | `/roles/{id}` | `role:write` | 改名称/描述 |
| DELETE | `/roles/{id}` | `role:write` | 内置角色禁止；仍有用户绑定时建议 `409` |
| PUT | `/roles/{id}/permissions` | `role:write` | `permission_codes` 全量覆盖 |

---

## 6. 大模型管理 `/models`

密钥**不得**在列表/详情响应中明文返回。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/models` | `model:read` | Query 可选 `model_type`=`llm`\|`embedding`\|`rerank` |
| POST | `/models` | `model:write` | 新增配置 |
| PUT | `/models/{id}` | `model:write` | 更新 |
| PATCH | `/models/{id}/status` | `model:write` | Body：`is_enabled` |
| PUT | `/models/{id}/default` | `model:write` | Body：`is_default`；同类型仅一个默认 |

**创建请求主要字段：** `name`、`model_type`、`provider`、`model_name`、`base_url?`、`config?`、`timeout_seconds?`

---

## 7. 知识库管理 `/knowledge-bases`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/knowledge-bases` | 需登录 | **仅返回当前用户有权访问的库** |
| POST | `/knowledge-bases` | `kb:write` | 创建 |
| GET | `/knowledge-bases/{id}` | `kb:read` + 库授权 | 详情含统计 |
| PUT | `/knowledge-bases/{id}` | `kb:write` | 改元信息 |
| DELETE | `/knowledge-bases/{id}` | `kb:write` | 删除；记审计 |
| POST | `/knowledge-bases/{id}/re-vectorize` | `kb:vectorize` | 异步，建议 `202` |
| GET | `/knowledge-bases/{id}/vectorize-status` | `kb:vectorize` | 进度百分比等 |
| PUT | `/knowledge-bases/{id}/permissions` | `kb:write` | 配置用户/角色对库的权限 |

### 7.1 创建知识库请求体

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 名称 |
| type | 是 | `technical_doc` / `product_manual` / `faq` / `general` |
| embedding_model | 是 | 嵌入模型名 |
| tags | 否 | 标签数组 |
| description | 否 | 描述 |
| visibility | 否 | 默认 `restricted`；`public` 允许访客检索 |
| chunk_size | 否 | 默认 500，范围 100–5000 |
| chunk_overlap | 否 | 默认 50，范围 0–1000 |

### 7.2 配置库权限请求体

```json
{
  "grants": [
    {
      "user_id": "uuid-or-null",
      "role_id": "uuid-or-null",
      "permission_code": "kb:upload"
    }
  ]
}
```

约束：`user_id` 与 `role_id` **至少填一个**。建议实现为全量覆盖语义，并在变更前自动快照（P1）。

---

## 8. 文档管理 `/knowledge-bases/{kb_id}/documents`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `.../documents` | `doc:read` | 分页+`keyword` |
| POST | `.../documents/upload` | `kb:upload` | `multipart/form-data`，字段名 `file` |
| GET | `.../documents/{id}` | `doc:read` | 详情与状态 |
| DELETE | `.../documents/{id}` | `doc:write` | 删除；P1 前自动快照 |
| PUT | `.../documents/{id}/segment-rules` | `doc:segment` | 只改规则 |
| POST | `.../documents/{id}/re-segment` | `doc:segment` | 重分段+向量化，异步 `202` |
| POST | `.../documents/{id}/normalize` | `doc:write` | 规范化，返回统计 |
| GET | `.../documents/{id}/chunks` | `doc:read` | 分段预览分页 |
| PUT | `.../documents/{id}/chunks/{chunk_id}` | `doc:segment` | 编辑内容 / `is_enabled` |

### 8.1 上传说明

- **Content-Type：** `multipart/form-data`
- **体积限制：** 反向代理已配 `client_max_body_size 100m`
- **格式：** 首期 P0：`pdf` / `doc` / `docx` / `txt` / `md`；P1：`csv` / `xlsx` / `pptx`（契约已预留，首期可拒绝并返回明确错误）
- **流水线状态（文档 `status`）：**  
  `uploaded` → `parsing` → `processing` → `pending_segment` → `vectorizing` → `ready`  
  失败为 `error`（可带 `error_message`）

### 8.2 编辑分段

禁用分段（`is_enabled=false`）后**不得**参与检索与问答引用。

---

## 9. 智能问答 `/qa`

### 9.1 发送问题（SSE）

- **方法 / 路径：** `POST /qa/ask`
- **权限：** 可选认证（访客可访问）；功能上对应 `qa:ask`，检索范围按身份过滤
- **请求体：**

| 字段 | 必填 | 说明 |
|------|------|------|
| question | 是 | 1–2000 字符 |
| session_id | 否 | 不传则新建会话 |
| kb_ids | 否 | 限定知识库；默认全部可访问范围 |
| strategy | 否 | 默认 `hybrid`；另支持 `vector` / `fulltext` |
| top_k | 否 | 默认 5，范围 1–20 |
| temperature | 否 | 默认 0.7，范围 0–2 |

- **响应：** `Content-Type: text/event-stream`
- **事件 `event` 取值：**

| event | 说明 |
|-------|------|
| `chunk` | 增量文本，字段 `content` |
| `citations` | 引用来源列表 |
| `done` | 结束，含 `session_id` / `message_id` |
| `error` | 错误信息 |

**引用对象字段：** `doc_id`、`doc_name`、`chunk_index`、`content`、`score`

**范围规则：**

- 未登录：仅 `visibility=public`
- 已登录：公开库 ∪ 本人/角色授权库；指定 `kb_ids` 时取交集

**超时：** 反向代理 SSE 读超时 600s。

### 9.2 会话与反馈

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/qa/sessions` | 需登录 | 仅本人会话 |
| GET | `/qa/sessions/{id}` | 需登录 | 消息历史（含 citations） |
| PUT | `/qa/sessions/{id}` | 需登录 | Body：`title`（1–100） |
| DELETE | `/qa/sessions/{id}` | 需登录 | 删除会话 |
| POST | `/qa/feedback` | 需登录 | `message_id`、`rating`=`useful`\|`useless`、`comment?` |

访客会话可用 `guest_id` 短期保存（实现细节见产品手册）；长期历史仅登录用户。

---

## 10. 命中率测试 `/hit-tests`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/hit-tests/cases` | `test:read` | 用例列表 |
| POST | `/hit-tests/cases` | `test:write` | 创建用例（含期望 doc/chunk） |
| PUT | `/hit-tests/cases/{id}` | `test:write` | 编辑 |
| DELETE | `/hit-tests/cases/{id}` | `test:write` | 删除 |
| POST | `/hit-tests/runs` | `test:write` | 执行；可挂 `case_id` 或临时 `questions`；建议 `202` |
| GET | `/hit-tests/runs` | `test:read` | 运行记录 |
| GET | `/hit-tests/runs/{id}` | `test:read` | 汇总 + 每题明细 |
| GET | `/hit-tests/runs/{id}/export` | `test:read` | CSV 下载 |

**执行请求要点：** `kb_ids` 必填且须在授权范围内；`strategy`、`top_k`、`similarity_threshold` 可调。

**常用指标：** `recall_at_k`、`mrr`、`avg_elapsed_ms`、`hit_count` / `total_questions`

---

## 11. 快照管理 `/knowledge-bases/{kb_id}/snapshots`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `.../snapshots` | `snapshot:read` | 列表 |
| POST | `.../snapshots` | `snapshot:write` | 手动创建；Body：`name`、`description?` |
| GET | `.../snapshots/{id}` | `snapshot:read` | 详情（文档列表、配置快照） |
| POST | `.../snapshots/{id}/preview` | `snapshot:read` | 回退差异预览 |
| POST | `.../snapshots/{id}/rollback` | `snapshot:restore` | Body：`confirm` **必须为 true**；可选 `document_ids` 选择性恢复 |
| DELETE | `.../snapshots/{id}` | `snapshot:write` | 删除快照（回退保护快照不可手动删除） |

**说明：**

- 快照含元数据、文档版本、分段规则、权限配置等引用；向量本身可不落快照，回退后重建索引
- 自动触发类型（实现时）：上传/删除/规范化/重分段/重向量化/权限变更等；入口 `take_auto_snapshot`
- 正式回退前应创建 `rollback_protection` 保护快照
- 回退后索引版本先为 `building`，向量重建完成后由服务层 `activate_index_version` 原子切换

---

## 12. 审计日志 `/audit`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/audit/logs` | `audit:read` | 分页；筛选：`user_id`、`action`、`resource_type`、`resource_id`、`result`、`start_date`、`end_date` |
| GET | `/audit/logs/{id}` | `audit:read` | 详情，含 `detail` 变更对比 |

`action` 示例：`kb.create`、`doc.delete`、`user.disable`

---

## 13. 系统监控 `/monitor`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/monitor/health` | 公开 | `status`：`healthy` \| `degraded` \| `unhealthy`；含各组件 `checks` |
| GET | `/monitor/stats` | `system:read` | 用户数、库数、文档数、活跃会话、队列长度 |
| GET | `/metrics` | 内部 | Prometheus 文本指标；由应用根路径或独立挂载，**不一定**走 `/api/v1` 包装 |

---

## 14. 联调检查清单（团队）

1. 前端只认 `contracts/openapi.json` + 本文档字段名  
2. 所有需鉴权接口先测 401，再测无权限 403  
3. 知识库列表不得返回未授权库  
4. `/qa/ask` 分别测：未登录仅公开库、登录后授权范围、非法 `kb_ids`  
5. 上传超大文件应 413；不支持格式应 400 且 message 明确  
6. SSE：至少覆盖 `chunk` → `citations` → `done` 顺序  
7. 回退：`confirm=false` 必须拒绝；`true` 后可查向量化进度  

---

## 15. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 2.1.0 | 2026-07-16 | 框架阶段首版契约与中文说明，对齐产品手册 V2.1 |

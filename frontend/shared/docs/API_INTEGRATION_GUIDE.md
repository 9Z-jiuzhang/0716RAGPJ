# 知识库 RAG 平台 — 第三方应用接入指南

> 版本：与产品 `APP_VERSION`（当前 `2.1.0`）对齐  
> 适用场景：将本系统接入 **Android / iOS / 桌面客户端 / 其他业务后台**  
> 完整字段级契约另见仓库 `docs/API.md`、运行时 [`/openapi.json`](/openapi.json)、仓库 `docs/CONTRACT.md`


本文面向「如何在别的应用里调用本知识库」，强调：**鉴权怎么做、问答怎么流式收、会话怎么管、常见坑怎么避**。管理端运维类接口仅作索引，细节请查 `API.md`。

---

## 1. 系统能提供什么

本平台是一套企业级 **RAG（检索增强生成）知识库** 后端，对外暴露统一的 HTTP JSON / SSE API。第三方应用通常只需要：

| 能力 | 说明 | 典型接口 |
|------|------|----------|
| 登录与令牌 | 账号密码换 JWT，刷新续期 | `/auth/login`、`/auth/refresh` |
| 流式问答 | 按知识库检索并生成回答，边生成边推送 | `POST /qa/ask`（SSE） |
| 会话管理 | 多轮对话列表、历史、重命名、删除 | `/qa/sessions*` |
| 回答反馈 | 标记有用 / 无用 | `POST /qa/feedback` |
| 可见知识库 | 查询当前身份可检索的知识库 | `GET /knowledge-bases` |
| 健康探活 | 接入方做存活检查 | `GET /monitor/health` |

高级能力（上传文档、向量化、命中率测试、RAGAS、用户角色管理等）同样走 REST，但通常由管理端使用，移动端一般不必直连。

---

## 2. 访问入口与 Base URL

所有业务接口挂在统一前缀：

```text
{ORIGIN}/api/v1
```

| 部署方式 | 推荐 ORIGIN | 说明 |
|----------|-------------|------|
| Docker Compose + 反代（本仓库默认） | `http://<主机>:18080` | 经 Nginx 同源反代 `/api/` |
| 云端 HTTPS | `https://<域名>` | 见 `docs/CLOUD_DEPLOY.md`；前端仍用相对路径 `/api/v1` |
| 直连 API 容器 | `http://<主机>:18000` | 仅调试；生产禁止对公网开放 |

示例：登录完整地址

```http
POST http://192.168.1.10:18080/api/v1/auth/login
Content-Type: application/json
```

> Android 模拟器访问宿主机：常用 `10.0.2.2:<端口>` 代替 `localhost`。真机请使用电脑局域网 IP，并保证防火墙放行。

---

## 3. 统一约定（所有客户端必须遵守）

### 3.1 鉴权头

```http
Authorization: Bearer <access_token>
```

- `access_token`：默认约 **30 分钟**有效  
- `refresh_token`：默认约 **7 天**，用于换新 access  
- 除标注「公开」的接口外，均需携带有效 Token  
- Token 失效 → HTTP `401`；账号禁用或权限不足 → `403`

### 3.2 建议额外请求头

| 头 | 用途 |
|----|------|
| `Content-Type: application/json` | JSON 请求体 |
| `Accept: application/json` | 普通接口；问答请用 `text/event-stream` |
| `X-Request-Id` | 客户端生成的 UUID，便于与服务端日志对齐 |
| `X-Guest-Id` | 未登录访客的稳定匿名 ID（≤64 字符），建议 App 首次安装写入本地并长期复用 |

### 3.3 统一 JSON 响应包装

除 **SSE 流式问答**、**CSV 导出**、**Prometheus 指标** 外，成功响应形如：

```json
{
  "code": 0,
  "message": "success",
  "data": { },
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| 字段 | 含义 |
|------|------|
| `code` | 业务码，`0` 表示成功 |
| `message` | 可读提示（可直接展示给用户，或映射本地文案） |
| `data` | 真正业务数据；客户端应主要解析此字段 |
| `request_id` | 追踪 ID，客服 / 排障时请一并提供 |

分页列表的 `data` 一般为：

```json
{ "items": [ ... ], "total": 100, "page": 1, "page_size": 20 }
```

### 3.4 常见 HTTP 状态码

| 状态码 | 含义 | App 建议行为 |
|--------|------|----------------|
| 200 / 201 / 202 | 成功 / 已创建 / 异步已受理 | 解析 `data` |
| 400 / 422 | 参数或业务错误 | 展示 `message` 或 `detail` |
| 401 | 未登录或 Token 过期 | 先 `refresh`，失败则跳登录 |
| 403 | 无权限或账号禁用 | 提示权限不足 |
| 404 | 资源不存在 | 刷新列表 |
| 409 | 冲突（用户名/邮箱已存在等） | 提示修改输入 |
| 413 | 上传超过约 100MB | 压缩或分卷 |
| 429 | 触发限流 | 退避重试 |
| 500 / 502 | 服务或上游异常 | 稍后重试 |

---

## 4. 推荐接入架构（以 Android App 为例）

```text
┌─────────────┐     HTTPS/HTTP      ┌──────────────────┐
│  Android App │ ─────────────────► │ Nginx :18080     │
│  (OkHttp)    │  Bearer + SSE      │  /api/ → FastAPI │
└─────────────┘                     └──────────────────┘
        │
        ├─ 登录页 → POST /auth/login → 本地安全存储 Token
        ├─ 问答页 → POST /qa/ask (SSE) → 逐段渲染回答
        ├─ 历史页 → GET /qa/sessions → 打开详情拉消息
        └─ 设置页 → PUT /auth/me、POST /auth/change-password
```

**建议分层：**

1. **AuthRepository**：登录、刷新、退出清 Token  
2. **QaRepository**：流式问答、会话 CRUD、反馈  
3. **KbRepository**：可选，拉取可选知识库列表给用户勾选  
4. **TokenInterceptor**：自动附加 `Authorization`；收到 `401` 时单飞刷新

---

## 5. 认证与用户（接入必做）

### 5.1 注册 — `POST /auth/register`（公开）

为终端用户创建账号，默认角色为访客 `guest`（仅能问答访客可见知识库）。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 3–50，唯一 |
| password | string | 是 | 8–128 |
| email | string | 是 | 邮箱，唯一 |
| nickname | string | 否 | 显示名 |

**功能解说：** 适合 App 内「注册」；注册成功后一般再调登录拿 Token。冲突返回 `409`。

### 5.2 登录 — `POST /auth/login`（公开）

统一登录入口：访客 / 员工 / 管理员同一接口。

**请求体：** `{ "username": "...", "password": "..." }`（username 也可用邮箱）

**响应 `data` 要点：**

| 字段 | 说明 |
|------|------|
| access_token | 访问令牌，后续请求放在 Authorization |
| refresh_token | 刷新令牌，仅存本地安全区，勿日志打印 |
| expires_in | access 有效秒数 |
| user | 用户资料、roles、permissions、department |
| landing / landing_href | Web 端分流提示；**原生 App 可忽略**，自行进主界面 |

**功能解说：** 这是接入的第一步。App 应持久化两个 Token 与用户摘要；权限列表可用于隐藏无权限的菜单。凭证错误返回 `401`，文案为「用户名或密码错误」；账号禁用返回 `403`。

### 5.3 刷新令牌 — `POST /auth/refresh`（公开）

**请求体：** `{ "refresh_token": "..." }`  
**功能解说：** access 过期后不要立刻踢出登录；用 refresh 换新 access（及可能轮换的 refresh）。刷新失败再清会话并跳登录。

### 5.4 当前用户 — `GET /auth/me`（需登录）

**功能解说：** 冷启动校验 Token 是否仍有效，并刷新本地权限/昵称。

### 5.5 更新资料 — `PUT /auth/me`（需登录）

可改 `nickname`、`email`（及部分场景下的部门字段，视后端策略）。  
**功能解说：** 个人中心「保存资料」。

### 5.6 修改密码 — `POST /auth/change-password`（需登录）

**请求体：**

| 字段 | 说明 |
|------|------|
| old_password | 原密码 |
| new_password | 新密码（≥8） |
| confirm_password | 再次确认，须与 new 一致 |

**功能解说：** 普通用户自助改密。固定超管账号 `super` **禁止**走此接口，密码仅能通过服务器 `.env` 的 `SUPER_ADMIN_PASSWORD` 维护。

---

## 6. 核心：流式问答 `POST /qa/ask`

这是知识库系统对外最重要的接口，也是 Android 接入的重点。

### 6.1 功能解说

1. 服务端先经 **LLM Guard** 做安全意图检查（提示注入、窃密、越权、破坏性指令等）；不通过则推送 `guard_blocked` 并结束。  
2. 通过后在授权范围内做检索（向量 / 全文 / 混合），再调用大模型生成回答。  
3. 回答以 **SSE（Server-Sent Events）** 分片推送，适合边收边显示。  
4. 未登录也可调用（访客），但检索范围通常限于访客部门知识库；登录用户可访问其部门知识库（以及创建者本人库）。功能权限由角色决定，请由超管在「组织与权限」配置。

### 6.2 请求

```http
POST /api/v1/qa/ask
Content-Type: application/json
Accept: text/event-stream
Authorization: Bearer <可选，访客可省略>
X-Guest-Id: <未登录时强烈建议>
X-Request-Id: <建议>
```

**JSON 体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 用户问题，1–2000 字 |
| session_id | UUID | 否 | 不传则新建会话；多轮请带上一次返回的会话 ID |
| kb_ids | UUID[] | 否 | 限定检索的知识库；不传则按权限可见范围检索 |
| strategy | string | 否 | `vector` / `fulltext` / `hybrid`，默认 `hybrid` |
| top_k | int | 否 | 引用片段数，1–20，默认 5 |
| temperature | float | 否 | 生成温度 0–2，默认 0.7 |

> **不要用普通 EventSource GET**：本接口是 **POST + body**，请用 OkHttp / HttpURLConnection 读流。

### 6.3 SSE 事件一览

每个事件块形如：

```text
event: chunk
data: {"content":"……"}

```

| 事件名 | 含义 | data 要点 |
|--------|------|-----------|
| `intent` | Guard 识别的意图（已放行） | intent、confidence、detector |
| `guard_blocked` | 被安全策略拒绝 | message、intent、reason_code |
| `cache_hit` | 命中角色/问题缓存（若启用） | 可能直接给出缓存回答相关信息 |
| `query_processing` | Query 预处理结果 | 改写/扩展等元数据 |
| `chunk` | 回答正文增量 | 字段 `content`；前端拼接到气泡 |
| `citations` | 引用来源列表 | `citations` / `items`：文档名、分段、相关度 score |
| `done` | 本轮结束 | session_id、message_id、confidence、performance 等 |
| `error` | 流水线错误 | message |

**App 渲染建议：**

1. 收到 `chunk` → 追加到当前助手气泡（注意思考内容若带 `<think>` 可折叠展示）  
2. 收到 `citations` → 展示「引用来源」与检索相关度  
3. 收到 `done` → 保存 `session_id` / `message_id`，解锁输入框  
4. 收到 `guard_blocked` / `error` → 展示 message，结束流

### 6.4 会话与访客说明

- 不传 `session_id`：**始终新建**会话。  
- `X-Guest-Id` 只标识访客归属，**不会**自动复用旧会话。  
- 登录用户的会话列表只返回本人会话；历史消息接口同理。  
- 闲置过久可能 `expired`，列表仍可见；再次用同一 `session_id` 提问可重新激活（视服务端策略）。

---

## 7. 会话与反馈（问答 App 常用）

### 7.1 我的会话列表 — `GET /qa/sessions`

- 查询参数：`page`、`page_size`  
- **需登录**  
- **功能解说：** 历史对话入口；展示 title、kb_names、message_count、时间。

### 7.2 会话消息 — `GET /qa/sessions/{session_id}`

- **功能解说：** 打开某次对话，拉取 user/assistant 消息、citations、耗时等。

### 7.3 重命名 — `PUT /qa/sessions/{session_id}`

- 体：`{ "title": "新标题" }`（1–100 字）

### 7.4 删除 — `DELETE /qa/sessions/{session_id}`

- **功能解说：** 软删除；本地列表应同步移除。

### 7.5 反馈 — `POST /qa/feedback`（需登录）

| 字段 | 说明 |
|------|------|
| message_id | 助手消息 ID（来自 `done` 或历史） |
| rating | 如有用 / 无用（以服务端枚举为准，常见为字符串） |
| comment | 可选备注 |

**功能解说：** 用于改进质量与运营分析；应在回答完成后提供点赞/点踩。

---

## 8. 知识库列表（可选）

### `GET /knowledge-bases`

- 权限：通常需要 `kb:read`；访客仅见授权/访客库  
- **功能解说：** 让用户在提问前勾选「从哪些库检索」。把选中的 ID 数组放进 `/qa/ask` 的 `kb_ids`。  
- 创建/改删、上传、向量化等属于管理能力，详见 `API.md` 第 8–9 章，一般不必做进消费者 App。

---

## 9. 探活与监控（运维 / SDK 健康检查）

| 接口 | 鉴权 | 功能解说 |
|------|------|----------|
| `GET /monitor/health` | 公开或低门槛 | 检查 postgres / redis / chroma / langfuse / minio 等组件是否 healthy |
| `GET /monitor/stats` | `system:read` | 用户数、7/30 天问答与命中率趋势、48h 错误分桶、Guard 阻拦统计等，偏管理端仪表盘 |
| `GET /monitor/guard-events` | `system:read` | LLM Guard 拦截明细（账号、IP、意图），偏安全运营 |

移动端 SDK 建议仅在启动或设置页调用 `health`；不要把管理统计接口暴露给普通用户 Token。

---

## 10. 其他模块索引（管理 / 质量）

以下模块完整字段说明见 [`API.md`](./API.md)。第三方业务 App **通常不需要**直接集成，除非你在做管理壳或自动化运维。

| 模块前缀 | 功能解说（中文） |
|----------|------------------|
| `/users` | 用户增删改、启停、分配角色（需 `user:*`） |
| `/roles` | 角色与权限码配置（写权限敏感，部分仅超管） |
| `/departments` | 部门、成员、关联知识库 |
| `/models` | LLM / Embedding / Rerank 配置与用量 |
| `/knowledge-bases/.../documents` | 文档上传、分段、清洗、chunk 启停 |
| `/knowledge-bases/.../snapshots` | 索引快照创建与回退 |
| `/hit-tests` | 检索命中率用例与运行记录 |
| `/qa/admin/sessions` | 管理端跨用户会话与预处理审计（见 `API.md` §10.3） |
| `/ragas` | RAGAS 质量评估运行 |
| `/role-caches` | 按角色缓存高频问题 |
| `/query-processing` | Query 预处理策略配置 |
| `/audit` | 操作审计日志 |
| `/auth/change-password` 等 | 见第 5 节 |

---

## 11. Android（Kotlin + OkHttp）示例

### 11.1 登录

```kotlin
val json = JSONObject()
  .put("username", username)
  .put("password", password)
val body = json.toString().toRequestBody("application/json".toMediaType())
val req = Request.Builder()
  .url("$BASE/api/v1/auth/login")
  .post(body)
  .build()
client.newCall(req).execute().use { resp ->
  val root = JSONObject(resp.body!!.string())
  require(root.getInt("code") == 0) { root.optString("message") }
  val data = root.getJSONObject("data")
  tokenStore.save(data.getString("access_token"), data.getString("refresh_token"))
}
```

### 11.2 流式问答（简化）

```kotlin
val payload = JSONObject()
  .put("question", question)
  .put("strategy", "hybrid")
  .put("top_k", 5)
sessionId?.let { payload.put("session_id", it) }

val req = Request.Builder()
  .url("$BASE/api/v1/qa/ask")
  .addHeader("Authorization", "Bearer $accessToken")
  .addHeader("Accept", "text/event-stream")
  .addHeader("X-Guest-Id", guestId)
  .addHeader("X-Request-Id", UUID.randomUUID().toString())
  .post(payload.toString().toRequestBody("application/json".toMediaType()))
  .build()

client.newCall(req).execute().use { resp ->
  require(resp.isSuccessful)
  val source = resp.body!!.source()
  var event = "message"
  while (!source.exhausted()) {
    val line = source.readUtf8Line() ?: break
    when {
      line.startsWith("event:") -> event = line.removePrefix("event:").trim()
      line.startsWith("data:") -> {
        val data = line.removePrefix("data:").trim()
        handleSse(event, data) // chunk / citations / done / ...
      }
      line.isEmpty() -> { /* 事件结束 */ }
    }
  }
}
```

> 生产环境请使用 HTTPS，关闭明文日志中的 Token / 密码，并处理取消（用户点「停止生成」时 cancel Call）。

---

## 12. 安全与合规注意

1. **LLM Guard**：恶意或越权提问会被拒绝并审计；客户端应友好展示 `guard_blocked.message`，不要当作网络错误。  
2. **最小权限**：终端用户使用 `guest` / `staff` Token，不要把超管账号写进 App。  
3. **HTTPS**：公网部署必须 TLS；改密、登录必须加密传输。  
4. **限流**：频繁调用可能 `429`，请做指数退避。  
5. **引用展示**：回答附带 citations，建议 UI 展示文档名与相关度，并提示「请结合原文核对」。  
6. **密钥**：App 内勿硬编码管理端密钥；模型 API Key 只存在服务端。

---

## 13. 最小联调清单（第三方接入验收）

1. `GET /monitor/health` 返回 overall healthy / degraded 可接受状态  
2. `POST /auth/login` 拿到 access / refresh  
3. `GET /auth/me` 成功  
4. `POST /qa/ask` 能收到至少一个 `chunk` 与 `done`，并拿到 `session_id`  
5. 用同一 `session_id` 再问一轮，确认多轮上下文  
6. `GET /qa/sessions` 能看到该会话  
7. Token 过期后 `refresh` 成功，问答可继续  
8. 故意发送注入类问题，确认收到 `guard_blocked` 而非 500  

---

## 14. 相关文档

| 文档 | 用途 |
|------|------|
| 本文 `API_INTEGRATION_GUIDE.md` | 第三方 / 移动端接入指南（功能解说向） |
| [`API.md`](./API.md) | 全量接口字段与约束 |
| [`openapi.json`](./openapi.json) | 机器可读契约，可导入 Postman / 代码生成 |
| [`CONTRACT.md`](./CONTRACT.md) | 契约变更流程 |
| [`CLOUD_DEPLOY.md`](./CLOUD_DEPLOY.md) | 云端生产部署与安全加固 |

管理端「API 接入指南」页面展示本文内容，并内嵌同源 Swagger（`/assets/vendor/swagger-ui/index.html`）。机器调试也可打开官方 `/docs`（本机默认 `http://localhost:18080/docs`），或导入 `openapi.json`。

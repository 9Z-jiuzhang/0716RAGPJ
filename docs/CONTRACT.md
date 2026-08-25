# 接口契约说明（OpenAPI Contract）

本目录存放前后端共用的 **接口文档** 与 **OpenAPI 3.0.3 契约**，是联调的唯一事实来源。

## 文件

| 文件 | 说明 |
|------|------|
| [`openapi.json`](./openapi.json) | 机器可读契约（OpenAPI 3.0.3）。由脚本生成，请勿手工直接编辑 |
| [`API.md`](./API.md) | 中文接口文档（逐接口详解，与契约同步） |
| [`KB_FAQ.md`](./KB_FAQ.md) | 知识库 FAQ 产品说明 |
| [`API_INTEGRATION_GUIDE.md`](./API_INTEGRATION_GUIDE.md) | 第三方 / 移动端接入指南 |
| [`CLOUD_DEPLOY.md`](./CLOUD_DEPLOY.md) | 云端 / 生产部署与安全加固 |
| [`CONTRACT.md`](./CONTRACT.md) | 本文件：契约使用与变更流程 |
| [`../scripts/generate_openapi.py`](../scripts/generate_openapi.py) | 契约生成脚本（契约的**代码来源**） |

当前契约覆盖：**63 条路径 / 86 个操作 / 81 个数据模型**，涵盖认证、用户、角色、部门、大模型、知识库、文档、问答（SSE）、命中率测试、快照、审计、监控等核心模块。

> 管理端扩展模块 **Query 预处理**（`/query-processing`）、**角色缓存**（`/role-caches`）、**RAGAS**（`/ragas`）、**管理员会话分析**（`/qa/admin/sessions*`）、**问答分析**（`/monitor/analytics/*`）、**模型版本**（`/models/{id}/publish|versions|rollback`）、**敏感等级**（`/admin/sensitivity/*`、文档 `.../sensitivity`）、**知识库 FAQ**（`/faq/*`、`/admin/faq/*`）、**原 PDF 预览**（`GET /qa/documents/{id}/file`）已在运行时 API 与 `API.md` 中说明；`/monitor/metrics` 为 Prometheus 别名（隐藏于 schema）。若需写入 `openapi.json`，请在生成脚本中补充后重跑。

## 契约要点

- **Base URL（本机 Docker 默认）**：`http://localhost:9080/api/v1`（统一入口；容器与宿主机均为 `:9080`）。云端见 `CLOUD_DEPLOY.md`。
- **认证**：`Authorization: Bearer <access_token>`（JWT）。标注为 `public` 或含可选 `BearerAuth`（如 `/qa/ask`、`/qa/accessible-kbs`）的接口允许匿名/可选认证。
- **统一响应**：除 SSE、CSV 导出、Prometheus `/metrics` 外，JSON 接口统一包装为 `{code, message, data, request_id}`。
- **分页**：`data` 为 `{items, total, page, page_size}`；查询参数 `page`（默认 1），`page_size`（默认 20，部门列表 50、会话消息 50、Guard 事件 50，上限 100）。
- **SSE**：`POST /qa/ask` 返回 `text/event-stream`。常见事件：`intent` / `guard_blocked` / `route` / `query_processing` / `cache_hit` / `chunk` / `citations` / `done` /（可选）`suggested_questions` / `error`。不传 `session_id` 始终新建会话；`X-Guest-Id` 仅标识归属，不自动复用旧会话。`AskRequest.top_k` 默认 **5**；`AskRequest.rewrite_enabled` 可选覆盖全局 Query 改写；`temperature` 默认不覆盖已发布模型配置。前端引用区默认展开相关度最高的 3 段，其余折叠；图表经 `chart_refs` 懒加载（ask 路径 `images=[]`）。问题最长 **2000** 字。
- **可检索库列表**：`GET /qa/accessible-kbs`（可选认证）返回当前身份已建索引的知识库，供问答页下拉。
- **会话闲置过期**：超过 `QA_SESSION_IDLE_EXPIRE_MINUTES` 未问答 → `status=expired` 并清 Redis；历史列表仍可见；续聊携带 `session_id` 可重新激活。管理员「活跃会话」仅计 `active`。
- **文件上传**：`multipart/form-data`（字段 `file`），上限 100MB（`413`）。前端支持字节上传进度；txt/md 支持 UTF-8/GBK/UTF-16 等常见编码。
- **向量库**：Compose 使用 `chromadb/chroma:1.5.5`，与 Python `chromadb` 1.5.x 对齐（勿用 `latest`）。
- **访问控制**：知识库可见性以**部门**为主（`GUEST`=访客专用）；一个知识库可关联多个部门（表 `kb_departments`，API 字段 `departments[]`）。角色等级 `super_admin > admin > staff/guest`，仅可管理权限低于自己的用户。管理端日常授权入口为超管「组织与权限」；知识库页「访问范围」为多选（含「除访客外全选」）；部门侧关联知识库为追加写入。
- **角色权限配置**：`PUT /roles/{id}/permissions` **仅超级管理员**可调用。
- **改密**：`POST /auth/change-password`；固定超管 `super` 禁止调用，仅可通过 `.env` 的 `SUPER_ADMIN_PASSWORD` 维护。

## 使用方式

1. **Swagger UI（官方）**：服务启动后访问 http://localhost:9080/docs 。
2. **Swagger UI（管理端嵌入）**：同源静态资源 http://localhost:9080/assets/vendor/swagger-ui/index.html （目录：`frontend/shared/vendor/swagger-ui/`）。
3. **Swagger Editor / Redoc**：导入 `openapi.json` 在线预览。
4. **Postman / Insomnia**：Import → 选择 `openapi.json` 自动生成请求集合。
5. **前后端联调**：路径、请求体、响应字段、权限标识一律以本目录契约 + `API.md` 为准。
6. **第三方接入**：优先阅读 `API_INTEGRATION_GUIDE.md`（管理端「API 接入指南」页同源文档）。

## 重新生成

```bash
python scripts/generate_openapi.py
# 输出：Wrote docs/openapi.json (...bytes), paths=..., schemas=...
```

> 请勿手工编辑 `openapi.json`，否则会在下次生成时被覆盖。所有变更都应落到 `scripts/generate_openapi.py`。

## 变更流程

1. 提出契约变更（Issue / PR），前后端评审；
2. 修改 `scripts/generate_openapi.py`（schemas / paths）；
3. 运行脚本重新生成 `docs/openapi.json`；
4. 同步更新中文文档 `docs/API.md`（必要时同步 `API_INTEGRATION_GUIDE.md` 与 `frontend/shared/docs/` 副本）；
5. 评审合并后再改业务代码（**契约优先**）。

## 版本

- 契约版本：**2.1.13**，与仓库 `APP_VERSION`（`backend/app/core/config.py`、`.env.example`）及 [`API.md`](./API.md) §20 保持同步。
- 文档修订：**2026-08-23**（2.1.13 chart_refs / P2 UI、`suggested_questions` SSE 尾事件）。
- 历史修订见 `API.md` §20 变更记录。

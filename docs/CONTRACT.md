# 接口契约说明（OpenAPI Contract）

本目录存放前后端共用的 **接口文档** 与 **OpenAPI 3.0.3 契约**，是联调的唯一事实来源。

## 文件

| 文件 | 说明 |
|------|------|
| [`openapi.json`](./openapi.json) | 机器可读契约（OpenAPI 3.0.3）。由脚本生成，请勿手工直接编辑 |
| [`API.md`](./API.md) | 中文接口文档（逐接口详解，与契约同步） |
| [`CONTRACT.md`](./CONTRACT.md) | 本文件：契约使用与变更流程 |
| [`../scripts/generate_openapi.py`](../scripts/generate_openapi.py) | 契约生成脚本（契约的**代码来源**） |

当前契约覆盖：**59 条路径 / 82 个操作 / 76 个数据模型**，涵盖认证、用户、角色、部门、大模型、知识库、文档、问答（SSE）、命中率测试、快照、审计、监控共 12 个模块。

## 契约要点

- **Base URL**：`http://localhost:8080/api/v1`（统一入口）。
- **认证**：`Authorization: Bearer <access_token>`（JWT）。标注为 `public` 或含可选 `BearerAuth`（如 `/qa/ask`）的接口允许匿名/可选认证。
- **统一响应**：除 SSE、CSV 导出、Prometheus `/metrics` 外，JSON 接口统一包装为 `{code, message, data, request_id}`。
- **分页**：`data` 为 `{items, total, page, page_size}`；查询参数 `page`（默认 1）、`page_size`（默认 20，部门列表 50、会话消息 50，上限 100）。
- **SSE**：`POST /qa/ask` 返回 `text/event-stream`，事件类型 `chunk / citations / done / error`。不传 `session_id` 始终新建会话；`X-Guest-Id` 仅标识归属，不自动复用旧会话。
- **会话闲置过期**：超过 `QA_SESSION_IDLE_EXPIRE_MINUTES` 未问答 → `status=expired` 并清 Redis；历史列表仍可见；续聊携带 `session_id` 可重新激活。管理员「活跃会话」仅计 `active`。
- **文件上传**：`multipart/form-data`（字段 `file`），上限 100MB（`413`）。
- **访问控制**：知识库可见性以**部门**驱动（`GUEST`=访客专用）；角色等级 `super_admin > admin > staff/guest`，仅可管理权限低于自己的用户。
- **角色权限配置**：`PUT /roles/{id}/permissions` **仅超级管理员**可调用。

## 使用方式

1. **Swagger UI**：服务启动后访问 http://localhost:8080/docs 。
2. **Swagger Editor / Redoc**：导入 `openapi.json` 在线预览。
3. **Postman / Insomnia**：Import → 选择 `openapi.json` 自动生成请求集合。
4. **前后端联调**：路径、请求体、响应字段、权限标识一律以本目录契约 + `API.md` 为准。

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
4. 同步更新中文文档 `docs/API.md`；
5. 评审合并后再改业务代码（**契约优先**）。

## 版本

- 契约版本：`2.1.0`，与产品手册 V2.1 及仓库 `APP_VERSION` 保持同步。

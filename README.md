# AI 知识库 RAG 平台

基于大语言模型的智能知识库平台：文档上传与向量化、混合检索、多轮问答、RBAC 权限、命中率测试、快照回退与可观测性。

版本与产品手册对齐：**V2.1**（`APP_VERSION=2.1.0`）。

---

## 架构说明

```text
Browser (:8080)
    │
    ▼
nginx (reverse-proxy) ──► web (:80 静态 guest/admin)
    │
    ├── /api/*  ──► api (:8000 FastAPI)
    └── /grafana/* ──► grafana (:3001，可选)

api 依赖：
  PostgreSQL (:5432) · Redis (容器 6379 / 宿主机 16379) · Chroma (:8001)
  MinIO (:9000/:9001) · 外部 LLM / Embedding HTTP API
```

| 服务 | 宿主机端口 | 说明 |
|------|------------|------|
| 统一入口 nginx | **8080** | **推荐入口**（静态 + API 代理） |
| web 静态 | 80 | 仅静态；`/api/` 返回 501，会触发前端演示 Mock |
| api | 8000 | FastAPI /docs |
| postgres | 5432 | 主库 |
| redis | **16379→6379** | Windows 排除区含 6379，故宿主机映射 16379；容器内仍为 `redis:6379` |
| chroma | 8001 | 向量库（镜像需与客户端 0.6.x 对齐，见下文） |
| minio | 9000 / 9001 | 对象存储 |
| prometheus | 9090 | 指标 |
| grafana | 3001 | 仪表盘（可选） |
| langfuse | 3000 | 追踪（可选，需补齐 Key） |

---

## 快速开始

```bash
# 1. 复制环境变量并填写密钥（标记为 <请填写> 的项）
cp .env.example .env

# 2. 启动核心栈（建议）
docker compose up -d --build postgres redis chroma minio api web nginx prometheus

# 可选：grafana / langfuse（需 .env 中对应密钥齐全）
docker compose up -d grafana
```

| 入口 | 地址 |
|------|------|
| 统一入口 | http://localhost:8080 |
| 访客端 | http://localhost:8080/ |
| 管理端 | http://localhost:8080/admin/ |
| API Swagger | http://localhost:8080/docs 或 http://localhost:8000/docs |
| 健康检查 | http://localhost:8080/api/v1/monitor/health |

演示管理员（种子数据）：`admin` / `Admin123!`

### 禁用前端 Mock（强制真实后端）

1. **只使用** `http://localhost:8080`（不要用裸 `:80`）
2. 浏览器控制台执行后硬刷新：

```javascript
localStorage.removeItem('rag_force_demo');
sessionStorage.removeItem('rag_demo_mode');
location.reload();
```

### 本地开发（conda `lg`）

本机 `lg` 环境当前为 **Python 3.9**，本项目要求 **3.10**。推荐：

- 日常联调：Docker Compose 全栈  
- Lint/测试：在 `0716ragpj-api` 镜像（Python 3.10）内执行，或升级 `lg` 到 3.10 后：

```bash
conda activate lg   # 需 Python>=3.10
pip install -r requirements.txt
# .env 中主机改为 localhost；CHROMA_PORT=8001；REDIS 宿主机端口 16379
uvicorn app.main:app --reload --app-dir backend --port 8000
pytest backend/tests -q
```

---

## 真实环境 E2E 验证结果（禁用 Mock）

> 验证时间：2026-07-17  
> 运行时：Docker `python:3.10-slim` + `chromadb==1.5.9` + `chroma:latest`  
> 入口：`http://127.0.0.1:8000` / `8080`，密钥来自项目根目录 `.env`（真实 LLM/Embedding，非 Mock）  
> 契约依据：[`docs/API.md`](docs/API.md)（上传路径、快照 preview、`/qa/ask` SSE、索引版本可检索约束）  
> 脚本：[`scripts/e2e_real_stack.ps1`](scripts/e2e_real_stack.ps1) → [`scripts/e2e_results.json`](scripts/e2e_results.json)

| 步骤 | 结果 | 说明 |
|------|------|------|
| monitor/health | **通过** | postgres / redis / chroma healthy；整体 degraded（Langfuse Key 空） |
| auth/login + /me | **通过** | 真实 JWT（admin） |
| 知识库创建/列表 | **通过** | 对齐契约字段：`type` / `visibility` / `embedding_model` |
| 文档上传 → ready | **通过** | `POST .../documents/upload` + 异步流水线向量化成功 |
| 命中率测试 runs | **通过** | 真实 API completed |
| 快照创建 + preview | **通过** | 对齐契约 `.../snapshots`、`.../preview` |
| 问答 SSE | **通过** | 真实引用 citations + LLM 流式输出（非 Mock） |

复跑：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\e2e_real_stack.ps1
```

---

## CI 状态

文件：[`.github/workflows/ci.yml`](.github/workflows/ci.yml)

| 项 | 变更 |
|----|------|
| Ruff | 去掉 `\|\| true`，**硬失败** |
| Black | 去掉 `\|\| true`，**硬失败** |
| Pytest | 始终执行 `pytest backend/tests`（不再因「无用例」跳过） |

本地已在 API 容器内执行：

- `ruff check app` → **All checks passed**
- `black --check app` → 已对 backend 跑过 `black` 格式化

Pytest：GitHub Actions 使用自带 postgres/redis（密码 `test_password`）应与 workflow 一致。容器内跑测时需保留 Docker 服务名（`conftest.py` 已改为仅在宿主机 remap `postgres`→`localhost`）。

推送 `develop`/`main` 后请在 GitHub Actions 确认绿灯。

---

## 未接通模块 / 问题说明与排查

### 1. Chroma 客户端与服务端版本（已对齐）

- **处理**：`requirements.txt` 使用 `chromadb>=1.0,<2.0`（运行时 1.5.9），Compose 使用 `chromadb/chroma:latest`，与 **Python 3.10** API 镜像一致。
- 向量写入统一走 [`app.core.chroma`](backend/app/core/chroma.py) 单例客户端。

### 2. Redis 宿主机端口 6379 无法绑定

- **现象**：Windows 排除端口含 6379  
- **处理**：宿主机映射 **16379:6379**；容器内 API 仍访问 `redis:6379`

### 3. 文档流水线 / 索引版本（已修，对齐 docs/API.md）

- 后台任务关键字参数：`auto_vectorize=True`  
- 上传向量化后写入 `knowledge_bases.current_index_version`（无版本则 `/qa/ask` 不可检索）  
- `Document.chunks` / `Snapshot.documents` 使用 `lazy="noload"`，避免 MissingGreenlet

### 4. 全文检索 SQL（已修）

- `plainto_tsquery` 使用 `'simple'::regconfig`  
- tsvector/trgm 失败使用 savepoint，避免事务 aborted 拖垮 hybrid/问答

### 5. Langfuse

- `.env` 中 Public/Secret Key 为空 → health 中 langfuse=degraded（非阻塞）  
- 补齐后：`docker compose up -d langfuse-db langfuse-server`

### 6. Rerank / Grafana

- Rerank 未配置则跳过；Grafana 可选，nginx 使用变量 upstream，未启动也不挡 8080 主链路

### 一键查看 / 释放端口（Windows）

```powershell
$ports = 8000,8080,5432,16379,8001,9000,9001,9090,3000,3001,5433
foreach ($p in $ports) { netstat -ano | findstr ":$p " | findstr LISTENING }

# 优先用 docker stop，勿杀 com.docker.backend
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
```

---

## 前后端能力差距（待确认后再补前端代码）

活跃 UI：`frontend/guest/js/app.js`、`frontend/admin/js/app.js`。  
模块化 `admin/js/pages/*`、`admin/js/api/*` **未挂载**。

| 优先级 | 缺口 | 后端已有 |
|--------|------|----------|
| **P0** | 文档详情 / 分段规则 / 预览 / 重分段 / 规范化 / chunk 编辑 / 失败重试 | `documents.py` |
| **P0** | 命中率用例 CRUD、跑次详情、CSV 导出、多策略对比 | `hit_tests.py` |
| **P1** | KB 权限编辑、向量化进度轮询 | permissions / vectorize-status |
| **P1** | 模型创建 / 编辑 / 设默认 | `models.py` |
| **P2** | 会话改名/删除、消息反馈 | `qa.py` |
| **P2** | 用户搜索、重置密码（契约有、实现需核对） | `users` |
| — | OpenAPI 契约漂移 | `contracts/openapi.json` |

请回复确认范围：`P0` / `P0+P1` / `全部` / `本轮不写前端`。确认前**不会**继续大改前端页面。

本次已做小修复：管理端创建知识库补上 `embedding_model` 等必填字段，避免 422。

---

## 功能概览（产品手册 §5）

| 模块 | 后端 | 前端活跃 UI |
|------|------|-------------|
| 认证 / RBAC / 用户与角色 | 已实现 | 基本可用 |
| 知识库管理 | 已实现 | 列表/详情/重向量化；权限编辑缺失 |
| 文档流水线 | 已实现 | 仅列表/上传/删除 |
| 智能问答 SSE | 已实现 | 已对接（需索引就绪） |
| 命中率测试 | 已实现 | 仅简陋执行 |
| 快照 / 回退 / 审计 | 已实现 | 快照较完整；审计筛选有限 |
| 大模型配置、监控 | 已实现 | 模型仅启停；监控+Grafana |

---

## 项目结构

```
0716RAGPJ/
├── backend/                 # FastAPI
├── frontend/guest|admin|shared
├── docker/                  # Nginx / Postgres / Grafana / Prometheus
├── contracts/openapi.json
├── scripts/e2e_real_stack.ps1
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## 协作约定

- 主开发分支：`develop`；稳定发布：`main`
- Commit：Conventional Commits
- PR 需通过 CI（ruff / black / pytest）；接口变更同步契约

## 许可证

MIT

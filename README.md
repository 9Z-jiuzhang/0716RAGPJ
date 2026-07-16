# AI 知识库 RAG 平台

基于大语言模型的智能知识库平台：文档上传与向量化、混合检索、多轮问答、RBAC 权限、命中率测试、快照回退与可观测性。

版本与产品手册对齐：**V2.1**（`APP_VERSION=2.1.0`）。

## 技术栈

| 层次 | 选型 |
|------|------|
| 后端 | Python 3.10+ / FastAPI |
| 前端 | 原生 HTML / CSS / JS（访客端 + 管理端 SPA） |
| 数据 | PostgreSQL、Chroma、Redis、MinIO |
| 可观测 | Langfuse、Prometheus、Grafana |
| 部署 | Docker Compose + Nginx 统一入口 |

## 功能概览（对应产品手册 §5）

| 模块 | 状态 |
|------|------|
| 认证 / RBAC / 用户与角色 | 已实现 |
| 知识库管理（含权限、重向量化） | 已实现 |
| 文档上传 / 解析 / 分段 / 向量化 / 分段预览 | 已实现（P0 格式：PDF/DOC/DOCX/TXT/MD） |
| 智能问答（SSE、混合检索 RRF、会话记忆） | 已实现 |
| 命中率测试（含多策略对比、CSV 导出） | 已实现 |
| 快照 / 回退 / 审计 | 已实现 |
| 大模型配置、监控、限流 | 已实现 |
| OCR / 告警规则 / 商业化多租户 | 非首期（P2） |

## 快速开始

```bash
# 1. 复制环境变量并填写密钥（标记为 <请填写> 的项）
cp .env.example .env

# 2. 启动全部服务
docker compose up -d --build
```

启动后访问：

| 入口 | 地址 |
|------|------|
| 统一入口 | http://localhost:8080 |
| 访客端（问答） | http://localhost:8080/ |
| 管理端 | http://localhost:8080/admin |
| API Swagger | http://localhost:8080/docs |
| 健康检查 | http://localhost:8080/api/v1/monitor/health |
| Grafana | http://localhost:8080/grafana/ |
| Prometheus | http://localhost:9090 |
| Langfuse | http://localhost:3000 |

演示管理员（种子数据）：`admin` / `Admin123!`

### 本地开发（可选）

```bash
# 依赖
pip install -r requirements.txt

# 仅启动基础设施后，本机跑 API
# 将 .env 中 POSTGRES_HOST / REDIS_HOST 等改为 localhost
uvicorn app.main:app --reload --app-dir backend --port 8000

# 测试
pytest backend/tests -q
```

## 项目结构

```
0716RAGPJ/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/          # 路由：auth/users/roles/kb/docs/qa/hit-tests/snapshots/audit/models/monitor
│   │   ├── core/            # 配置、安全、DB、Redis、Chroma、指标、限流
│   │   ├── models/          # SQLAlchemy ORM
│   │   ├── schemas/         # Pydantic 契约
│   │   ├── services/        # 业务服务
│   │   ├── retrieval/       # 向量 / 全文 / 混合检索
│   │   ├── memory/          # 会话记忆
│   │   ├── repositories/    # 数据访问
│   │   └── middleware/      # 访问日志、限流
│   ├── tests/
│   └── alembic/             # 数据库迁移
├── frontend/
│   ├── guest/               # 访客端 SPA
│   ├── admin/               # 管理端 SPA
│   └── shared/              # 共享 JS/CSS
├── docker/                  # Nginx / Postgres / Grafana / Prometheus 等配置
├── contracts/               # OpenAPI 契约（openapi.json）
├── docs/API.md              # 中文接口说明
├── scripts/generate_openapi.py
├── docker-compose.yml       # 一键编排
├── requirements.txt
└── .env.example
```

## 文档与契约

| 文档 | 说明 |
|------|------|
| [contracts/openapi.json](contracts/openapi.json) | OpenAPI 3.0 机器契约 |
| [contracts/README.md](contracts/README.md) | 契约使用与变更流程 |
| [docs/API.md](docs/API.md) | 中文接口说明 |

前后端对接以契约为准；变更契约需同步更新 `openapi.json` 与 `docs/API.md`。

## 协作约定

- 主开发分支：`develop`；稳定发布：`main`
- 分支命名：`feature/<模块>-<简述>`、`fix/<简述>`、`docs/<简述>`
- Commit：Conventional Commits，如 `feat(qa): ...`、`fix(kb): ...`
- PR 需通过 CI（ruff / black / pytest）；接口变更必须更新契约文档

## 许可证

MIT

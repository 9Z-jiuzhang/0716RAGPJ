# AI 知识库 RAG 平台

基于大语言模型的智能知识库平台，支持多格式文档管理、语义检索和多轮对话问答。

## 技术栈

- Python 3.10 + FastAPI
- PostgreSQL + Chroma + Redis + MinIO
- Docker Compose 一键编排
- 前端：原生 HTML / CSS / JS（访客端 + 管理端）

## 快速开始

```bash
# 1. 复制环境变量模板
cp .env.example .env

# 2. 填写 .env 中的密钥与密码（标记为 <请填写> 的项）

# 3. 启动全部服务
docker compose up -d
```

启动后访问：

| 入口 | 地址 |
|------|------|
| 统一入口 | http://localhost:8080 |
| 访客端 | http://localhost:8080/ |
| 管理端 | http://localhost:8080/admin |
| API 文档（Swagger，待后端实现后可用） | http://localhost:8080/docs |
| 契约文件 | [contracts/openapi.json](contracts/openapi.json) |
| 中文接口说明 | [docs/API.md](docs/API.md) |

## 项目结构

```
0716RAGPJ/
├── backend/                 # FastAPI 后端（业务代码待实现）
│   ├── app/
│   │   ├── api/v1/          # API 路由
│   │   ├── core/            # 配置、安全、依赖注入
│   │   ├── models/          # ORM 模型
│   │   ├── schemas/         # Pydantic 契约
│   │   ├── services/        # 业务逻辑
│   │   ├── repositories/    # 数据访问
│   │   ├── middleware/      # 中间件
│   │   └── utils/           # 工具函数
│   ├── tests/
│   └── alembic/             # 数据库迁移
├── frontend/                # 前端静态资源（页面待实现）
│   ├── guest/               # 访客端
│   ├── admin/               # 管理端
│   └── shared/              # 共享样式与脚本
├── docker/                  # 容器与中间件配置
├── contracts/               # OpenAPI 接口契约
├── docs/                    # 团队文档（含中文 API 说明）
└── data/                    # Docker 数据卷（不入库）
```

## 团队协作

1. 克隆仓库后复制 `.env.example` 为 `.env` 并填写密钥
2. **前后端并行开发以契约为准**：`contracts/openapi.json` + `docs/API.md`
3. 契约变更需团队评审后再修改
4. 开发规范见 [CONTRIBUTING.md](CONTRIBUTING.md)

## 当前阶段说明

本仓库当前为**项目框架与接口契约**阶段：

- 已提供完整目录、环境模板、Docker/CI 配置与 OpenAPI 契约
- **尚未实现**后端业务代码与前端页面，由团队按模块认领开发

## 许可证

MIT

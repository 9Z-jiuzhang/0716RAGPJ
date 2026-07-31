# 云端部署指南

本文说明如何把本知识库 RAG 平台部署到云主机 / 容器服务，并与本地联调配置区分开。

配套文件：

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | 本机开发（热重载、业务栈端口 9xxx） |
| `docker-compose.langfuse.yml` | 自建 Langfuse 独立栈（ClickHouse + 独立 PG/Redis/MinIO） |
| `docker-compose.prod.yml` | 云端覆盖（关热重载、数据面不暴露、加固默认） |
| `.env` / `.env.example` | 密钥、`DEPLOYMENT_MODE`、Langfuse 自建变量 |
| `docs/API_INTEGRATION_GUIDE.md` | 第三方 / App 接入 |

---

## 1. 架构建议

```text
Internet → 云负载均衡 (HTTPS)
        → 本机 Nginx 容器（宿主机 :9080）—— 业务唯一对公入口
             ├─ /          → web（静态前端 :9082）
             ├─ /api/      → api（FastAPI :9081，SSE 关闭缓冲）
             ├─ /docs      → api Swagger
             └─ /grafana/  → grafana (:9300)
        → Langfuse Web（宿主机 :9310）—— 追踪 UI / Public API
        内网 Docker 网络 kb-network：
             业务：postgres:9543 / redis:9637 / chroma:8000（宿主机映射 9800） / minio:9900 / prometheus:9909
             Langfuse：langfuse-postgres:9544 / langfuse-redis:9638 /
                       langfuse-minio:9910 / langfuse-clickhouse:9812|9000 /
                       langfuse-worker:9330
```

本机与云端宿主机映射均落在 **9000–9999**。云端 prod 通常只对外暴露 **9080**（业务）与 **9310**（Langfuse）。

- **不要**把业务 Postgres、Redis、Chroma、MinIO、API:9081、Grafana、ClickHouse 等数据面直接映射到公网（prod 已 `ports: []`）。
- TLS 优先在云 LB 终止，并转发 `X-Forwarded-Proto=https`。
- 前端已使用相对路径 `/api/v1`，换域名一般无需改打包产物。
- 业务 API 默认 `LANGFUSE_HOST=http://langfuse-web:9310`（容器内互访）。

---

## 2. 环境变量（云端必填）

在 `.env` 中至少设置：

```env
DEPLOYMENT_MODE=cloud
PUBLIC_BASE_URL=https://kb.example.com
CORS_ORIGINS=https://kb.example.com
CORS_ALLOW_CREDENTIALS=false

SECRET_KEY=<强随机>
JWT_SECRET_KEY=<强随机>
SUPER_ADMIN_PASSWORD=<强密码>
SUPER_ADMIN_SYNC_PASSWORD=true
SEED_DEMO_USERS=false
AUTH_REGISTER_ENABLED=false
METRICS_PUBLIC=false

POSTGRES_PASSWORD=<强密码>
REDIS_PASSWORD=<强密码>
MINIO_ACCESS_KEY=<...>
MINIO_SECRET_KEY=<...>
GRAFANA_ADMIN_PASSWORD=<...>

LLM_API_KEY=<...>
EMBEDDING_API_KEY=<...>

# Langfuse 自建（完整列表见 .env.example）
LANGFUSE_HOST=http://langfuse-web:9310
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_NEXTAUTH_URL=https://kb.example.com:9310
LANGFUSE_NEXTAUTH_SECRET=<强随机>
LANGFUSE_SALT=<...>
LANGFUSE_ENCRYPTION_KEY=<64位 hex，openssl rand -hex 32>
LANGFUSE_POSTGRES_PASSWORD=<...>
LANGFUSE_REDIS_AUTH=<...>
LANGFUSE_MINIO_PASSWORD=<...>
LANGFUSE_CLICKHOUSE_PASSWORD=<...>
LANGFUSE_INIT_USER_PASSWORD=<...>
```

说明：

| 变量 | 含义 |
|------|------|
| `DEPLOYMENT_MODE=cloud` | 启动时校验弱密钥 / CORS / PUBLIC_BASE_URL，不通过则拒绝启动 |
| `SUPER_ADMIN_SYNC_PASSWORD` | 首次部署可 `true`；稳定后改为 `false` |
| `REDIS_PASSWORD` | 与 `docker-compose.prod.yml` 中业务 Redis `--requirepass` 一致 |
| `LANGFUSE_INIT_*` / `LANGFUSE_PUBLIC_KEY` | 首次启动自动建组织/项目，密钥需与 API 侧一致 |

首次启动成功并确认能用 `super` 登录后，建议将 `SUPER_ADMIN_SYNC_PASSWORD=false`。

---

## 3. 启动命令

```bash
# 构建并启动（业务 + Langfuse + 生产覆盖）
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml -f docker-compose.prod.yml --env-file .env up -d --build

# 查看 API 日志（确认未因安全检查失败）
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml -f docker-compose.prod.yml logs -f api

# 健康检查（经统一入口）
curl -fsS http://127.0.0.1:9080/api/v1/monitor/health
# Langfuse
curl -fsS http://127.0.0.1:9310/api/public/health
```

本机开发：

```bash
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d --build
```

---

## 4. 安全组 / 防火墙

仅放行：

- **9080**（业务统一入口；若前方有 LB，可仅放行 LB → 主机）
- **9310**（Langfuse UI / Public API）
- 若终止 TLS 在 LB：对外 443，回源到 9080/9310

不要对公网开放：`9543`、`9637`、`9800`、`9900/9901`、`9909`、`9300`、`9544`、`9638`、`9910`、`9812`、`9000`（ClickHouse native）等。

---

## 5. 数据持久化

Compose 默认把数据挂在项目下 `./data/*` 与 `./data/langfuse/*`。云端请：

1. 把 `./data` 放到云盘挂载点，或改 volume 为命名卷 / 云存储；
2. 定期备份业务 Postgres、业务 MinIO，以及 Langfuse Postgres / ClickHouse / MinIO；
3. 滚动升级前先 `docker compose ... down` 再 up，避免半写状态。

---

## 6. 上线检查清单

1. `DEPLOYMENT_MODE=cloud` 下 API 能启动（弱密钥会直接失败）  
2. `http(s)://域名:9080/` 打开落地页；`/admin/` 打开管理端  
3. `http(s)://域名:9310/` 打开 Langfuse，可用 `LANGFUSE_INIT_USER_*` 登录  
4. 登录业务 `super`，改掉演示习惯口令依赖  
5. `POST /api/v1/auth/register` 返回 403（若已关闭注册）  
6. 流式问答 SSE 正常；健康检查中 `langfuse` 为 healthy/degraded（有密钥时期望 healthy）  
7. Grafana 仅登录后可用（生产关闭匿名）  
8. `/metrics` 对公网 404（`METRICS_PUBLIC=false`）  
9. 安全组无数据库 / 向量 / 对象存储端口  

---

## 7. 与本地差异摘要

| 项 | 本地 compose | 云端 prod 覆盖 |
|----|--------------|----------------|
| API | `--reload` + 源码挂载 | workers、无挂载 |
| 端口 | 多端口 9xxx 便于调试 | 仅暴露 9080 + 9310 |
| Redis | 业务 Redis 无密码 | requirepass |
| Grafana | 可匿名嵌入 | 关匿名，ROOT_URL=PUBLIC_BASE_URL |
| Langfuse | 自建独立栈 | 同左；MinIO 等数据面不暴露 |
| 演示账号 | 默认播种 | 不播种 |
| 注册 | 默认开放 | 默认关闭 |

更细的接口说明见 `API_INTEGRATION_GUIDE.md` 与 `API.md`。

# 云端部署指南

本文说明如何把本知识库 RAG 平台部署到云主机 / 容器服务，并与本地联调配置区分开。

配套文件：

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | 本机开发（热重载、多端口暴露） |
| `docker-compose.prod.yml` | 云端覆盖（关热重载、不暴露数据面端口、加固默认） |
| `.env` / `.env.example` | 密钥与 `DEPLOYMENT_MODE` 等 |
| `docs/API_INTEGRATION_GUIDE.md` | 第三方 / App 接入 |

---

## 1. 架构建议

```text
Internet → 云负载均衡 (HTTPS:443)
        → 本机 Nginx 容器（宿主机 :80 → 容器 :8080）—— 唯一对公入口
             ├─ /          → web（静态前端）
             ├─ /api/      → api（FastAPI，SSE 关闭缓冲）
             ├─ /docs      → api Swagger
             └─ /grafana/  → grafana
        内网 Docker 网络：
             postgres / redis / chroma / minio / prometheus
```

本机开发默认映射为宿主机 **18080→8080**；云端 prod 覆盖通常只暴露 **80**（再由云 LB 做 HTTPS）。

- **不要**把 Postgres、Redis、Chroma、MinIO、API:8000、Grafana 直接映射到公网。
- TLS 优先在云 LB 终止，并转发 `X-Forwarded-Proto=https`。
- 前端已使用相对路径 `/api/v1`，换域名一般无需改打包产物。

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
```

说明：

| 变量 | 含义 |
|------|------|
| `DEPLOYMENT_MODE=cloud` | 启动时校验弱密钥 / CORS / PUBLIC_BASE_URL，不通过则拒绝启动 |
| `SUPER_ADMIN_SYNC_PASSWORD` | 首次部署可 `true` 把超管密码写入 DB；稳定后改为 `false` 避免每次重启强制覆盖 |
| `SEED_DEMO_USERS=false` | 不自动创建 `admin` / `staff_*` 演示账号 |
| `AUTH_REGISTER_ENABLED=false` | 关闭公开注册，仅后台建号 |
| `REDIS_PASSWORD` | 与 `docker-compose.prod.yml` 中 Redis `--requirepass` 一致 |

首次启动成功并确认能用 `super` 登录后，建议将 `SUPER_ADMIN_SYNC_PASSWORD=false`。

---

## 3. 启动命令

```bash
# 构建并启动（生产覆盖）
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build

# 查看 API 日志（确认未因安全检查失败）
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api

# 健康检查（经统一入口）
curl -fsS https://kb.example.com/api/v1/monitor/health
```

本机开发仍用：

```bash
docker compose up -d
```

---

## 4. 安全组 / 防火墙

仅放行：

- `80` / `443`（或仅 LB → 主机的内网端口）

不要对公网开放：`5432`、`6379/16379`、`8000/18000`、`9000`、`9090`、`3000/3001`、Chroma 端口等。

---

## 5. 数据持久化

Compose 默认把数据挂在项目下 `./data/*`。云端请：

1. 把 `./data` 放到云盘挂载点，或改 volume 为命名卷 / 云存储；
2. 定期备份 Postgres 与 MinIO；
3. 滚动升级前先 `docker compose ... down` 再 up，避免半写状态。

---

## 6. 上线检查清单

1. `DEPLOYMENT_MODE=cloud` 下 API 能启动（弱密钥会直接失败）  
2. `https://域名/` 打开访客端，`/admin/` 打开管理端  
3. 登录 `super`，改掉演示习惯口令依赖（`.env` 中的超管密码）  
4. `POST /api/v1/auth/register` 返回 403（若已关闭注册）  
5. 流式问答 SSE 正常（LB 需支持长连接、关闭缓冲）  
6. Grafana 仅登录后可用（生产关闭匿名）  
7. `/metrics` 对公网 404（`METRICS_PUBLIC=false`）  
8. 安全组无数据库端口  

---

## 7. 与本地差异摘要

| 项 | 本地 compose | 云端 prod 覆盖 |
|----|--------------|----------------|
| API | `--reload` + 源码挂载 | workers、无挂载 |
| 端口 | 多端口映射便于调试 | 仅暴露 nginx 80 |
| Redis | 无密码 | requirepass |
| Grafana | 可匿名嵌入 | 关匿名，ROOT_URL=PUBLIC_BASE_URL |
| 演示账号 | 默认播种 | 不播种 |
| 注册 | 默认开放 | 默认关闭 |

更细的接口说明见 `API_INTEGRATION_GUIDE.md` 与 `API.md`。

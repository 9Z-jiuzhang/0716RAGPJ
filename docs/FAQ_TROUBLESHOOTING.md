# FAQ / 缓存排障说明

## FAQ 命中仍很慢

### 症状
- 点击热门问题仍等待数秒以上
- SSE `done.performance.stages_ms` 中仍有较大的 `llm_guard`

### 原因
- 旧版本在 FAQ 查找前执行完整 LLM Guard（约 3–5 秒）

### 期望行为（稳定化修复包后）
- FAQ active 命中路径：仅本地规则护栏 + FAQ lookup，`llm_guard` 阶段应接近 0 / 不出现
- 未命中 FAQ 的恶意问题仍走完整 `llm_guard` 并可能 `guard_blocked`

---

## FAQ 修改后仍返回旧答案

### 症状
- 管理端改 FAQ 答案后，访客立即点击同一热门题仍是旧答案

### 原因
- FAQ Redis 短时缓存未主动失效（TTL 约 15 分钟）

### 处理
- 稳定化修复包后：update / batch / disable / reject / 重生会按 `kb_id` scan 删除 `kb:faq:v1:{tenant}:{kb_id}:*`
- 若仍异常：检查 Redis 是否可达，以及 API 日志中是否有 `faq redis invalidate failed`

---

## 迁移脚本找不到

```bash
docker exec -it <api容器> python /app/scripts/migrate_role_cache_to_kb.py
```

本地 compose 已挂载 `./scripts:/app/scripts:ro`。若仍报 No such file，确认宿主机存在该脚本并重建 api 容器。

---

## PostgreSQL 密码认证失败

### 症状
- API 启动失败 / 502
- 日志含 `password authentication failed` / `InvalidPasswordError`

### 原因
- `.env` 中 `POSTGRES_PASSWORD` 与已有 Postgres 数据卷密码不一致（环境变量只在首次初始化生效）

### 解决方案
1. 手动同步密码（保留数据）：
   ```bash
   docker exec <postgres容器> psql -U kb_user -d knowledge_base -c "ALTER USER kb_user PASSWORD '<新密码>';"
   ```
2. 重置数据卷（会丢数据）：
   ```bash
   docker compose down -v && docker compose up -d
   ```

入口脚本与 API lifespan 会打印上述中文说明；**不会**自动 `ALTER USER`。

---

## Langfuse 无 Trace / 大量 error

### 症状
- API 日志持续 `ERROR | langfuse | Unexpected error occurred`
- 健康检查 langfuse unhealthy；面板无数据

### 原因
- 云版需有效 Key 与网络；自建未启动；或配置了不可达 HOST

### 解决方案

**方案 A：禁用（开发环境推荐）**

在 `.env` 中注释：

```bash
# LANGFUSE_HOST=
# LANGFUSE_PUBLIC_KEY=
# LANGFUSE_SECRET_KEY=
```

**方案 B：自建**

```bash
docker compose -f docker-compose.langfuse.yml up -d
# LANGFUSE_HOST=http://langfuse-web:9310  （API 容器内）
```

**方案 C：云版**

```bash
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
```

---

## /metrics 无 faq_ 指标

### 处理
- 至少触发一次 FAQ 命中后再查：`curl -s localhost:9081/metrics | grep faq_`
- 指标不含高基数 `kb_id` label；按库统计请用管理端 `GET /api/v1/admin/faq/stats?kb_id=`

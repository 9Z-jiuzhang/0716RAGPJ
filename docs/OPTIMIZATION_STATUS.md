# 六维核查优化 — 实现状态（与代码同步）

> 对照实施计划文档包 [`0716RAGPJ_六维核查修订版文档包/`](../0716RAGPJ_六维核查修订版文档包/)（尤其 `00_六维核查修订版总体优化计划.md`）。  
> 本文描述**当前仓库已落地能力**；高风险能力默认开关关闭，开启后即可生效。

最后核对日期：2026-07-25。

## 总览

| Wave | 主题 | 状态 |
|------|------|------|
| W0 | 功能开关、DTO、错误码、Redis Key、契约测试 | **已完成** |
| W1 | TopK=3 / Rewrite 默认关、问答事件与反馈 | **已完成** |
| W2 | 业务路由、上一答案变换、追问 | **已完成**（访客端仅轻提示，不展示完整流水线） |
| W3 | 模型参数类型化、发布/版本/回滚 API + 管理端 | **已完成**（需 `MODEL_CONFIG_REGISTRY_V2_ENABLED=true`） |
| W4 | Session V2、L1–L4 缓存、0.80 语义门控 | **已完成（默认保守）** |
| W5 | 多副本样例、Scheduler、有界并发、队列观察入队 | **已完成（默认保守）** |
| W6 | VectorStorePort、统计图表、主题粗聚类 | **已完成（默认 chroma 读）** |

### 计划内故意保留的默认

- `VECTOR_READ_PROVIDER=chroma`：不切阿里云生产读；`AlibabaAdapter` 为能力矩阵桩。
- `QA_SEMANTIC_CACHE_OBSERVE_ONLY=true`：语义直答先观察；无独立语义索引时候选为空，不短路。
- `SESSION_STORE_V2_ENABLED=false`：开启后为 PG 事实源上的 Redis 双写，读路径仍以 V1 为主。
- `QA_EXACT_CACHE_ENABLED` / `QA_SEMANTIC_CACHE_ENABLED` / `QA_RETRIEVAL_CACHE_ENABLED` / `QA_QUEUE_ENABLED` / `SCHEDULER_EXTERNAL_ENABLED` 默认 `false`。
- 主题簇为关键词粗聚类（`keyword-v1`），非向量 Collection 终态聚类。

## 功能开关一览

见 `.env.example`「六维优化功能开关」段与 `backend/app/core/config.py`。

## 管理端入口

| 页面 | 路径 | 内容 |
|------|------|------|
| 系统监控 | `#/admin/monitor` | 健康检查、系统统计、Grafana |
| 问答统计 | `#/admin/qa-analytics` | 反馈环形图、14 日趋势、路由/缓存分布、主题分布与重建 |
| 大模型管理 | `#/admin/models` | 连接信息、配置参数、版本列表、发布/回滚（注册表开关开启时） |

## 关键代码入口

- 流水线：`backend/app/core/qa_pipeline.py`
- 路由：`backend/app/services/conversation_router.py`
- 多级缓存：`backend/app/services/qa_cache.py`
- 向量端口：`backend/app/services/vector_port.py` ← `retrieval/vector.py`
- 事件/主题：`analytics_events.py`、`topic_analytics.py`、`api/v1/monitor.py`
- 并发/队列：`model_concurrency.py`、`qa_queue.py`、`docker-compose.scale.yml`、`worker_scheduler.py`

## 验收速查（摘自计划必测）

| 用例 | 期望 |
|------|------|
| 「你好」 | 不进知识库检索（路由模板） |
| 「简略一点」 | 基于上一答案变换，不重检索 |
| 默认 TopK / Rewrite | Ask 与命中测试默认 TopK=3；Rewrite 默认关 |
| 温度 | 普通请求不覆盖已发布/环境模型配置（注册表开启并有快照时） |
| 语义直答 | ≥0.80 + 分差/质量/权限门控；观察模式不短路 |
| Redis 故障 | 缓存查找失败降级为未命中，问答可继续 |
| 向量读 | 经 `VectorStorePort`，默认 Chroma |

## 已知边界（非阻塞）

1. L3 语义候选需外部索引注入；当前流水线传入空列表，观察日志可开。
2. Session V2 未做读切流；生产可维持 V1。
3. QA 队列开启后仅观察入队，不替代同步 SSE 生成（无独立消费 Worker）。
4. 业务写向量仍走文档流水线 / `chroma_store`；读路径已端口化。
5. Alembic 区间 `a100–d499` 未单独落文件；表结构由启动期 `ensure_schema_patches` 补齐。

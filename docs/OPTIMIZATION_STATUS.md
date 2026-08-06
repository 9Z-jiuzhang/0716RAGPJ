# 六维核查优化 — 实现状态（与代码同步）

> 本文描述**当前仓库已落地能力**；高风险能力默认开关关闭，开启后即可生效。  
> 外部「六维核查修订版」计划文档包不在本仓库内；以本文与 `.env.example` / `config.py` 为准。

最后核对日期：2026-08-06（含端口 9xxx、自建 Langfuse、Chroma `0.6.3` 固定、问答页 rewrite/kb 可选与上传进度）。

## 总览

| Wave | 主题 | 状态 |
|------|------|------|
| W0 | 功能开关、DTO、错误码、Redis Key、契约测试 | **已完成** |
| W1 | Ask 默认 TopK=5 / Rewrite 默认关、问答事件与反馈 | **已完成** |
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
| 默认 TopK / Rewrite | Ask/`QA_DEFAULT_TOP_K`=**5**；命中测试默认 TopK=**3**；Rewrite 默认关；跟进问有效 TopK≥`QA_FOLLOWUP_TOP_K`(5)；访客端引用区默认展开相关度最高 3 段、其余折叠 |
| 多轮追问连贯 | 跟进问合并上轮 citations 为粘性证据（`QA_STICKY_EVIDENCE_ENABLED`）；不得称上轮为「幻觉」 |
| 会话历史 vs 答案缓存 | Redis 会话上下文仅供指代；精确/语义/角色缓存另计，默认关 |
| 未命中 / 元问题 | `SYSTEM_MECHANISM` 模板拒答；`QA_FALLBACK_LLM_ENABLED` **默认 false**（优先拒答，不写通用参考长文） |
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
6. **会话历史 ≠ 知识库证据**：粘性证据只合并上轮已引用分段，不会把 Redis 全文当 KB；首轮仍完全依赖检索召回。
7. **未命中默认拒答**：`QA_FALLBACK_LLM_ENABLED=false`；系统运行机制类问题走 `SYSTEM_MECHANISM` 模板，不进检索、不写通用 RAG 说明。

## 多轮粘性证据（2026-07-25）

- 开关：`QA_STICKY_EVIDENCE_ENABLED` / `QA_FOLLOWUP_TOP_K` / `QA_NEIGHBOR_CHUNKS_ENABLED`（见 `.env.example`）。
- 实现：`backend/app/services/sticky_evidence.py`，接入 `qa_pipeline` 检索后、生成前。
- `retrieval_meta` 可含 `sticky_chunk_ids`、`effective_top_k`、`neighbor_chunk_ids`。

## 未命中拒答（2026-07-25）

- 路由：`SYSTEM_MECHANISM` / 扩面 `SYSTEM_HELP` / `OUT_OF_SCOPE`（`conversation_router.py` rules-v2）。
- 兜底：`_stream_no_evidence_answer` 按意图分策；仅白名单意图且显式开启 `QA_FALLBACK_LLM_ENABLED` 才写 LLM 参考答。
- `retrieval_meta.fallback_mode`：`notice_only` | `template_refuse` | `llm_reference` | …

## 知识库多部门访问（2026-07-25）

与六维开关无关的产品能力，已与主线一并落地：

| 项 | 说明 |
|----|------|
| 数据模型 | 权威表 `kb_departments`（`kb_id` × `department_code`）；`knowledge_bases.department` 为兼容首选列（含 GUEST 优先） |
| API | 创建/更新支持 `departments[]`；仍接受单值 `department`；响应同时返回 `departments` 与 `department` |
| 可见性 | 关联列表含 `GUEST` → `public`，否则 `restricted` |
| 部门侧 | `POST .../knowledge-bases` **追加**关联；`DELETE` 仅解除本部门；删除部门时其它部门对同一库的关联保留 |
| 管理端 | 知识库「访问范围」多选；快捷操作「除访客外全选」/「清空」 |
| 检索/鉴权 | `retrieval/scope.py`、`assert_kb_access`、列表过滤均按多部门判断 |
| 回填 | 启动 `seed_departments` 将历史单部门字段幂等写入 `kb_departments` |
| 测试 | `backend/tests/test_kb_multi_departments.py` |

## 反馈率口径（2026-07-27）

| 项 | 说明 |
|----|------|
| 问题 | 旧口径用「近 N 日反馈条数 / 近 N 日问答事件」，补评旧回答会使反馈率 >100% |
| 现行 | `feedback_rate = matched_feedback / answerable_events`（窗口内带 `message_id` 的问答中已反馈占比，钳制 ≤1） |
| 有用/无用 | 仍按反馈 `created_at` 统计近 N 日活动量 |
| 前端 | 首页/问答统计展示钳制 0–100%；hover 说明口径 |
| 测试 | `backend/tests/test_analytics_feedback.py` |

## 前端体验补强（ZYUI-develop-ui-0725，2026-07-25）

| 端 | 要点 |
|----|------|
| 管理端 | 列表全量拉取 + 本地分页；用户排序/部门筛选/深链高亮；首页反馈 KPI；部门列宽与图表贴底 |
| 访客端 | 流式回答「中止」；顶栏历史/收藏；本机收藏清理；未知路由 404 卡片 |
| 共享 | `askStream` 401 refresh 重试；`formatStatNumber` |

## 落地页与品牌（ZYUI-V3.1 / V3.2，2026-07-27）

纯前端体验，无 API / 契约变更：

| 版本 | 要点 |
|------|------|
| V3.1 | `/` 改为营销落地页 + 环境粒子场；登录/注册以弹层打开（直链 `#/login` / `#/register` 仍可自动弹出） |
| V3.2 | 左右分栏（左宣言 / 右预览）；副标题打字机轮播；CTA「立即登录」「访客登录」；9Z logo；`brand-mark.js` 落地页与管理端侧栏共用（localStorage 同步构图） |
| 共享资源 | `frontend/shared/js/env-particle-field.js`、`brand-mark.js`、`img/logo-9z.png` |
| 验证 | 本机入口 http://localhost:9080/ ；硬刷新以绕过 CSS/JS cache-bust |

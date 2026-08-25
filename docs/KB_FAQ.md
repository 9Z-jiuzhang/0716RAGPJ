# FAQ 知识库缓存

库级 FAQ 是 RAG 加速层：文档向量化 `ready` 后**异步**生成 FAQ，按知识库隔离缓存。  
**FAQ 命中 ≠ 当场完整 RAG**；答案为预计算结果。答案校验（A4-a）只告警过时，不自动覆盖。

角色缓存（`/role-caches`）过渡期**只读 + 密级补检**。接口摘要见 [`API.md`](API.md) §12.1。

## 命中优先级

1. 本地规则护栏（完整 LLM Guard 在 FAQ 未命中后执行）
2. **知识库 FAQ 精确命中**（`normalized_question` + Redis 短时缓存）
3. **知识库 FAQ 语义命中**（问题 embedding 与 FAQ `embedding` 余弦 ≥ `FAQ_SIMILARITY_THRESHOLD`，默认 0.85；需 `FAQ_SEMANTIC_HIT_ENABLED=true`）
4. **多级 QA 缓存 L2/L3**（L2 键含 `user_max_level`；L3 可注入 FAQ 近义候选，默认观察态）
5. 原 RAG

角色缓存（`/role-caches`）**退场中**：`ROLE_CACHE_SHADOW_METRICS_ENABLED=true` 时只观测命中、不短路；shadow 窗口结束后读路径自动关闭。过渡期接口仍只读 + 密级补检。

密级不足：FAQ 精确/语义明确拒答；后续链路按 L2/L3/RAG 继续。

## 能力摘要

| 能力 | 说明 |
|------|------|
| 精确命中 | 规范化同题秒答；点选热门与手输同题相同 |
| 语义命中 | upsert/编辑写 `embedding`；精确 miss 后近义命中 |
| 答案校验 | 文档 ready / 日 hit 达标入队；标 `rag_drift` + `pending_review`；审计 `faq_verify_stale`；**不覆盖答案** |
| 敏感闸门 | 生成时问题/答案命中 `FAQ_SENSITIVE_PATTERNS`（手机/身份证/薪资/报销额度等）→ `pending_review`，须人工 approve 才秒答；**不自动升密级**；**不回溯**已 active 的旧 FAQ |
| 密级 | FAQ / 文档 API / QA 缓存键 / 角色缓存命中均做密级门控；授权只信 DB（FAQ 行 / 文档 / 分段），不信向量 metadata |
| 缓存回查 | FAQ Redis 命中后回查 `kb_cached_faqs`；QA L2 命中后按引用 `doc_id` 回查文档密级，不达标则丢缓存重走链路 |
| 快照 | `snapshot_faqs` 可回退还原 FAQ |

## 配置（节选）

| 项 | 默认 | 说明 |
|----|------|------|
| `FAQ_REDIS_CACHE_TTL_SECONDS` | 900 | FAQ 精确命中 Redis TTL |
| `FAQ_SENSITIVE_PATTERNS` | 见 `config.py` | JSON 正则数组；命中 → `pending_review`（不自动升密、不回溯旧 FAQ） |
| `FAQ_SIMILARITY_THRESHOLD` | 0.85 | 生成去重 + FAQ 语义命中阈值 |
| `FAQ_SEMANTIC_HIT_ENABLED` | true | 语义命中开关 |
| `FAQ_SEMANTIC_CANDIDATE_LIMIT` | 200 | 语义候选扫描上限 |
| `FAQ_VERIFY_ENABLED` | true | 答案校验调度 |
| `FAQ_VERIFY_HIT_THRESHOLD` | 5 | 日批校验 hit 下限 |
| `FAQ_VERIFY_DAILY_SCAN_ENABLED` | false | 全库日扫默认关 |
| `FAQ_VERIFY_DAILY_LIMIT` | 200 | 日校验条数上限 |
| `FAQ_VERIFY_ON_DOCUMENT_READY` | true | 文档 ready 后触发相关 FAQ 校验入队 |
| `QA_SEMANTIC_CACHE_OBSERVE_ONLY` | true | L3 默认观察不短路 |
| `ROLE_CACHE_READONLY_FALLBACK` | true | 角色缓存只读回退 |
| `ROLE_CACHE_SHADOW_METRICS_ENABLED` | false | Shadow 观测（不短路） |
| `ROLE_CACHE_SHADOW_DAYS` | 14 | Shadow 窗口天数 |

完整项见仓库根目录 `.env.example` 中 `FAQ_*` / `ROLE_CACHE_*`。

## 管理端

- FAQ 列表：`rag_drift` 显示过时标记；详情可看 `verify_diff`、模拟问答对照
- FAQ 详情：**编辑**（非仅查看）→ 校验面板「填入上方答案框」→ **保存** 可清除 `rag_drift`
- 文档列表：`faq_job_status` / `faq_job_reason`（空文、无 Key、限额等）

## 说明

- 旧 FAQ 若 `embedding` 为空，语义命中不会生效，需编辑触发刷新或重新生成。
- 改文档密级：`PUT .../documents/{id}/sensitivity` 同步分段 + 关联 FAQ 取源文档最高密级，并失效该库 FAQ Redis / QA L2；响应含 `sync` 计数。
- 不自动回填答案、不整删角色缓存（另开需求）。
- 问答引用图表：`citations.chart_refs[]` 为懒加载元数据（PDF 页或内嵌 asset）；前端按需 `GET /charts/` / `GET /assets/`；原 PDF 预览 `GET /qa/documents/{id}/file`（可 `#page=N`）；ask 路径 `images=[]`。见 README §2.5、`docs/API.md` §10。

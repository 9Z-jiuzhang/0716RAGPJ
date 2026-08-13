# FAQ 知识库缓存（Cache V2.0 / 一期夯实）

> 分支标记：`ZY_Cache_V2.0`。一期目标：按知识库缓存、上传后自动生成、访客热门点选秒答、精确同题复用。  
> 二期验收清单见 [`FAQ_PHASE2_ACCEPTANCE.md`](FAQ_PHASE2_ACCEPTANCE.md)。排障见 [`FAQ_TROUBLESHOOTING.md`](FAQ_TROUBLESHOOTING.md)。

## 概述

知识库 FAQ 是 RAG 的加速层：文档向量化就绪后**异步**生成 FAQ，按 `kb_id + normalized_question` **精确命中**，跳过 Embedding / 检索 / LLM。

角色缓存（`/role-caches`）已停写，仅作过渡期只读回退；管理端入口为 **知识库 FAQ**。

## 一期已落地能力

| 能力 | 状态 | 说明 |
|------|------|------|
| 按知识库缓存 | ✅ | 表 `kb_cached_faqs`，唯一键 `(kb_id, normalized_question)` |
| 上传后自动生成 | ✅ | 文档 `ready` 后入队；上传 UI 在向量化完成后即结束，FAQ 后台继续 |
| 扩大条数 | ✅ | 默认每文档 25 / 每库 500（可配置） |
| 精确同题同答 | ✅ | 规范化后完全同题秒答；点选热门与手输同文案一致 |
| 访客热门点选 | ✅ | `GET /faq/list`；点选不经模型长思考 |
| 密级门控（FAQ） | ✅ | 命中与热门列表按 `user_max_level` 过滤/拒答 |
| 管理端审编 | ✅ | 列表/编辑/批量/密级/重生/库级开关 |
| 快照含 FAQ | ✅ | `snapshot_faqs`；回退还原 FAQ，重建时 `skip_faq_generation` |
| 文档删除剪枝 FAQ | ✅ | `prune_by_document` + Redis/QA 缓存失效 |

## 命中链路

1. 安全护栏（本地规则；完整 LLM Guard 在 FAQ 未命中后）
2. 知识库 FAQ：`normalized_question` **精确同题**即秒答；`explicit_faq_click` 仅作前端体验与观测标记
3. Redis 短时精确缓存（TTL 默认 900s）
4. 数据库 `kb_cached_faqs`（仅 `active` + `is_active`，且 `kb.faq_enabled`）
5. 越权校验：`faq.kb_id ∈ authorized_kb_ids`；密级不足则明确拒答
6. 未命中 → 多级 QA 缓存 → 角色缓存只读回退 → 原 RAG

## 生成链路

文档 `ready` 后异步入队，不阻塞就绪状态。空文档 / 扫描件 / 无 LLM Key / 日上限 / 库上限会优雅跳过；列表可显示 FAQ 任务状态（queued/running/done/error/skipped）。

近义相似度（`FAQ_SIMILARITY_THRESHOLD`）当前用于**生成去重**，不用于问答语义命中（语义命中属二期）。

## 配置（`.env` / Settings）

| 项 | 默认 | 说明 |
|----|------|------|
| `FAQ_MASTER_SWITCH` | true | 总开关 |
| `FAQ_GENERATION_ENABLED` | true | 生成开关 |
| `FAQ_PER_DOCUMENT_COUNT` | 25 | 每文档目标条数 |
| `FAQ_PER_KB_LIMIT` | 500 | 每库上限 |
| `FAQ_KB_DAILY_LIMIT` | 500 | 每库每日生成上限 |
| `FAQ_QUALITY_THRESHOLD` | 0.7 | 入库阈值 |
| `FAQ_SIMILARITY_THRESHOLD` | 0.85 | 生成近义去重 |
| `FAQ_REJECT_DISABLE_THRESHOLD` | 3 | 连续点踩禁用 |
| `FAQ_REDIS_CACHE_TTL_SECONDS` | 900 | FAQ Redis TTL |
| `ROLE_CACHE_WRITE_ENABLED` | false | 过渡期停写角色缓存 |
| `ROLE_CACHE_READONLY_FALLBACK` | true | 角色缓存只读回退 |

## 迁移

```bash
cd backend
PYTHONPATH=. python ../scripts/migrate_role_cache_to_kb.py
```

幂等：已存在 `source=migrated` 同题跳过。

## 主要接口

- `GET /api/v1/faq/list` — 访客热门（可选登录；按密级过滤）
- `GET /api/v1/admin/faq/list?kb_id=` — 管理列表
- `PUT /api/v1/admin/faq/{id}` — 编辑
- `POST /api/v1/admin/faq/batch` — 批量（含密级）
- `POST /api/v1/knowledge-bases/{kb_id}/faq/toggle` — 库级开关
- `POST /api/v1/admin/knowledge-bases/{kb_id}/regenerate-faq` — 重生

## 一期冒烟验收

1. 上传文档 → `ready` → 后台出现 FAQ  
2. 访客页热门题可点选秒答  
3. 手输与热门完全同题命中同一答案  
4. 管理端改答案后立刻生效（无旧 Redis）  
5. 带 FAQ 的快照回退后 FAQ 集合还原  

## 二期（结项，无三期）

见 [`FAQ_PHASE2_ACCEPTANCE.md`](FAQ_PHASE2_ACCEPTANCE.md)：语义同题命中、QA 缓存密级隔离、文档侧权限对齐、角色缓存过渡收口等。

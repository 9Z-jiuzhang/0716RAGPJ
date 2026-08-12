# FAQ 知识库缓存（V2.1）

## 概述

知识库 FAQ 是 RAG 的加速层：文档向量化就绪后异步生成 FAQ，按 `kb_id + normalized_question` 精确命中，跳过 Embedding / 检索 / LLM。

## 命中链路

1. 安全护栏（现网 guard）
2. 多轮判定：显式点选热门题强制走 FAQ；否则会话已有消息或未结束上下文则跳过
3. Redis 短时精确缓存（TTL 默认 900s）
4. 数据库 `kb_cached_faqs`（仅 `active` + `is_active`，且 `kb.faq_enabled`）
5. 越权校验：`faq.kb_id ∈ authorized_kb_ids`
6. 未命中 → 多级 QA 缓存 → 角色缓存只读回退 → 原 RAG

## 生成链路

文档 `ready` 后 `asyncio.create_task` 触发，不阻塞就绪状态。空文档 / 扫描件 / 无 LLM Key / 日上限 / 库上限会优雅跳过。

## 配置（`.env` / Settings）

| 项 | 默认 | 说明 |
|----|------|------|
| `FAQ_MASTER_SWITCH` | true | 总开关 |
| `FAQ_GENERATION_ENABLED` | true | 生成开关 |
| `FAQ_PER_DOCUMENT_COUNT` | 25 | 每文档目标条数 |
| `FAQ_PER_KB_LIMIT` | 500 | 每库上限 |
| `FAQ_QUALITY_THRESHOLD` | 0.7 | 入库阈值 |
| `FAQ_SIMILARITY_THRESHOLD` | 0.85 | 近义去重 |
| `FAQ_REJECT_DISABLE_THRESHOLD` | 3 | 连续点踩禁用 |
| `ROLE_CACHE_WRITE_ENABLED` | false | 过渡期停写角色缓存 |
| `ROLE_CACHE_READONLY_FALLBACK` | true | 角色缓存只读回退 |

## 迁移

```bash
cd backend
PYTHONPATH=. python ../scripts/migrate_role_cache_to_kb.py
```

幂等：已存在 `source=migrated` 同题跳过。

## 主要接口

- `GET /api/v1/faq/list` — 访客热门（可选登录）
- `GET /api/v1/admin/faq/list?kb_id=` — 管理列表
- `PUT /api/v1/admin/faq/{id}` — 编辑
- `POST /api/v1/admin/faq/batch` — 批量
- `POST /api/v1/knowledge-bases/{kb_id}/faq/toggle` — 库级开关
- `POST /api/v1/admin/knowledge-bases/{kb_id}/regenerate-faq` — 重生

管理端菜单：**知识库 FAQ**（原「角色缓存」入口已替换）。

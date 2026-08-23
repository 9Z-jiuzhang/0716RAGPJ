# 运维 Runbook

## PR-A：图表引用上线

1. 部署前确认 `CHART_CITATION_USE_LEGACY_LOGIC=false`（默认新逻辑）。
2. 多副本：**全停再起**，避免新旧 citation 逻辑混跑。
3. 部署后执行清库脚本（staging 先 `--dry-run`）：

```bash
docker compose exec api python -m app.scripts.clear_qa_citation_images --dry-run
docker compose exec api python -m app.scripts.clear_qa_citation_images
```

4. 回滚：设 `CHART_CITATION_USE_LEGACY_LOGIC=true` 并重启 API（恢复 develop 整本展开行为）。

### 配置

| 变量 | 默认 | 说明 |
|------|------|------|
| `MAX_CITATION_CHART_PAGES` | 5 | 单条引用最多拉图页数 |
| `QA_CITATION_CHART_DISPLAY_LIMIT` | 8 | 前端展示上限（`GET /qa/accessible-kbs` 下发 `max_charts`） |
| `CHART_CITATION_USE_LEGACY_LOGIC` | false | true=develop 旧逻辑 |
| `CHART_RASTERIZE_ZOOM` | 1.5 | 缩略图栅格 zoom（2.0 更慢更大） |

按需栅格化：`ensure_pdf_charts(pages=[N])` 只补缺失页；GET `/charts/page-NN.png` 同样只渲该页。

---

## PR-B：角色缓存 Shadow

### Staging 试跑（3–5 天功能验证）

1. Staging 开启：
   - `ROLE_CACHE_SHADOW_METRICS_ENABLED=true`
   - `ROLE_CACHE_READONLY_FALLBACK=true`
   - `QA_EXACT_CACHE_ENABLED=true`（P0 后 L2 回灌需要）
2. 观察 `/metrics`：
   - `role_cache_shadow_hit_total`
   - `role_cache_shadow_started_at_seconds`
   - `role_cache_shadow_window_closing_soon_total`
3. 验证 shadow 期间：**问答不走角色缓存秒答**，但 shadow 命中计数上升。
4. 窗口结束前 3 天应出现 `closing_soon` 计数；到期后 audit `role_cache_shadow_window_closed`。
5. Prod：**全停再起** 后开启 shadow；勿滚动混跑。

### Prod 上线后 24h（SRE ticket 必检）

2.1.13 发版当天若未开 shadow，`shadow hit = 0` **不代表**角色缓存无用，只代表 **没人开 shadow**。

- [ ] 24h 内在 prod **至少 1 个 KB** 设 `ROLE_CACHE_SHADOW_METRICS_ENABLED=true`
- [ ] `role_cache_shadow_started_at_seconds` 非 0
- [ ] `role_cache_shadow_hit_total` 日增

### Prod shadow 数据窗口（14 天）

- 按 `ROLE_CACHE_SHADOW_DAYS=14` 连续采集后再跑 L2 回灌脚本。
- staging 3–5 天样本常 &lt;100 条，**不以 staging 样本量做关角色缓存决策**。

### P0 后 L2 回灌

```bash
docker compose exec api python -m app.scripts.export_role_cache_shadow_hits --top 500 > shadow_hits.jsonl
docker compose exec api python -m app.scripts.backfill_l2_from_shadow --dry-run
docker compose exec api python -m app.scripts.backfill_l2_from_shadow --ttl-seconds 259200
```

需 `QA_EXACT_CACHE_ENABLED=true`；TTL 默认 3 天。

### Prometheus 告警示例

```yaml
- alert: RoleCacheShadowWindowClosingSoon
  expr: increase(role_cache_shadow_window_closing_soon_total[1h]) > 0
  for: 0m
  labels:
    severity: warning
  annotations:
    summary: "角色缓存 shadow 窗口即将结束（3 天内）"
```

### Redis 键

| 键 | 说明 |
|----|------|
| `shadow:role_cache:started_at:v1:{tenant}` | SET NX，窗口起点 |
| `shadow:role_cache:hits:v1:{tenant}` | ZSET，normalized_question → 命中次数 |
| `shadow:role_cache:closed_audit:v1:{tenant}` | 窗口结束 audit 防重 |

Redis 不可用：shadow 降级，**不影响正常问答**。

---

## 2.1.13：功能开关（5 秒回退，不发新版）

开干前 30 分钟对齐 **第 8 项**：下列 env 齐全且 staging 已测「关开关回旧行为」。

| 模块 | 环境变量 | 默认 | 关开关效果 | 紧急回退测试 |
|------|----------|------|------------|--------------|
| Shadow | `ROLE_CACHE_SHADOW_METRICS_ENABLED` | false | 不采集 shadow | `/metrics` 无 shadow 计数 |
| Markdown | `MARKDOWN_RENDER_ENABLED` | true | 访客/管理端会话详情回纯文本 | 答案无 MD、无闪 `**` |
| 内联引用 | `INLINE_CITATION_ENABLED` | true | 回 citations 数组旧展示 | 无 `[1]`，仅侧栏引用 |
| Asset 图 | `ASSET_CITATION_ENABLED` | true | 仅 page 级整页图 | 无 `kind=asset` |
| 推荐问 | `SUGGESTED_QUESTIONS_ENABLED` | true | 不发 SSE 尾事件 | `done` 后无尾事件 |
| 澄清反问 | `CLARIFY_ENABLED` | true | staging 3 天后再开 prod | 模糊问不澄清 |
| Cite 校验 | `CITE_VALIDATION_ENFORCE` | false | 仍全量算 overlap，不展示 unverified | `cite_validation_unverified_total` 仍增 |
| CJK 全文 | `FULLTEXT_ANALYZER_BACKEND` | default | 切 `default` 回退 | 长尾召回恢复改前 |
| FAQ 语义 | `FAQ_SEMANTIC_HIT_ENABLED` | true | 仅精确 FAQ | 近义无 cache_hit |
| FAQ 校验 | `FAQ_VERIFY_ENABLED` | true | 关闭自动校验任务 | verify 无 drift |

**澄清 prod**：建议 staging 跑满 3 天且 `clarify_triggered_total` 在 5–20% 后再开 `CLARIFY_ENABLED=true`。

---

## 2.1.13：Asset 图鉴权

- **禁止** MinIO presigned URL 直出前端。
- 路径：`GET /api/v1/qa/documents/{doc_id}/assets/{asset_id}`（或 charts 同级代理）。
- **复用** `require_kb_access` + 密级过滤，与 `/qa/ask` 一致。

---

## 2.1.13：CJK 改造与回滚

1. 改前 Chroma collection export 到 backup 目录（脚本见发布 PR）。
2. PG：`CREATE INDEX CONCURRENTLY`；保留 `DROP INDEX` 步骤。
3. `FULLTEXT_ANALYZER_BACKEND=default|zh_jieba` env 切换，避免只能重建才能回退。
4. 改后 **7 天**监控 `fulltext_query_latency_seconds` p99、索引大小；p99 &gt; 改前 50% → 切 env 回 `default`。

---

## 2.1.13：上线后 7 日每日监控

上线后 **7 天每天看**（不是「上线就完事」）：

| 指标 | 阈值 | 异常动作 |
|------|------|----------|
| `role_cache_shadow_hit_total` 日增 | 应有值 | 查 shadow 是否真在跑 |
| `cite_validation_unverified_total` | enforce=false 时仍计数 | 看「若 enforce=true 会标多少」 |
| `suggested_questions_click_total` / `suggested_questions_total` | click rate &gt; 0 | 全 0 → 调 prompt |
| `clarify_triggered_total` / `qa_requests_total` | 5–20% | 0=太严；&gt;30%=误触发 |
| `qa_feedback_total{rating="thumbs_down"}` 占比 | &lt;15% 期望 | &gt;25% 体验回退 |
| `fulltext_query_latency_seconds` p99 | 改前 ±20% | &gt;50% → CJK env 回滚 |
| `qa_feedback_total{actor="visitor"}` 日增 | 应有值 | 0=访客 feedback 未打通 |

---

## 2.1.13：Golden 问句

- **开干第 1 天**：DBA + 产品 + 架构 **30 分钟**定稿 10 条（见 `backend/tests/fixtures/golden_queries.json`）。
- 分布：5 FAQ（精确+语义）+ 2 PDF 引用（含图）+ 1 中文长尾 + 1 多轮 + 1 故意模糊（澄清）。
- **每个 PR** 跑 `pytest tests/test_golden_queries.py`；定稿后扩展端到端断言，**任 1 条退化 PR 不过**。
- 文件：`backend/tests/fixtures/golden_queries.json`
- `expected_status`: `pass` | `partial` | `fail_implemented`（blocked 不算 PR failure）
- `review_due` 过期 → CI 禁止发版，须季度审视后延期

---

## 2.1.13：SSE 尾事件

- `done` = 主答案流结束，**连接未必立即关闭**（可能再发 `suggested_questions` 等）。
- 前端 **fetch + 自管 stream**，不用 `EventSource`。
- 新提问用新 `request_id` + AbortController，避免与尾事件串流。

---

## 2.1.13：文档与代码同 PR

每个模块 PR 须含对应文档/前端，禁止「文档后补」：

- `docs/API.md`（citation、SSE、CITE_VALIDATION）
- `docs/KB_FAQ.md`（FAQ 二期、命中链）
- `docs/RUNBOOK.md`（本文件）
- `README.md` changelog 2.1.13
- `frontend/guest/js/app.js`（Markdown、内联解析）

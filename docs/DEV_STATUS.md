# 开发与发布状态（文档同步基准）

> **文档修订**：2026-08-23  
> **代码 `APP_VERSION`**：`2.1.12`（`backend/app/core/config.py`）  
> **相对 `origin/develop`**：本地 `develop` +2 commit；`feature/2.1.13` +FAQ 基底；工作区尚有未提交改动。

本文是各开发文档的**对齐基准**：README / API.md 等于本文件冲突时，以**代码 + 本文件**为准并尽快修文档。

---

## 1. 版本与分支

| 线 | 状态 | 说明 |
|----|------|------|
| **2.1.12** | 已 commit 到本地 `develop`（未 push） | PR-A 图表引用 + PR-B shadow |
| **2.1.13** | `feature/2.1.13` 开发中 | FAQ 二期已合入分支；D–H 主体未完成 |
| **图表性能 hotfix** | 工作区已改、待 commit | 按需栅格化 + LRU + 线程池（见 RUNBOOK PR-A） |

**推 GitHub**：按团队决定「本地全部搞好再推」；推前见 README §九 契约同步清单。

---

## 2. 已交付能力（相对远端 develop）

| 模块 | 状态 |
|------|------|
| 图表引用 PR-A | ✅ 单页 citation，非整本 99 页 |
| Shadow PR-B | ✅ 观测不短路；RUNBOOK 运维条目 |
| FAQ 二期（语义 + 校验） | ✅ 在 `feature/2.1.13` |
| 图表按需栅格化 | ✅ 代码在工作区 |
| Golden 测试门禁 | ⚠️ 骨架在工作区（`expected_status`、SSE 解析器） |

---

## 3. 2.1.13 宪章：未完成（仅 config 开关名）

| 模块 | 状态 |
|------|------|
| D Markdown 流式渲染 | ❌ |
| E 内联 `[N]`、cite 指标 | ❌ |
| F Asset 代理 API + 鉴权 | ❌ |
| G CJK 双后端 | ❌ |
| H 推荐问 SSE 尾事件 | ❌ |
| 澄清反问 | ❌ |

开关已在 `.env.example`（`MARKDOWN_RENDER_ENABLED` 等），**业务代码未接**。

---

## 4. 基础设施钉死项

| 组件 | 版本 / 约定 |
|------|-------------|
| Chroma 镜像 | `chromadb/chroma:1.5.5`（compose 固定，勿 `latest`） |
| Python `chromadb` | `>=1.5,<2.0`（建议生产锁 `==1.5.5` 与镜像一致） |
| Chroma 持久化 | 容器 `/data` → 宿主机 `./data/chroma` |
| 向量读 | `VECTOR_READ_PROVIDER=chroma`（`alibaba` 为桩，禁止生产切读） |
| 换向量库 | 实现 `VectorStorePort` 新适配器 + 全量 reindex；见 README §2.5 |

---

## 5. 问答与引用（给产品/测试）

| 能力 | 现状 |
|------|------|
| 问图答 **文字** | ✅ 入库多模态描述 + RAG |
| 引用区 **整页 PNG** | ✅ `GET /qa/documents/{id}/charts/page-NN.png` |
| 引用区 **单图 asset** | ❌ 等 F 模块 |
| 首次点缩略图慢 | ✅ hotfix 后按需单页栅格化（约 0.3–1s） |

---

## 6. 文档索引

| 文件 | 用途 |
|------|------|
| [README.md](../README.md) | 架构、模块、配置总览 |
| [API.md](./API.md) | 接口字段与变更记录 |
| [KB_FAQ.md](./KB_FAQ.md) | FAQ 命中链与配置 |
| [RUNBOOK.md](./RUNBOOK.md) | 发版、shadow、开关、监控 |
| [CONTRACT.md](./CONTRACT.md) | OpenAPI 变更流程 |
| [CLOUD_DEPLOY.md](./CLOUD_DEPLOY.md) | 云端部署 |
| [API_INTEGRATION_GUIDE.md](./API_INTEGRATION_GUIDE.md) | 第三方接入 |

---

## 7. 测试

```bash
docker compose exec api pytest tests/test_qa_chart_citations.py tests/test_role_cache.py tests/test_golden_queries.py -q
```

- Golden 问句：`backend/tests/fixtures/golden_queries.json`（对齐会定稿 10 条）
- Layer 1 手测记录：`backend/tests/testdata/qa_kb/staging_records/`

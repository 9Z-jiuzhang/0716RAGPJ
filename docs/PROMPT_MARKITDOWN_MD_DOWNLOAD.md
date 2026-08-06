# 修改提示词：文档 MarkItDown 转换 + 列表「下载 MD」

> **用途**：给开发 / Cursor Agent 的实现说明（先读本文再改代码）。  
> **范围**：本机联调 `http://localhost:9080`；分支按仓库约定在 `develop`。  
> **状态**：已按本文实现（2026-08-06）；联调依赖需在 API 容器内安装 `markitdown[pdf,docx]`（或重建镜像）。  
> **关联截图场景**：管理端 → 知识库 → 文档列表 →「操作」列（现有：文档处理 / 删除）。  
> **核查修订**：2026-08-06 第二遍（对齐目标措辞与格式表、统一函数名、StreamInfo、事件绑定、service 编排、OpenAPI 脚本路径、错误体 `detail`）。

---

## 0. 任务对齐（防跑偏）

用户原话对应关系：

| # | 用户要求 | 本期落地方式 |
|---|----------|--------------|
| 1 | 文档 markdown 转换（微软工具 markitdown） | 后端对需转换的格式调用 **MarkItDown**；纯文本类见 §4.2.3 |
| 2 | 知识库文档列表「操作」列加选项，可下载转换后的 md | 增加按钮 **「下载 MD」**；点击 = **转换/导出 + 下载**（一个动作） |

**明确结论（逻辑自洽点）**：

- 本期是 **导出能力**，不是「替换 RAG 解析器」。  
- **不需要**单独的「转换」按钮或异步任务状态；列表上 **只加一个「下载 MD」**。  
- 转换结果 **默认不落库、不改表、不写回** `raw_text` / `normalized_text` / 向量索引。  
- 「用了 MarkItDown」的验收口径：对 **pdf/docx**（及能走通的 **doc**）必须走 MarkItDown；**md/txt** 本身已是文本，直接解码导出仍算完成本期下载能力，且避免无意义二次转换。  
- 联调入口：`http://localhost:9080/admin/#/admin/knowledge-bases/{kb_id}?tab=docs`。

---

## 1. 目标（必须同时满足）

1. 接入微软 **[MarkItDown](https://github.com/microsoft/markitdown)**（PyPI：`markitdown`），按 §4.2.3 将知识库已上传原文件导出为 Markdown 文本。  
2. 在管理端知识库文档列表 **操作列** 增加 **「下载 MD」**，点击后浏览器下载 `.md` 文件（内容为 §4.2.3 规定的导出结果）。

### 1.1 非目标（本期不做）

- 不改变现有 RAG 流水线主路径：`parsers.extract_text` → 分段 → 向量化（`document_pipeline`）。  
- 不把导出结果写回 DB / 替换检索语料。  
- 不扩展上传格式（仍为 `pdf/doc/docx/txt/md`，见 `UPLOAD_ALLOWED_TYPES`）。  
- 不做访客端（guest）入口；仅管理端文档列表。  
- 不启动/改造 Langfuse。  
- 不做「转换一次、MinIO 缓存 MD」落库方案（见 §3.2，仅备选）。

---

## 2. 现状（改之前先对齐）

| 层级 | 现状 | 关键路径 |
|------|------|----------|
| 前端入口 | `pageDocuments`；页级权限 `requirePerm("doc:read")` | `frontend/admin/js/app.js` ≈3482+ |
| 操作列 HTML | 「文档处理」始终显示；「删除」=`canWrite && !busy`；「重试」=`canWrite && error && !busy` | 同文件 ≈4550–4555 |
| 操作列事件 | `[data-preview]` → `openDocWorkbench`；`[data-retry]` / `[data-del]` 另绑 | 同文件 ≈4664+（**下载按钮须在此附近加 `[data-dl-md]` 绑定**） |
| 权限变量 | `canWrite = doc:write`；`canUpload = doc:write \|\| kb:upload`；`canSegment = doc:segment` | 同文件 ≈3488–3490 |
| 文档 API | 有 content **JSON 预览**，**无**原文件下载 / **无** MD 导出 | `backend/app/api/v1/documents.py` |
| 业务异常 | `DocumentError(message, http_status=400)`；`_raise_doc_error` → `HTTPException(detail=exc.message)` | `utils/exceptions.py`；`documents.py` |
| 原文件 | MinIO；路径形如 `{kb_id}/{uuid}_{filename}`；`storage.download_bytes` | `storage.py` |
| 现有解析 | 自研 `parsers.extract_text`（`.doc` 依赖镜像内 antiword/catdoc） | `parsers.py`；`backend/Dockerfile` |
| 依赖 | **无** `markitdown` | 根目录 `requirements.txt` |
| 附件下载范式 | 后端 `PlainTextResponse` + `Content-Disposition`；前端 `fetch`+Bearer+`blob`+`<a download>` | `hit_tests.py` `export`；`app.js` `exportRunCsv` ≈5192–5205 |
| OpenAPI | **手写生成脚本**维护 paths，不是运行时自动反射 | `scripts/generate_openapi.py`（文档段 `KBD = "/knowledge-bases/{kb_id}/documents"` ≈1649+）→ 产出 `docs/openapi.json` |
| 契约文案 | 文档管理在 **§9**（以 `docs/API.md` 为准） | `docs/API.md` |

上传体积上限：nginx / 前端均为 **100MB**（大文件转换须进线程池，见 §4.2.2）。

---

## 3. 推荐方案（默认按此实现）

### 3.1 主路径：按需导出 + 即时下载（不落库）

```text
用户点击「下载 MD」
  → GET /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/markdown
  → require_permission("doc:read")
  → document_service（或等价编排）：取文档（校验 kb_id）→ download_bytes → convert_document_to_markdown
  → 转换在 asyncio.to_thread 中执行
  → PlainTextResponse
       media_type=text/markdown; charset=utf-8
       Content-Disposition=attachment; filename="...md"; filename*=UTF-8''...
```

**为何与任务自洽**：一次点击同时完成「转换/导出」与「下载」；无需第二按钮。  
**优点**：无迁移、与流水线解耦、实现面小。  
**缺点**：每次下载都可能再转换；大 PDF 可能较慢（可接受）。

### 3.2 备选（仅产品明确要求时）

- MinIO 缓存：`{kb_id}/markdown/{doc_id}.md` + 可选 DB 字段。  
- 本期 **默认不做**。若做：删除文档时清理对象 + Alembic。

### 3.3 与 `GET .../content`、流水线文本的关系

| 接口/字段 | 用途 | 本期 |
|-----------|------|------|
| `GET .../content` | JSON 预览 `raw_text` / `normalized_text` | **不动** |
| `raw_text` / `normalized_text` | RAG 解析结果 | **禁止**直接当「下载 MD」内容（含 pdf/docx；禁止用规范化文本冒充 MarkItDown） |
| 新 `GET .../markdown` | 按 §4.2.3 导出 `.md` 附件 | **新增** |

---

## 4. 后端改动清单

### 4.1 依赖

在 `requirements.txt`「文档处理」段增加：

```text
markitdown[all]>=0.1.0,<1.0
```

说明：

- 官方推荐 `pip install 'markitdown[all]'`。  
- 若镜像体积/构建失败，可收窄 extras（至少覆盖 **pdf、docx**）。  
- 合入必须以 `requirements.txt` 为准；容器重建：

```powershell
docker compose -f docker-compose.yml --env-file .env up -d --build api
```

本机构建若因网络失败，可临时 `docker compose exec api pip install 'markitdown[all]'` 联调，但合入前须写回依赖并确保可构建。

### 4.2 服务层

新建：`backend/app/services/markitdown_export.py`  
编排：建议在 `document_service` 增加 `export_document_markdown(db, kb_id, doc_id) -> tuple[str, str]`（正文, 下载文件名），API 只负责鉴权与 Response——与现有 `get_document_content_preview` 分层一致。

#### 4.2.1 MarkItDown 调用（钉死）

原文件已是内存字节，**必须** `convert_stream`（官方：用最窄接口；勿对不可信 URI/路径调用宽泛 `convert()`）。

优先 `stream_info`（`file_extension` 在上游已标记 Deprecated，仍可用作兼容）：

```python
import io
from markitdown import MarkItDown
from markitdown._stream_info import StreamInfo  # 若公开导出路径不同，以实现时包内实际导出为准

md = MarkItDown(enable_plugins=False)
ext = "." + file_type.lower().lstrip(".")  # 如 .docx
result = md.convert_stream(
    io.BytesIO(content),
    stream_info=StreamInfo(extension=ext),
)
text = (getattr(result, "text_content", None) or getattr(result, "markdown", None) or "").strip()
```

若当前安装版 `StreamInfo` 导入路径不便，允许退回：

```python
result = md.convert_stream(io.BytesIO(content), file_extension=ext)
```

禁止：

- `convert("http://...")` / 指向容器外未知路径的 `convert(path)`。  
- 传入 `llm_client`（避免隐式耗额度、拖慢下载）。

#### 4.2.2 异步与阻塞

MarkItDown / 重解析为 **同步** 调用。FastAPI async 路由中：

```python
text = await asyncio.to_thread(
    convert_document_to_markdown,
    filename=doc.filename,
    content=content,
    file_type=doc.file_type,
)
```

函数名统一为 **`convert_document_to_markdown`**（与 §4.2.4 一致）。  
禁止在 async 路由里直接同步转换大文件。

#### 4.2.3 格式边界（与上传白名单对齐，写死）

上传允许：`pdf / doc / docx / txt / md`。

| 类型 | 行为 |
|------|------|
| `md` | **直接解码**为文本返回（复用 `parsers` 侧解码思路 / UTF-8 等），不跑 MarkItDown |
| `txt` | **直接解码**（同上） |
| `pdf` / `docx` | **必须** MarkItDown |
| `doc` | 先 MarkItDown；失败则降级 `parsers.extract_text`，纯文本作为 Markdown 正文（不造假标题层级），日志 `fallback=parsers`；两者皆失败 → `DocumentError` |

空结果（strip 后为空）→ `DocumentError("...", http_status=422)`，禁止下发空文件。

#### 4.2.4 函数签名

```text
convert_document_to_markdown(*, filename: str, content: bytes, file_type: str) -> str
```

失败：抛 `DocumentError`（或其子类如 `UnsupportedFileTypeError`）；路由用现有 `_raise_doc_error`。

### 4.3 API

在 `backend/app/api/v1/documents.py` 增加（紧挨 `GET /{doc_id}/content`）：

| 方法 | 路径 | 权限 | 响应 |
|------|------|------|------|
| `GET` | `/knowledge-bases/{kb_id}/documents/{doc_id}/markdown` | `doc:read` | **附件流**（非 `ok()` JSON） |

完整 URL：`/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/markdown`。

实现要点：

- 对齐 `hit_tests.export_test_run_csv`：`PlainTextResponse`（或等价 `Response`）。  
- `media_type="text/markdown; charset=utf-8"`。  
- `Content-Disposition: attachment; filename="ascii-fallback.md"; filename*=UTF-8''percent-encoded.md`  
  逻辑名 = 原 `filename` 去扩展名 + `.md`（截图中文名如「锦盈四季….docx」→「….md」）。  
- 错误：一律走 `DocumentError.http_status` + `detail=message`（前端读 `detail`）。  
  - 不存在 → 404（`DocumentNotFoundError`）  
  - MinIO 失败 → 建议 `DocumentError(..., http_status=502)` 或 404（选一种写死并测通）  
  - 转换失败 / 空结果 → 422 或 400（与 `DocumentError` 一致）  
- **不要**包进 `{code,message,data}`。

文档状态前置：

- **不要求** `status==ready`。DB 有记录且 MinIO 对象在即可（含 `error` / busy）。  
- 对象缺失 → 明确错误，前端 toast。

### 4.4 契约与 OpenAPI

实现后必须：

1. `docs/API.md` §9 表格新增一行。  
2. 在 `scripts/generate_openapi.py` 的 `KBD` 文档段增加 `.../{doc_id}/markdown` 的 GET（附件响应，对标 hit-test export 写法），再运行脚本更新 `docs/openapi.json`（**不要**只手改 json 导致与脚本漂移）。

---

## 5. 前端改动清单

文件：`frontend/admin/js/app.js` → `pageDocuments`

### 5.1 操作列 UI

在「文档处理」同一 `div.table-actions` 内、**不要**包进 `canWrite`：

```html
<button type="button" class="btn btn-secondary btn-sm"
        data-dl-md="..." data-name="...">下载 MD</button>
```

显隐：

| 按钮 | 显隐 |
|------|------|
| 文档处理 | 能进列表即显示 |
| **下载 MD** | **同「文档处理」**（页级已有 `doc:read`） |
| 删除 | `canWrite && !busy` |
| 重试 | `canWrite && error && !busy` |

Busy 时仍可点「下载 MD」。文案固定：**下载 MD**。不做下拉。

### 5.2 事件绑定（勿漏）

在现有 `document.querySelectorAll("[data-preview]")` 绑定处（≈4664）**旁**增加：

```text
[data-dl-md] → downloadDocumentMarkdown(kbId, docId, filename)
```

### 5.3 点击行为

对齐 `exportRunCsv`，并补强错误处理：

1. 点击后 `btn.disabled = true`；可选 toast「正在转换…」。  
2. `fetch('/api/v1/knowledge-bases/' + kbId + '/documents/' + docId + '/markdown', { headers: { Authorization: 'Bearer ' + getAccessToken() } })`  
   （`getAccessToken` 从 `/assets/js/auth.js` 引入，与 CSV 导出相同）。  
3. `!res.ok`：读 body；FastAPI 多为 `{"detail":"..."}`，取出 `detail` 再 `toast(..., "error")`，return。  
4. `blob` → `<a download>`；优先解析 `Content-Disposition`，否则用 `data-name` 改后缀 `.md`。  
5. `URL.revokeObjectURL`；`btn.disabled = false`（`finally`）。

静态资源已挂载 `./frontend`，改完硬刷新。

---

## 6. 测试建议

### 6.1 后端

- `docx` / `pdf` / `txt` / `md` 各至少一条：200；`Content-Disposition` 含 `.md`；body 非空。  
- `md`/`txt`：与直接解码一致。  
- `pdf`/`docx`：单测 mock `MarkItDown.convert_stream`，断言调用发生。  
- `doc`：mock MarkItDown 抛错 → 断言走 parsers 降级（或集成测跳过）。  
- 无 token / 无 `doc:read` → 401/403。  
- 错误 `doc_id` → 404。  

### 6.2 前端手工（localhost）

1. 打开知识库文档 Tab（截图同款）。  
2. 「文档处理」旁见「下载 MD」。  
3. 对已就绪 docx 下载，`.md` 可打开、非乱码。  
4. 故意制造失败（或断 MinIO）可见 toast，不出现空文件静默下载。  
5. 「文档处理 / 删除 / 重试 / 上传」无回归。  
6. 仅 `doc:read` 账号：能下载、不能删除（若有此类角色）。

---

## 7. 给 Agent 的执行约束（LEVER）

1. **Leverage**：扩 `documents` API + `pageDocuments`；下载对齐 `exportRunCsv` / hit-test CSV；编排对齐 `document_service` 现有方法风格。  
2. **Extend**：新建 `markitdown_export.py`；**禁止**重写 `document_pipeline` / 替换 `parsers.extract_text` 主路径。  
3. **Verify**：`localhost:9080` 点「下载 MD」实机验证。  
4. **Eliminate**：不做前端本地转换、不新增第二套 JSON 预览、不并行落库缓存。  
5. **Reduce**：不落库、不改表；**一按钮 + 一 GET**。

### 7.1 最小改动文件集

```text
requirements.txt
backend/app/services/markitdown_export.py      # 新建
backend/app/services/document_service.py       # 编排 export（建议）
backend/app/api/v1/documents.py
frontend/admin/js/app.js                       # HTML + [data-dl-md] 绑定
docs/API.md
scripts/generate_openapi.py                    # 增 path 后重生
docs/openapi.json                              # 脚本产出
backend/tests/test_documents.py                # 建议
```

禁止：提交 `.env` / 密钥；无关重构；改 guest 前端。

---

## 8. 验收标准（Definition of Done）

- [ ] `requirements.txt` 含 `markitdown`；API 环境可 `import markitdown`  
- [ ] `GET /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/markdown` 可用，`doc:read`，返回 **附件流**  
- [ ] `pdf`/`docx` 走 MarkItDown `convert_stream`；`md`/`txt` 直接解码；`doc` 有降级  
- [ ] 转换经 `asyncio.to_thread`（或等价）调用 **`convert_document_to_markdown`**  
- [ ] 操作列有「下载 MD」，与「文档处理」同显隐；`[data-dl-md]` 已绑定  
- [ ] 失败时 toast 展示后端 `detail`（非静默坏文件）  
- [ ] 现有「文档处理 / 删除 / 重试 / 上传 / 向量化」无回归  
- [ ] `docs/API.md` + `scripts/generate_openapi.py` / `docs/openapi.json` 已更新  

---

## 9. 一句话需求复述（可贴 PR / commit）

> 接入微软 MarkItDown，为知识库文档提供 Markdown 导出；管理端文档列表操作列增加「下载 MD」，按需从 MinIO 原文件导出并下载；不改动现有解析向量化主链路。

---

## 10. 实现口令

> 按 `docs/PROMPT_MARKITDOWN_MD_DOWNLOAD.md` 实现 MarkItDown 下载 MD（默认不落库；遵循 §4.2 调用、格式表与 `.doc` 降级约定）。

---

## 附录 A：第二遍核查记录

| # | 检查项 | 第一版/上一版问题 | 本版处理 |
|---|--------|-------------------|----------|
| 1 | 任务两条是否都覆盖 | 已覆盖 | 保持；§0 写清「一按钮完成两事」 |
| 2 | 目标措辞 vs 格式表 | §1 写「内容为 MarkItDown 结果」，与 md/txt 直接解码矛盾 | §0/§1 改为「按 §4.2.3 导出」 |
| 3 | 函数名 | `to_thread` 用 `convert_bytes_to_markdown`，签名节用另一名 | 统一 `convert_document_to_markdown` |
| 4 | MarkItDown API | 仅 `file_extension` | 优先 `StreamInfo`；兼容 `file_extension` |
| 5 | 分层 | 易把下载/转换全堆在路由 | 建议 `document_service` 编排 |
| 6 | 前端事件 | 只写按钮 HTML，未写绑定位置 | §5.2 钉在 `[data-preview]` 旁 |
| 7 | 错误体 | 泛写 message | 钉死 FastAPI `detail` |
| 8 | OpenAPI | 「若有脚本」 | 明确改 `generate_openapi.py` 再生成 json |
| 9 | 异常映射 | 422/500 含糊 | 对齐 `DocumentError.http_status` + `_raise_doc_error` |
| 10 | 是否贴合截图操作列 | 是 | 保持短文案「下载 MD」、同级按钮 |

**结论**：提示词与「MarkItDown 转换 + 操作列下载 MD」任务对齐；内部目标/格式/命名/前后端契约已自洽；可按 §10 口令实现。

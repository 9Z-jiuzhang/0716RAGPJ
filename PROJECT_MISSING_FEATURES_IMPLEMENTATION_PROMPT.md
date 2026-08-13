# RAG 项目缺失功能实施提示词

> 使用方式：将本文件完整交给编码模型，并让它在当前仓库中直接实施。不要只输出示例代码、设计文档或伪代码。

## 角色与任务

你是一名资深 Python/FastAPI、RAG、Redis、PostgreSQL、前端和 Cython/C++ 工程师。请基于当前仓库完成下列功能，直接修改代码、数据库迁移、配置、前端、测试及文档，并在完成后运行验证。

当前项目的主要技术栈与结构如下：

- 后端：Python 3.10、FastAPI、Pydantic v2、SQLAlchemy 2.x、Alembic。
- 存储：PostgreSQL、Redis、Chroma、MinIO。
- RAG：向量检索、全文检索、混合检索、Rerank、SSE 流式回答。
- 前端：`frontend/guest/` 和 `frontend/admin/` 下的原生 HTML/CSS/JavaScript。
- 现有核心代码：
  - 问答流水线：`backend/app/core/qa_pipeline.py`
  - 问答接口：`backend/app/api/v1/qa.py`
  - 问答 Schema：`backend/app/schemas/qa.py`
  - 会话记忆：`backend/app/memory/`
  - 分段逻辑：`backend/app/services/chunking.py`
  - 角色缓存：`backend/app/services/role_cache.py`
  - Guard：`backend/app/services/llm_guard.py`
  - LLM 客户端：`backend/app/services/llm.py`
  - 访客端：`frontend/guest/`
  - 管理端：`frontend/admin/`

## 总体实施原则

1. **先审计，后修改。** 逐项检查现有实现、测试和文档，列出“已完整实现、部分实现、未实现”。已有能力必须复用和补齐，不得平行创建重复模块。
2. **必须实际落地。** 不得只写方案、TODO、空实现、假数据或永远返回固定值的占位代码。
3. **保持兼容。** 不随意删除或重命名现有字段、接口、SSE 事件、数据库列和环境变量。需要调整时采用新增字段、别名或兼容层。
4. **异步链路不得阻塞。** FastAPI 请求中的数据库、Redis、HTTP 和模型调用继续使用异步实现；CPU 密集逻辑应隔离或编译。
5. **权限隔离。** 所有历史、缓存、预测、反馈和引用均必须校验用户、访客、角色、部门、知识库权限，不得跨用户或跨知识库泄漏。
6. **中文优先。** 用户可见文案、字段说明、日志关键信息和文档使用简体中文；程序内部稳定枚举值可保留英文。
7. **配置化。** 阈值、TTL、上下文轮数、温度范围、意图开关、缓存开关、授权校验参数不得散落硬编码。
8. **可观测。** 关键路径记录结构化日志、`request_id`、各阶段耗时、缓存命中状态和失败原因，但不得记录密码、令牌、完整序列号等敏感数据。
9. **改动前检查 Git 工作区。** 保留用户已有改动，不覆盖无关文件，不使用破坏性 Git 命令。

---

## 功能一：切分策略中文化并增强中文文档切分

### 目标

让管理端所有切分策略、参数和预览结果以中文展示，同时改善中文文档按标题、段落、句末标点切分的质量。

### 要求

1. 对外展示以下中文标签：

   | 内部稳定值 | 中文名称 |
   |---|---|
   | `fixed` | 固定长度 |
   | `sliding` | 滑动窗口 |
   | `paragraph` | 按段落 |
   | `heading` | 按标题 |
   | `markdown` | Markdown 结构 |

2. 后端枚举值和数据库存储值继续使用英文，避免破坏已有数据和 API；响应可增加 `split_mode_label`，前端通过统一映射展示中文。
3. 管理端不得再直接展示 `split_mode`、`chunk_size`、`chunk_overlap` 等生硬英文标签，分别显示“切分策略”“分段长度”“重叠长度”“分隔符”等中文文案。
4. 中文递归切分优先级至少覆盖：

   - Markdown 标题、普通标题；
   - 空行和换行；
   - `。！？；`；
   - `，、：`；
   - 英文句末标点和空格；
   - 最后才使用硬截断。

5. 不得从中间截断 Markdown 围栏代码块；标题路径元数据必须保留。
6. 正确处理 CRLF、连续空行、中英文混排、超长无标点文本、`chunk_overlap >= chunk_size`、空文本和特殊 Unicode 标点。
7. 上传、预览、重新切分、重新向量化必须调用同一套规则，结果一致。
8. 为中文切分添加单元测试和接口测试，至少覆盖：

   - 中文标题与多级标题；
   - 中文句号、问号、感叹号和分号；
   - 中英文混排；
   - Markdown 代码围栏；
   - overlap 边界；
   - 中文 UI 标签与内部英文值的映射。

---

## 功能二：历史对话与多级缓存机制

### 目标

补齐可靠的多轮对话记忆、历史持久化、Redis 热缓存和问答结果缓存，确保缓存命中时仍严格遵守权限和知识版本。

### 会话历史要求

1. PostgreSQL 是会话和消息的持久化事实来源；Redis 只保存热上下文、摘要和索引，不得成为唯一数据源。
2. 同一个 `session_id` 续聊时，将“长期摘要 + 最近 N 轮对话 + 当前问题 + 检索证据”正确注入 LLM。
3. Redis 未命中、过期或重启后，能够从 PostgreSQL 恢复最近历史和摘要，并重新写入 Redis。
4. 超出上下文窗口后自动生成摘要，摘要落 PostgreSQL，并同步 Redis；摘要失败不得导致本轮问答失败。
5. 保持以下行为：

   - 不传 `session_id` 时创建新会话；
   - 传入已过期会话时，在通过归属校验后恢复；
   - 登录用户只能查看自己的历史；
   - 访客只能通过自己的 `X-Guest-Id` 访问所属会话；
   - 删除会话后清理对应 Redis 键。

6. 所有 Redis key 必须有明确命名空间和 TTL，读写时续期，避免永久垃圾数据。

### 问答缓存要求

在复用现有“角色缓存”的基础上，实现清晰的多级命中顺序：

1. L1：规范化问题的精确缓存；
2. L2：语义相似问题缓存；
3. 未命中后才进入 Query 预处理、Embedding、检索、Rerank 和 LLM 生成。

缓存键或缓存记录至少纳入以下隔离维度：

- 规范化后的问题或语义向量；
- 用户角色、部门和授权知识库集合；
- 明确指定的 `kb_ids`；
- 检索策略；
- 当前知识库索引版本或文档版本；
- 模型配置版本；
- 影响答案确定性的必要参数。

缓存记录至少包含：

- 原问题、规范化问题；
- 回答、引用；
- 相似度；
- 来源知识库及索引版本；
- 创建时间、过期时间、命中次数；
- 生成时所用模型和必要参数。

知识库内容、索引版本、权限、角色、模型配置发生变化时，旧缓存必须自动失效或因版本键变化而不再命中。缓存故障时降级到正常 RAG 流程，不得导致问答不可用。

SSE 命中时发送 `cache_hit`，并在 `done` 中包含：

```json
{
  "cache_hit": true,
  "cache_level": "exact|semantic|role",
  "cache_similarity": 0.93
}
```

增加缓存命中、未命中、失效和权限拒绝测试；禁止用相似问题缓存绕过知识库权限。

---

## 功能三：温度控制完整显式化

### 目标

让温度参数在前端、接口、模型调用、日志和历史元数据中完整可见、可控、可追踪。

### 要求

1. `POST /api/v1/qa/ask` 和新增的 `/api/v1/qa/predict` 均接受 `temperature`。
2. 参数范围保持 `0.0 <= temperature <= 2.0`，默认值从配置读取，例如 `QA_DEFAULT_TEMPERATURE=0.7`，不要在多处重复硬编码。
3. 访客端增加“生成温度”控制：

   - 滑块与数值输入联动；
   - 显示当前数值；
   - 提供简短中文说明，例如“值越低越稳定，值越高越有创造性”；
   - 浏览器本地记住用户选择；
   - 移动端可正常操作。

4. 后端必须将温度原样传递到最终回答的 LLM 调用；Guard、摘要、Query 改写等内部任务继续使用各自固定低温配置，不得被用户温度覆盖。
5. 在助手消息的 `retrieval_meta`、SSE `done` 和 `/predict` 响应中记录实际生效温度。
6. 缓存策略必须明确处理温度：建议语义/精确答案缓存只在确定性温度范围内启用，或者把温度桶纳入缓存键。不得在高温请求中静默复用不匹配的低温答案。
7. 添加边界测试：`0`、`2` 合法，负数、超过 `2`、非数字非法；验证温度确实传到主回答模型。

---

## 功能四：`predict` 相似度回答接口

### 目标

提供一个非 SSE 的预测接口，返回完整回答、相似度、引用、业务意图、序列号和耗时，方便普通 HTTP 客户端及后续 `.so` SDK 调用。

### 接口

新增：

```http
POST /api/v1/qa/predict
Content-Type: application/json
Authorization: Bearer <token>   # 登录用户
X-Guest-Id: <guest-id>          # 访客
X-Request-Id: <optional>
```

请求体与 `AskRequest` 尽量复用：

```json
{
  "question": "员工一年有几天年假？",
  "session_id": null,
  "kb_ids": [],
  "strategy": "hybrid",
  "top_k": 5,
  "temperature": 0.2,
  "similarity_threshold": 0.55
}
```

成功响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "serial_no": "pred_01J...",
    "request_id": "uuid",
    "session_id": "uuid",
    "message_id": "uuid",
    "answer": "……",
    "business_intent": {
      "name": "knowledge_query",
      "label": "知识问答",
      "confidence": 0.96,
      "detector": "rule|llm"
    },
    "similarity": 0.87,
    "similarity_source": "rerank|cosine|normalized_rrf|cache",
    "confidence": "high",
    "citations": [],
    "cache_hit": false,
    "cache_level": null,
    "temperature": 0.2,
    "elapsed_ms": 683,
    "stage_elapsed_ms": {
      "intent": 12,
      "cache": 3,
      "retrieval": 121,
      "generation": 520
    },
    "created_at": "ISO-8601 UTC"
  },
  "request_id": "uuid"
}
```

### 相似度规则

1. 对外相似度统一为 `[0, 1]`，含义是“当前问题与用于回答的最佳证据或缓存问题的相关程度”。
2. 不得把距离值直接当相似度。Cosine distance 应正确转换；RRF、全文检索和 Rerank 必须标注 `similarity_source`。
3. 优先级建议：

   - 语义缓存命中：问题与缓存问题的语义相似度；
   - Rerank 可用：最高 `relevance_score`；
   - 否则：最高检索证据的规范化分数；
   - 无可靠证据：`0`，并走低置信度兜底回答。

4. 当最高分低于 `similarity_threshold` 时，不得编造确定性答案；返回项目现有的低置信度/无证据兜底文案，引用可为空。
5. `/predict` 与 `/ask` 必须复用同一问答服务层，不能复制两套 RAG 逻辑。可以让服务层产出统一事件/结果对象，SSE 接口流式消费，`predict` 接口聚合消费。
6. `serial_no` 是每次预测的唯一业务流水号，应可排序、不可重复；建议使用 UUIDv7/ULID 或“时间前缀 + 安全随机数”，并与 `request_id`、数据库消息记录、日志关联。
7. 耗时使用单调时钟（如 `time.perf_counter()`）计算；时间戳使用带时区的 UTC 时间。不要用本地墙上时间做耗时差。
8. 添加并发、阈值、无证据、缓存命中、权限隔离、耗时字段、唯一流水号和错误响应测试。

---

## 功能五：Guard 之外的业务意图识别

### 目标

安全 Guard 只负责“是否允许请求”；新增独立业务意图识别器，负责“允许后该如何处理请求”。两者的数据结构、事件、指标和路由逻辑必须分开。

### 业务意图分类

至少支持以下稳定内部值及中文标签：

| 内部值 | 中文标签 | 建议处理 |
|---|---|---|
| `knowledge_query` | 知识问答 | 进入缓存和 RAG |
| `follow_up` | 追问 | 结合会话历史改写后进入 RAG |
| `greeting` | 问候 | 直接返回简短问候，不做检索 |
| `small_talk` | 闲聊 | 按配置直接回答或提示能力范围 |
| `clarification` | 信息澄清 | 请求用户补充必要信息 |
| `operation_help` | 使用帮助 | 返回系统使用说明 |
| `feedback` | 用户反馈 | 引导使用点赞/点踩或反馈入口 |
| `out_of_scope` | 超出范围 | 返回能力边界说明 |
| `unknown` | 未知 | 默认进入保守 RAG 或澄清流程 |

### 实现要求

1. 流程顺序：

   ```text
   安全 Guard → 业务意图识别 → 按意图路由 → 缓存/RAG/直接回答
   ```

2. 优先使用轻量本地规则识别明确意图；不明确时再调用轻量 LLM，并要求严格 JSON 输出。模型异常时降级为 `unknown`，不得中断问答。
3. 分类器可利用最近少量历史识别 `follow_up`，但不得将其他用户历史带入。
4. 新增独立 SSE 事件 `business_intent`。现有 `intent` 若已表示 Guard 结果，应为兼容保留，但不得继续拿 Guard 意图冒充业务意图。
5. `business_intent` 至少包含：

   ```json
   {
     "name": "knowledge_query",
     "label": "知识问答",
     "confidence": 0.95,
     "detector": "rule|llm|fallback"
   }
   ```

6. 业务意图写入 `QAMessage.retrieval_meta`，并在管理员会话分析中可查看；不要将模型思维链写入数据库或前端。
7. 增加分类器单元测试和流水线路由测试，覆盖问候、追问、知识问题、反馈、超范围、模型超时和非法 JSON。

---

## 功能六：点赞/点踩

### 目标

将现有简单反馈能力补齐为可重复操作、可统计、权限安全的前后端功能。

### 数据与接口

1. 不建议继续只把反馈嵌套写入 `qa_messages.retrieval_meta`。新增独立反馈表及 Alembic 迁移，例如 `qa_message_feedbacks`：

   - `id`
   - `message_id`
   - `user_id`
   - `rating`：`like|dislike`
   - `comment`：可空
   - `created_at`
   - `updated_at`
   - 唯一约束：同一用户对同一消息只有一条当前反馈。

2. 保持现有 `useful|useless` 请求兼容，可在服务层映射到 `like|dislike`。
3. `POST /api/v1/qa/feedback` 应支持：

   - 首次点赞或点踩；
   - 点赞切换为点踩；
   - 重复同一操作幂等；
   - 可选取消反馈，若采用 `DELETE /api/v1/qa/feedback/{message_id}`，请同步更新文档。

4. 只能评价当前登录用户自己会话中的 `assistant` 消息；不能评价问题、系统消息、其他用户消息或已删除会话。
5. 历史消息接口返回当前用户的反馈状态；管理员统计接口返回点赞数、点踩数、点赞率和按时间趋势，不泄漏评论中的敏感信息。

### 前端

1. 每条已完成的助手回答下方直接显示“👍 点赞”“👎 点踩”，不应只藏在更多菜单中。
2. 当前状态高亮，支持切换和取消；请求期间禁用重复点击。
3. 操作成功后即时更新，失败时回滚 UI 并显示中文提示。
4. 点踩后可选填写不超过 500 字的原因；不得使用阻塞式 `prompt()`，使用项目现有弹窗/表单样式。
5. SSE 尚未完成、无 `message_id` 或错误回答时不展示可操作按钮。
6. 添加接口测试及必要的前端行为测试。

---

## 功能七：Cython/C/C++ `.so` 类库、授权序列号与时间计算

### 先明确产物边界

Cython 默认生成的是依赖 CPython ABI 的 Python 扩展 `.so`，并不等于可被任意 C/C++ 程序直接链接的通用动态库。不得把 CPython 扩展错误宣传为独立 C++ 类库。

本次至少交付：

1. **Python/Cython SDK**：Linux 下可构建并通过 Python `import` 使用的 `.so` 扩展；
2. **稳定的 Python 降级实现**：没有编译扩展时功能仍可用；
3. **构建脚本、头文件/声明、版本说明和最小示例**；
4. 如果仓库的明确使用场景要求纯 C/C++ 直接链接，再增加薄的 `extern "C"` 稳定 C ABI；C++ 类仅作为 C ABI 之上的 RAII 封装，避免直接暴露不稳定的 C++ ABI。

### SDK 设计

建议新增独立目录，例如：

```text
native_sdk/
├── pyproject.toml
├── setup.py
├── src/
│   ├── rag_native.pyx
│   ├── rag_native.pxd
│   ├── native_core.hpp
│   └── native_core.cpp
├── include/
│   └── rag_sdk.h
├── python/
│   └── fallback.py
├── examples/
│   ├── python_example.py
│   └── cpp_example.cpp
├── tests/
└── README.md
```

对 Python 暴露清晰的类接口，例如：

```python
class RagPredictClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout_ms: int = 30000): ...
    def set_license(self, license_text: str) -> None: ...
    def verify_license(self) -> dict: ...
    def predict(self, question: str, **options) -> dict: ...
    def last_elapsed_ms(self) -> float: ...
    def version(self) -> str: ...
```

如果提供 C ABI，至少考虑不抛异常穿越 ABI，采用句柄和错误码：

```c
typedef void* rag_client_handle;

rag_client_handle rag_client_create(const rag_client_options* options);
int rag_client_set_license(rag_client_handle handle, const char* license_text);
int rag_client_predict(
    rag_client_handle handle,
    const rag_predict_request* request,
    rag_predict_response* response
);
const char* rag_client_last_error(rag_client_handle handle);
void rag_predict_response_free(rag_predict_response* response);
void rag_client_destroy(rag_client_handle handle);
```

必须明确字符串编码为 UTF-8、内存由谁分配和释放、线程安全边界、超时单位、结构体版本字段和 ABI 版本。

### 授权序列号

这里将“序列号”解释为 SDK 的离线授权许可证，同时预测请求仍有独立的 `serial_no` 业务流水号。

1. 许可证至少包含：

   - `license_id`
   - `customer_id`
   - `product`
   - `edition`
   - `features`
   - `issued_at`
   - `not_before`
   - `expires_at`
   - 可选设备指纹摘要
   - `key_id`
   - `signature`

2. 使用成熟的非对称数字签名方案（建议 Ed25519）：

   - 签发工具持有私钥；
   - SDK 只内置公钥并执行验签；
   - 私钥绝不能提交到仓库、镜像或 `.so`；
   - 不得用 MD5、简单 Base64、异或、自制加密或硬编码万能序列号代替签名。

3. 许可证正文使用确定性序列化，验签前严格校验字段、产品、功能、时间窗口和设备绑定。
4. 日志只能记录脱敏后的 `license_id`，不得打印完整许可证。
5. 提供独立的开发/测试密钥注入方式和测试许可证生成工具；生产公钥从构建参数或安全配置载入。

### 时间计算

1. 授权有效期使用 UTC、带时区时间计算，明确边界：

   ```text
   not_before <= now < expires_at
   ```

2. 返回剩余有效秒数/天数时定义取整规则，并测试闰年、月末、时区、夏令时和过期边界。
3. 运行耗时使用单调时钟，不使用系统墙上时间相减。
4. 离线授权应有基础的系统时间回拨检测：

   - 安全持久化最近一次成功校验时间；
   - 当前时间明显早于上次时间时拒绝或进入受限状态；
   - 明确容忍误差；
   - 检测文件需防普通篡改；
   - 文档必须说明纯离线客户端无法绝对防破解，不能做虚假的安全承诺。

5. Cython 模块内部不得把 Python 对象指针泄漏给外部；释放 GIL 只用于不访问 Python 对象的纯 C/C++ 计算。

### 构建与兼容

1. 加入固定范围的 Cython 构建依赖，不污染现有运行依赖。
2. 目标至少支持项目约束的 CPython 3.10、Linux x86_64；如需 ARM64，构建矩阵单列。
3. `.so` 文件名包含正确的 Python ABI 标签；不要把本机编译产物直接提交 Git，除非项目已有二进制发布规范。
4. 提供：

   - 本地构建命令；
   - Docker/CI 构建命令；
   - `ldd` 或等效依赖检查；
   - Python 导入与最小预测测试；
   - C/C++ 示例的编译运行方式（仅在交付 C ABI 时）。

5. SDK 调用 `/api/v1/qa/predict` 时要正确处理超时、非 2xx 响应、JSON 错误、中文 UTF-8、授权失败和服务端不可用。

---

## 数据库、配置与迁移

1. 所有数据库结构变化必须创建新的 Alembic migration，提供可升级和可安全降级逻辑。
2. 根据审计结果决定是否新增：

   - 业务意图审计字段或表；
   - 独立反馈表；
   - 通用问答缓存表；
   - 预测流水号唯一索引。

3. 更新 `.env.example`，至少考虑以下配置，名称可根据项目现有风格调整：

```dotenv
QA_DEFAULT_TEMPERATURE=0.7
QA_BUSINESS_INTENT_ENABLED=true
QA_BUSINESS_INTENT_MODEL=
QA_BUSINESS_INTENT_TIMEOUT_SECONDS=3
QA_ANSWER_CACHE_ENABLED=true
QA_EXACT_CACHE_TTL_SECONDS=3600
QA_SEMANTIC_CACHE_TTL_SECONDS=1800
QA_SEMANTIC_CACHE_THRESHOLD=0.90
QA_CACHE_MAX_TEMPERATURE=0.30
QA_PREDICT_DEFAULT_SIMILARITY_THRESHOLD=0.55
RAG_SDK_LICENSE_PUBLIC_KEY=
RAG_SDK_CLOCK_ROLLBACK_TOLERANCE_SECONDS=300
```

4. 对配置执行 Pydantic 校验，错误配置应在启动时给出明确提示。

---

## 文档要求

同步更新：

- `README.md`
- `docs/API.md`
- `docs/API_INTEGRATION_GUIDE.md`
- `docs/openapi.json`（通过项目脚本重新生成，不手工伪造）
- `.env.example`
- Cython/原生 SDK 的独立 `README.md`

文档必须包含：

- 中文切分策略映射；
- 历史与缓存生命周期；
- 温度控制说明；
- `/qa/predict` 请求响应示例；
- `business_intent` SSE 事件；
- 点赞/点踩接口和状态；
- `.so` 构建、安装、版本兼容、授权和错误码；
- Cython 扩展与通用 C/C++ 动态库的边界说明。

---

## 测试与验收标准

### 后端

1. 为新增服务写单元测试，为接口写集成测试。
2. 现有测试必须继续通过，不得通过删除断言、跳过测试或降低覆盖要求来“修复”。
3. 至少验证：

   - 中文切分质量和边界；
   - 历史从 PostgreSQL 回填 Redis；
   - 会话权限隔离；
   - 精确/语义/角色缓存命中与失效；
   - 温度透传及边界；
   - `/predict` 相似度、阈值、流水号和耗时；
   - Guard 与业务意图互不混用；
   - 点赞、点踩、切换、取消、幂等和权限；
   - 数据库迁移可执行。

### 前端

至少手工或自动验证：

- 切分策略全部显示中文；
- 温度控件桌面端和移动端可用；
- SSE 回答不受新增事件影响；
- 点赞/点踩状态正确、失败可回滚；
- 历史消息重新打开后能恢复反馈状态。

### Cython/原生 SDK

至少验证：

- 能在干净 Linux/CPython 3.10 环境构建；
- 编译后的模块可导入；
- Python fallback 与 `.so` 的输入输出一致；
- 中文问题不乱码；
- 并发调用无明显数据竞争；
- 授权有效、未生效、过期、签名错误、产品不匹配、功能不允许、时间回拨均有测试；
- `serial_no` 唯一，`elapsed_ms` 非负；
- 没有提交私钥、测试 Token 或真实凭证。

### 建议执行命令

请根据项目实际环境调整，但最终报告必须列出真实执行过的命令和结果：

```bash
pytest
ruff check backend
python scripts/generate_openapi.py
alembic upgrade head
python -m build native_sdk
pytest native_sdk/tests
```

---

## 最终交付格式

完成修改后，请按以下顺序给出最终报告：

1. **现状审计**：每项功能原先已有内容与实际缺口；
2. **已完成改动**：按后端、前端、数据库、SDK、文档分类；
3. **关键设计决定**：尤其是缓存隔离、相似度定义、业务意图、Cython/C ABI 和授权方案；
4. **数据库迁移与配置变化**；
5. **测试结果**：真实命令、通过数量、失败数量；
6. **构建产物**：`.so` 名称、ABI、目标平台及使用示例；
7. **遗留风险**：只列真实未解决问题，不得用“后续可优化”掩盖未完成项。

如果遇到无法从仓库判断、且会实质改变接口或授权模型的关键歧义，应先提出最少量的澄清问题；除此之外请基于以上默认约定持续实施，直到代码、迁移、测试和文档全部完成。

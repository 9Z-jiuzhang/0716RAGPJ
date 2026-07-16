# AI 知识库 RAG 平台 -- Cursor 项目框架搭建提示词

> 版本：V1.0
> 日期：2026-07-16
> 用途：在 Cursor 中逐条执行以下提示词，搭建完整的项目框架并上传至 GitHub 仓库，供 8 人团队协作开发
> 重要：本文件为提示词集合，不是代码。请将每条提示词复制到 Cursor 对话框中执行

---

## 使用说明

1. 按顺序执行以下提示词。每条提示词生成一组文件，后一条可能依赖前一条的输出
2. 执行前请先在 Cursor 中打开一个空的项目目录
3. 每条提示词执行完毕后，确认生成的文件无误，再执行下一条
4. 所有生成的代码文件必须包含中文注释
5. 框架搭建完毕后，初始化 Git 仓库并推送到 GitHub

---

## 提示词 1：项目根目录结构与基础配置文件

**目的**：创建项目骨架、目录结构、.gitignore、.env.example、requirements.txt、README.md

**提示词文本**：

```
你是一个资深 Python 后端架构师。请在当前项目根目录下创建以下文件和目录结构。所有生成的代码文件必须包含中文注释。

## 任务

### 1.1 创建目录结构

请创建如下完整的目录树（空目录也需要创建，使用占位 .gitkeep 文件保持目录）：

```
project-root/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── middleware/
│   │   └── utils/
│   ├── tests/
│   └── alembic/
│       └── versions/
├── frontend/
│   ├── guest/
│   │   ├── css/
│   │   ├── js/
│   │   └── assets/
│   ├── admin/
│   │   ├── css/
│   │   ├── js/
│   │   └── assets/
│   └── shared/
│       ├── css/
│       └── js/
├── docker/
│   ├── nginx/
│   ├── postgres/
│   └── grafana/
│       └── dashboards/
└── data/
```

### 1.2 创建 .gitignore

内容需忽略以下项：
- Python: __pycache__, *.pyc, *.pyo, .venv, venv, *.egg-info, dist, build
- 环境配置: .env（不提交，但 .env.example 要提交）
- IDE: .vscode/, .idea/, *.swp, *.swo
- 数据: data/（Docker 数据卷挂载目录）
- 操作系统: .DS_Store, Thumbs.db
- 测试: .pytest_cache, .coverage, htmlcov/
- Node: node_modules/（如果前端引入构建工具）
- 日志: *.log, logs/

### 1.3 创建 .env.example

基于以下配置项创建环境变量模板文件（只列出 key，value 全部用占位符 `<请填写>`）：

```
APP_NAME=AI-KnowledgeBase-RAG
APP_VERSION=2.1.0
DEBUG=false
SECRET_KEY=<请填写>

# 数据库
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=knowledge_base
POSTGRES_USER=kb_user
POSTGRES_PASSWORD=<请填写>

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# 向量数据库 Chroma
CHROMA_HOST=chroma
CHROMA_PORT=8000

# 对象存储 MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=<请填写>
MINIO_SECRET_KEY=<请填写>
MINIO_BUCKET=knowledge-base-docs

# LLM 大模型
LLM_PROVIDER=openai
LLM_API_KEY=<请填写>
LLM_MODEL=gpt-4o
LLM_BASE_URL=

# Embedding 嵌入模型
EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=<请填写>
EMBEDDING_MODEL=text-embedding-3-small

# Rerank 重排模型（可选）
RERANK_PROVIDER=
RERANK_API_KEY=
RERANK_MODEL=

# Langfuse 可观测
LANGFUSE_HOST=http://langfuse-server:3000
LANGFUSE_PUBLIC_KEY=<请填写>
LANGFUSE_SECRET_KEY=<请填写>

# JWT 认证
JWT_SECRET_KEY=<请填写>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# 日志
LOG_LEVEL=INFO
```

### 1.4 创建 requirements.txt

包含以下依赖（固定主版本号，不锁定次版本）：

```
# Web 框架
fastapi>=0.110,<1.0
uvicorn[standard]>=0.29,<1.0

# 数据库
sqlalchemy>=2.0,<3.0
asyncpg>=0.29,<1.0
alembic>=1.13,<2.0
psycopg2-binary>=2.9,<3.0

# Redis
redis>=5.0,<6.0
hiredis>=2.3,<3.0

# 向量数据库
chromadb>=0.5,<1.0

# 对象存储
minio>=7.2,<8.0

# 认证
python-jose[cryptography]>=3.3,<4.0
passlib[bcrypt]>=1.7,<2.0
python-multipart>=0.0.9,<1.0

# 数据校验
pydantic>=2.7,<3.0
pydantic-settings>=2.2,<3.0

# HTTP 客户端
httpx>=0.27,<1.0

# 文档处理
python-docx>=1.1,<2.0
PyPDF2>=3.0,<4.0
markdown>=3.6,<4.0
python-pptx>=0.6,<1.0
openpyxl>=3.1,<4.0

# LLM 相关
openai>=1.30,<2.0
langfuse>=2.40,<3.0

# 监控
prometheus-client>=0.20,<1.0

# 任务队列
arq>=0.26,<1.0

# 工具
python-dotenv>=1.0,<2.0
tenacity>=8.3,<9.0

# 测试
pytest>=8.2,<9.0
pytest-asyncio>=0.23,<1.0
httpx>=0.27,<1.0

# 代码质量
black>=24.4,<25.0
ruff>=0.4,<1.0
```

### 1.5 创建 README.md

内容包含：
- 项目名称：AI 知识库 RAG 平台
- 一句话简介：基于大语言模型的智能知识库平台，支持多格式文档管理、语义检索和多轮对话问答
- 技术栈：Python 3.10 + FastAPI + PostgreSQL + Chroma + Redis + MinIO + Docker
- 快速开始：3 步启动（复制 .env.example -> 填写配置 -> docker compose up）
- 项目结构说明（引用目录树）
- 开发规范链接
- 团队协作约定
- 许可证（MIT）

---

## 提示词 2：后端核心模块（配置、安全、依赖注入）

**目的**：创建 FastAPI 应用入口、核心配置管理、安全认证模块、依赖注入系统

**提示词文本**：

```
你是一个资深 FastAPI 开发者。请在后端 app/core/ 目录下创建以下文件。所有代码必须包含中文注释，注释应说明每个类、函数、关键逻辑的作用。

## 任务

### 2.1 创建 backend/app/core/config.py

使用 pydantic-settings 创建 Settings 类，从 .env 文件和环境变量加载配置。需要包含以下配置组（每个组用注释分隔）：

应用配置组：
- APP_NAME (str, 默认 "AI-KnowledgeBase-RAG")
- APP_VERSION (str)
- DEBUG (bool, 默认 False)
- SECRET_KEY (str)

数据库配置组：
- POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
- 添加一个 property `DATABASE_URL`，返回 asyncpg 格式的连接字符串：postgresql+asyncpg://...

Redis 配置组：
- REDIS_HOST, REDIS_PORT
- 添加 property `REDIS_URL`

Chroma 配置组：
- CHROMA_HOST, CHROMA_PORT

MinIO 配置组：
- MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET

LLM 配置组：
- LLM_PROVIDER, LLM_API_KEY, LLM_MODEL, LLM_BASE_URL (Optional)

Embedding 配置组：
- EMBEDDING_PROVIDER, EMBEDDING_API_KEY, EMBEDDING_MODEL

Rerank 配置组（全部 Optional）：
- RERANK_PROVIDER, RERANK_API_KEY, RERANK_MODEL

Langfuse 配置组：
- LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

JWT 配置组：
- JWT_SECRET_KEY, JWT_ALGORITHM (默认 HS256)
- ACCESS_TOKEN_EXPIRE_MINUTES (默认 30)
- REFRESH_TOKEN_EXPIRE_DAYS (默认 7)

日志配置组：
- LOG_LEVEL (默认 "INFO")

创建全局单例 settings = Settings()

### 2.2 创建 backend/app/core/security.py

包含以下函数：

1. `create_access_token(data: dict, expires_delta: timedelta | None = None) -> str`
   - 使用 python-jose 创建 JWT access token
   - 默认过期时间从 settings 读取
   - 中文注释说明 JWT payload 包含的字段

2. `create_refresh_token(data: dict) -> str`
   - 创建 JWT refresh token，过期时间从 settings 读取

3. `verify_token(token: str) -> dict`
   - 验证 JWT token 有效性，返回 payload
   - 处理过期、无效 token 异常，抛出明确的 HTTPException

4. `hash_password(password: str) -> str`
   - 使用 passlib bcrypt 哈希密码

5. `verify_password(plain_password: str, hashed_password: str) -> bool`
   - 验证明文密码与哈希是否匹配

### 2.3 创建 backend/app/core/dependencies.py

包含以下 FastAPI 依赖注入函数：

1. `get_db() -> AsyncGenerator`
   - 异步数据库会话生成器，使用 SQLAlchemy async session
   - 请求结束时自动关闭会话
   - 中文注释说明会话生命周期

2. `get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)) -> User`
   - 从 Authorization Header 提取 Bearer token
   - 验证 token 并查询数据库获取用户对象
   - 如果用户被禁用则抛出 403
   - 返回当前用户 ORM 对象

3. `get_optional_user(token: Optional[str] = Depends(optional_oauth2_scheme), db = Depends(get_db)) -> Optional[User]`
   - 可选认证：有 token 则解析，无 token 返回 None
   - 用于访客问答接口，返回 None 表示未登录访客

4. `require_permission(permission: str) -> Callable`
   - 权限检查依赖工厂函数
   - 返回一个依赖函数，内部检查当前用户是否拥有指定权限
   - 无权限时抛出 403

5. `get_redis() -> AsyncGenerator`
   - 异步 Redis 连接生成器

6. `require_kb_access(kb_id_param: str = "kb_id") -> Callable`
   - 知识库访问权限检查依赖工厂
   - 从路径参数提取 kb_id，验证当前用户是否有访问该知识库的权限
   - 需要同时满足：用户有对应权限标识 + 该权限关联到目标知识库

请将 oauth2_scheme 定义为从请求头提取 Bearer token 的实例。

### 2.4 创建 backend/app/main.py

FastAPI 应用入口文件，包含：

1. 创建 FastAPI 实例，设置 title、version、docs_url 等元信息
2. 配置 CORS 中间件（允许所有来源，开发阶段）
3. 添加启动事件：打印应用启动信息、初始化数据库连接池
4. 添加关闭事件：关闭数据库连接池、关闭 Redis 连接
5. 挂载所有 API 路由（预留路由注册位置，后续提示词补充具体路由）
6. 添加根路径 "/" 返回健康检查 JSON
7. 添加 Prometheus metrics 端点
```

---

## 提示词 3：数据模型层（SQLAlchemy ORM 模型）

**目的**：创建全部 19 个数据库表的 ORM 模型，这是前后端协作的数据契约基础

**提示词文本**：

```
你是一个数据库建模专家。请在 backend/app/models/ 目录下创建数据模型文件。所有代码必须包含中文注释，说明每个字段的用途和业务含义。使用 SQLAlchemy 2.0 异步风格声明模型。

## 任务

### 3.1 创建 backend/app/models/base.py

创建 SQLAlchemy declarative base 和通用混入类：

1. Base = declarative_base()
2. TimestampMixin 混入类：包含 created_at (DateTime, 默认 utcnow) 和 updated_at (DateTime, onupdate=utcnow)
3. 所有模型继承 Base + TimestampMixin

### 3.2 创建 backend/app/models/user.py

User 模型（表名: users）：
- id: UUID, 主键, 默认 uuid4
- username: String(50), 唯一, 非空, 索引
- email: String(255), 唯一, 非空, 索引
- hashed_password: String(255), 非空
- nickname: String(100), 可空
- status: String(20), 默认 "active"（枚举: active/disabled/pending）
- last_login_at: DateTime, 可空

### 3.3 创建 backend/app/models/role.py

Role 模型（表名: roles）：
- id: UUID, 主键
- name: String(100), 唯一, 非空
- description: Text, 可空
- is_builtin: Boolean, 默认 False（内置角色不可删除）

Permission 模型（表名: permissions）：
- id: UUID, 主键
- code: String(100), 唯一, 非空（如 "kb:read", "user:write"）
- name: String(200), 非空（中文名称）
- description: Text, 可空
- scope: String(50), 默认 "global"（global / kb_scoped）

UserRole 关联表（表名: user_roles）：
- user_id: UUID, 外键 -> users.id, 级联删除
- role_id: UUID, 外键 -> roles.id, 级联删除
- 联合主键 (user_id, role_id)

RolePermission 关联表（表名: role_permissions）：
- role_id: UUID, 外键
- permission_id: UUID, 外键
- 联合主键 (role_id, permission_id)

### 3.4 创建 backend/app/models/knowledge_base.py

KnowledgeBase 模型（表名: knowledge_bases）：
- id: UUID, 主键
- name: String(200), 非空, 索引
- type: String(50), 非空（枚举: technical_doc/product_manual/faq/general）
- tags: ARRAY(String), 默认空数组（PostgreSQL ARRAY 类型）
- description: Text, 可空
- visibility: String(20), 默认 "restricted"（public/restricted）
- embedding_model: String(100), 非空
- chunk_size: Integer, 默认 500
- chunk_overlap: Integer, 默认 50
- status: String(20), 默认 "active"（active/vectorizing/archived/deleted）
- current_index_version: String(50), 可空
- creator_id: UUID, 外键 -> users.id

KBPermission 模型（表名: kb_permissions）：
- id: UUID, 主键
- kb_id: UUID, 外键 -> knowledge_bases.id, 级联删除, 索引
- user_id: UUID, 外键 -> users.id, 可空（角色级权限时为空）
- role_id: UUID, 外键 -> roles.id, 可空（用户级权限时为空）
- permission_code: String(100), 非空（如 "kb:read", "kb:upload"）
- 添加 CHECK 约束说明：user_id 和 role_id 至少有一个不为空

### 3.5 创建 backend/app/models/document.py

Document 模型（表名: documents）：
- id: UUID, 主键
- kb_id: UUID, 外键 -> knowledge_bases.id, 级联删除, 索引
- filename: String(500), 非空
- file_type: String(20), 非空（pdf/docx/txt/md/csv/xlsx/pptx）
- file_size: BigInteger, 非空
- file_path: String(1000), 非空（MinIO 对象路径）
- chunk_count: Integer, 默认 0
- status: String(20), 默认 "uploaded"（uploaded/parsing/processing/pending_segment/vectorizing/ready/error/archived）
- error_message: Text, 可空
- creator_id: UUID, 外键 -> users.id

DocumentChunk 模型（表名: document_chunks）：
- id: UUID, 主键
- document_id: UUID, 外键 -> documents.id, 级联删除, 索引
- kb_id: UUID, 外键 -> knowledge_bases.id, 索引
- chunk_index: Integer, 非空（分段序号，从 0 开始）
- content: Text, 非空
- char_count: Integer, 非空
- metadata: JSON, 默认 {}（存储标题层级、页码等元信息）
- is_enabled: Boolean, 默认 True

### 3.6 创建 backend/app/models/index_version.py

IndexVersion 模型（表名: index_versions）：
- id: UUID, 主键
- kb_id: UUID, 外键 -> knowledge_bases.id, 索引
- version: String(50), 非空（版本号，如 "v20260716-001"）
- chunk_count: Integer, 非空
- status: String(20), 默认 "building"（building/active/obsolete/failed）
- config_snapshot: JSON, 非空（记录构建时的分段规则、embedding 模型等配置快照）
- error_message: Text, 可空

### 3.7 创建 backend/app/models/session.py

Session 模型（表名: sessions）：
- id: UUID, 主键
- user_id: UUID, 外键 -> users.id, 可空（访客会话 user_id 为空）
- guest_id: String(64), 可空（访客匿名标识，有索引）
- title: String(200), 默认 "新对话"
- kb_ids: ARRAY(UUID), 可空（限定检索的知识库范围）
- message_count: Integer, 默认 0
- expired_at: DateTime, 可空（会话过期时间）

Message 模型（表名: messages）：
- id: UUID, 主键
- session_id: UUID, 外键 -> sessions.id, 级联删除, 索引
- role: String(20), 非空（user/assistant/system）
- content: Text, 非空
- citations: JSON, 可空（引用来源列表，每个元素含 doc_id/chunk_id/score/content 等）
- token_count: Integer, 默认 0
- metadata: JSON, 默认 {}（含检索策略、耗时、模型版本等）

MemorySummary 模型（表名: memory_summaries）：
- id: UUID, 主键
- session_id: UUID, 外键 -> sessions.id, 级联删除, 唯一
- summary: Text, 非空（对话摘要文本）
- message_range: String(50), 可空（已压缩的消息范围，如 "1-20"）
- compressed_at: DateTime, 非空

### 3.8 创建 backend/app/models/snapshot.py

Snapshot 模型（表名: snapshots）：
- id: UUID, 主键
- kb_id: UUID, 外键 -> knowledge_bases.id, 索引
- name: String(200), 非空
- description: Text, 可空
- trigger: String(20), 非空（auto_upload/auto_delete/auto_resegment/auto_revectorize/auto_permission/manual/rollback_protection）
- status: String(20), 默认 "active"（active/deleted）
- config_snapshot: JSON, 非空（快照时的知识库元信息、分段规则等）
- creator_id: UUID, 外键 -> users.id

SnapshotDocument 模型（表名: snapshot_documents）：
- id: UUID, 主键
- snapshot_id: UUID, 外键 -> snapshots.id, 级联删除
- document_id: UUID（快照时的原始文档 ID，非外键约束，因为文档可能已被删除）
- filename: String(500), 非空
- file_type: String(20), 非空
- chunk_count: Integer, 非空
- content_hash: String(64), 可空（文档内容哈希）
- metadata: JSON, 默认 {}（快照时的文档元信息）

### 3.9 创建 backend/app/models/hit_test.py

HitTestCase 模型（表名: hit_test_cases）：
- id: UUID, 主键
- name: String(200), 非空（测试用例集名称）
- description: Text, 可空
- questions: JSON, 非空（问题列表，每个元素含 question/expected_doc_ids/expected_chunk_ids）
- creator_id: UUID, 外键 -> users.id

HitTestRun 模型（表名: hit_test_runs）：
- id: UUID, 主键
- case_id: UUID, 外键 -> hit_test_cases.id, 可空（关联的用例集）
- kb_ids: ARRAY(UUID), 非空（测试的知识库范围）
- strategy: String(20), 非空（vector/fulltext/hybrid）
- top_k: Integer, 默认 5
- similarity_threshold: Float, 默认 0.5
- status: String(20), 默认 "running"（running/completed/failed）
- total_questions: Integer, 非空
- hit_count: Integer, 默认 0
- recall_at_k: Float, 可空
- mrr: Float, 可空
- avg_elapsed_ms: Float, 可空
- completed_at: DateTime, 可空
- creator_id: UUID, 外键 -> users.id

HitTestResult 模型（表名: hit_test_results）：
- id: UUID, 主键
- run_id: UUID, 外键 -> hit_test_runs.id, 级联删除
- question: Text, 非空
- expected_doc_ids: ARRAY(UUID), 可空
- expected_chunk_ids: ARRAY(UUID), 可空
- actual_chunks: JSON, 可空（检索到的分段列表）
- is_hit: Boolean, 非空
- hit_rank: Integer, 可空（命中排名，1-based）
- score: Float, 可空（最高相关性得分）
- strategy: String(20), 非空
- elapsed_ms: Integer, 可空

### 3.10 创建 backend/app/models/model_config.py

ModelConfig 模型（表名: model_configs）：
- id: UUID, 主键
- name: String(100), 非空
- model_type: String(20), 非空（llm/embedding/rerank）
- provider: String(50), 非空
- model_name: String(200), 非空（实际模型名，如 gpt-4o）
- base_url: String(500), 可空
- is_default: Boolean, 默认 False
- is_enabled: Boolean, 默认 True
- config: JSON, 默认 {}（额外配置参数，如 temperature、max_tokens 等）
- timeout_seconds: Integer, 默认 60

### 3.11 创建 backend/app/models/audit_log.py

AuditLog 模型（表名: audit_logs）：
- id: UUID, 主键
- user_id: UUID, 外键 -> users.id, 可空（系统操作时为空）
- action: String(100), 非空, 索引（如 "kb.create", "doc.delete"）
- resource_type: String(50), 非空, 索引（kb/doc/user/role/snapshot）
- resource_id: String(100), 可空
- detail: JSON, 可空（操作详情，包含变更前后数据对比）
- ip_address: String(45), 可空
- user_agent: String(500), 可空
- request_id: String(64), 可空, 索引
- result: String(20), 默认 "success"（success/failure）
- error_message: Text, 可空

### 3.12 创建 backend/app/models/__init__.py

导入所有模型，便于 alembic 自动发现。

同时创建 backend/app/models/enums.py，使用 Python Enum 定义所有枚举值：
- UserStatus, KBType, KBVisibility, KBStatus, DocumentStatus, DocumentFileType
- SnapshotTrigger, SnapshotStatus, TestStrategy, TestRunStatus
- ModelType, AuditResult
```

---

## 提示词 4：API 契约层（Pydantic Schema 定义）

**目的**：创建全部请求/响应 Schema，这是前后端协作的接口契约。前端开发者和后端开发者以这些 Schema 为准进行并行开发

**提示词文本**：

```
你是一个 API 设计专家。请在 backend/app/schemas/ 目录下创建所有 Pydantic 请求和响应模型。所有代码必须包含中文注释。这是前后端协作的接口契约，务必完整、准确。

## 设计要求

1. 每个模块创建独立的 schema 文件
2. 请求 Schema 以 "XxxRequest" 命名（创建用 CreateXxxRequest，更新用 UpdateXxxRequest）
3. 响应 Schema 以 "XxxResponse" 命名
4. 列表响应统一包含 items、total、page、page_size
5. 所有字段使用 Field 添加描述和示例值
6. 使用 validator 或 field_validator 进行基本校验（如邮箱格式、字符串长度等）

## 任务

### 4.1 创建 backend/app/schemas/common.py

通用 Schema：

1. `BaseResponse` - 统一响应包装
   - code: int = 0
   - message: str = "success"
   - data: Any = None
   - request_id: str（UUID）

2. `PaginationParams` - 分页参数
   - page: int = 1 (ge=1)
   - page_size: int = 20 (ge=1, le=100)

3. `PaginationResponse` - 分页响应（泛型基类）
   - items: List[Any]
   - total: int
   - page: int
   - page_size: int

### 4.2 创建 backend/app/schemas/auth.py

1. `RegisterRequest`: username (3-50字符), password (8-128字符), email (邮箱格式), nickname (可选, 1-100字符)
2. `LoginRequest`: username, password
3. `TokenResponse`: access_token, refresh_token, token_type ("bearer"), expires_in (秒数)
4. `RefreshRequest`: refresh_token
5. `UserInfoResponse`: id, username, email, nickname, status, roles (角色名称列表), permissions (权限标识列表), created_at
6. `ChangePasswordRequest`: old_password, new_password

### 4.3 创建 backend/app/schemas/user.py

1. `UserResponse`: 完整用户信息（包含角色、状态等）
2. `UserListItem`: 用户列表项（精简字段：id, username, email, nickname, status, role_names, created_at, last_login_at）
3. `UpdateUserRequest`: nickname (可选), email (可选)
4. `UpdateUserStatusRequest`: status (active/disabled)
5. `UpdateUserRolesRequest`: role_ids (UUID 列表)
6. `ResetPasswordRequest`: new_password
7. `UserListResponse`: 继承 PaginationResponse，items 类型为 UserListItem

### 4.4 创建 backend/app/schemas/role.py

1. `RoleResponse`: 完整角色信息（含关联权限列表、授权知识库列表）
2. `RoleListItem`: 角色列表项
3. `CreateRoleRequest`: name, description (可选), permission_codes (权限标识列表)
4. `UpdateRoleRequest`: name (可选), description (可选)
5. `UpdateRolePermissionsRequest`: permission_codes (权限标识列表)
6. `RoleListResponse`: 继承 PaginationResponse

### 4.5 创建 backend/app/schemas/knowledge_base.py

1. `KnowledgeBaseResponse`: 完整知识库信息（20+ 字段，包含文档数、分段数、索引版本等统计）
2. `KnowledgeBaseListItem`: 列表项（精简）
3. `CreateKBRequest`: name, type, tags (可选), description (可选), visibility (默认 restricted), embedding_model, chunk_size (可选, 100-5000), chunk_overlap (可选, 0-1000)
4. `UpdateKBRequest`: 所有字段均可选
5. `KBListResponse`: 继承 PaginationResponse
6. `VectorizeStatusResponse`: status, progress_percent, current_doc, total_docs, started_at, error_message
7. `UpdateKBPermissionsRequest`: grants (权限授予列表，每个元素含 user_id/role_id + permission_code)
8. `KBPermissionResponse`: 知识库权限列表响应

### 4.6 创建 backend/app/schemas/document.py

1. `DocumentResponse`: 完整文档信息
2. `DocumentListItem`: 列表项
3. `DocumentListResponse`: 继承 PaginationResponse
4. `UpdateSegmentRulesRequest`: chunk_size, chunk_overlap, separators (可选), split_mode (可选)
5. `SegmentPreviewResponse`: chunks (分段预览列表), total_chunks
6. `DocumentChunkResponse`: 单个分段详情（含内容、元信息）
7. `UpdateChunkRequest`: content (可选), is_enabled (可选), metadata (可选)
8. `ChunkListResponse`: 继承 PaginationResponse
9. `NormalizeResponse`: normalized_content (规范化后的文本), stats (变更统计: 去除空行数、修正编码数等)

### 4.7 创建 backend/app/schemas/qa.py

1. `AskRequest`:
   - question: str (1-2000 字符)
   - session_id: UUID (可选, 不传则创建新会话)
   - kb_ids: List[UUID] (可选, 限定检索范围)
   - strategy: str (可选, 默认 "hybrid")
   - top_k: int (可选, 默认 5, 范围 1-20)
   - temperature: float (可选, 默认 0.7, 范围 0-2)

2. `AskEventResponse` (SSE 流式事件的 data 结构):
   - event: str ("chunk"/"citations"/"done"/"error")
   - content: str (可选, chunk 事件时的文本片段)
   - citations: List[CitationResponse] (可选, citations 事件时的引用列表)
   - session_id: UUID
   - message_id: UUID
   - request_id: str

3. `CitationResponse`:
   - doc_id: UUID
   - doc_name: str
   - chunk_index: int
   - content: str (引用片段文本)
   - score: float

4. `SessionResponse`: id, title, kb_names, message_count, created_at, updated_at
5. `SessionListItem`: 同 SessionResponse 精简
6. `SessionListResponse`: 继承 PaginationResponse
7. `MessageResponse`: id, role, content, citations, token_count, created_at
8. `MessageListResponse`: 继承 PaginationResponse
9. `RenameSessionRequest`: title (1-100 字符)
10. `FeedbackRequest`: message_id, rating ("useful"/"useless"), comment (可选)

### 4.8 创建 backend/app/schemas/hit_test.py

1. `TestCaseResponse`: 测试用例集信息（含问题数量和统计）
2. `TestCaseListItem`: 列表项
3. `CreateTestCaseRequest`: name, description (可选), questions (问题列表)
   - 每个问题: question (str), expected_doc_ids (List[UUID], 可选), expected_chunk_ids (List[UUID], 可选)
4. `UpdateTestCaseRequest`: name (可选), description (可选), questions (可选)
5. `TestCaseListResponse`: 继承 PaginationResponse
6. `TestRunRequest`:
   - case_id: UUID (可选, 不传则单题测试)
   - kb_ids: List[UUID]
   - doc_ids: List[UUID] (可选, 限定文档范围)
   - strategy: str ("vector"/"fulltext"/"hybrid")
   - top_k: int (1-20, 默认 5)
   - similarity_threshold: float (0-1, 默认 0.5)
   - questions: List[str] (可选, 单题测试时传入)
7. `TestRunResponse`: 完整运行记录（含统计指标）
8. `TestRunListItem`: 列表项（精简）
9. `TestRunListResponse`: 继承 PaginationResponse
10. `TestResultResponse`: 单条测试结果（含命中详情）
11. `TestResultExportResponse`: CSV 导出格式说明

### 4.9 创建 backend/app/schemas/snapshot.py

1. `SnapshotResponse`: 完整快照信息（含文档数量、创建方式、状态等）
2. `SnapshotListItem`: 列表项
3. `SnapshotListResponse`: 继承 PaginationResponse
4. `CreateSnapshotRequest`: name, description (可选)
5. `SnapshotDetailResponse`: 快照详情（含文档列表、分段统计、权限配置快照）
6. `RollbackPreviewResponse`: affected_documents (变更文档列表，标注新增/删除/修改)，total_changes
7. `RollbackRequest`: confirm (bool, 必须为 true 才能执行)

### 4.10 创建 backend/app/schemas/model_config.py

1. `ModelConfigResponse`: 完整模型配置（不含密钥明文）
2. `ModelConfigListItem`: 列表项
3. `CreateModelConfigRequest`: name, model_type, provider, model_name, base_url (可选), config (可选), timeout_seconds (可选)
4. `UpdateModelConfigRequest`: 所有字段均可选
5. `SetDefaultRequest`: is_default (bool)

### 4.11 创建 backend/app/schemas/audit.py

1. `AuditLogResponse`: 完整审计日志（含操作详情 JSON）
2. `AuditLogListItem`: 列表项（精简）
3. `AuditLogListResponse`: 继承 PaginationResponse
4. `AuditLogFilterParams`: user_id (可选), action (可选), resource_type (可选), resource_id (可选), result (可选), start_date (可选), end_date (可选)

### 4.12 创建 backend/app/schemas/monitor.py

1. `SystemStatsResponse`: user_count, kb_count, doc_count, active_sessions, task_queue_size
2. `HealthResponse`: status ("healthy"/"degraded"/"unhealthy"), version, uptime_seconds, checks (各组件连通性检查结果)

### 4.13 创建 backend/app/schemas/__init__.py

导入所有 Schema 模块，方便其他模块引用。
```

---

## 提示词 5：API 路由骨架（带契约注解的路由文件）

**目的**：创建全部 12 个 API 路由文件，每个文件包含完整的路由定义、Swagger 注解、权限装饰器，但业务逻辑体留空（标注 TODO）

**提示词文本**：

```
你是一个 FastAPI API 开发者。请在 backend/app/api/v1/ 目录下创建所有 API 路由文件。所有代码必须包含中文注释。

## 重要约束

1. 每个路由函数的函数体内部只写一行 `# TODO: 实现 XxxService.xxx() 业务逻辑` 注释和 `raise HTTPException(status_code=501)`，不要实现具体逻辑
2. 但要完整定义：路由路径、HTTP 方法、请求参数（Path/Query/Body）、响应模型、状态码、Swagger 文档描述、权限依赖
3. 所有请求参数使用 Pydantic Schema，所有响应标注 response_model
4. 使用 `from app.core.dependencies import get_current_user, require_permission, get_db` 注入依赖
5. 每个路由函数标注 status_code、summary、description、tags

## 任务

### 5.1 创建 backend/app/api/__init__.py 和 backend/app/api/v1/__init__.py

v1/__init__.py 中创建 `api_router = APIRouter(prefix="/api/v1")`，并在后续路由文件中使用。

### 5.2 创建 backend/app/api/v1/auth.py

路由前缀: /auth, tags=["认证"]

- POST /auth/register - 用户注册 (公开)
- POST /auth/login - 用户登录 (公开)
- POST /auth/refresh - 刷新 Token (需登录)
- GET /auth/me - 获取当前用户信息 (需登录)

### 5.3 创建 backend/app/api/v1/users.py

路由前缀: /users, tags=["用户管理"]

- GET /users - 用户列表（分页+搜索）- user:read
- GET /users/{id} - 用户详情 - user:read
- PUT /users/{id} - 修改用户信息 - user:write
- PATCH /users/{id}/status - 启用/禁用用户 - user:write
- PUT /users/{id}/roles - 修改用户角色 - user:write
- POST /users/{id}/reset-password - 重置密码 - user:write

### 5.4 创建 backend/app/api/v1/roles.py

路由前缀: /roles, tags=["角色管理"]

- GET /roles - 角色列表 - role:read
- POST /roles - 创建角色 - role:write
- PUT /roles/{id} - 修改角色 - role:write
- DELETE /roles/{id} - 删除角色 - role:write
- PUT /roles/{id}/permissions - 配置角色权限 - role:write

### 5.5 创建 backend/app/api/v1/models.py

路由前缀: /models, tags=["大模型管理"]

- GET /models - 模型列表 - model:read
- POST /models - 添加模型配置 - model:write
- PUT /models/{id} - 修改模型配置 - model:write
- PATCH /models/{id}/status - 启用/禁用模型 - model:write
- PUT /models/{id}/default - 设置默认模型 - model:write

### 5.6 创建 backend/app/api/v1/knowledge_bases.py

路由前缀: /knowledge-bases, tags=["知识库管理"]

- GET /knowledge-bases - 知识库列表（仅返回有权限的）- 需登录
- POST /knowledge-bases - 创建知识库 - kb:write
- GET /knowledge-bases/{id} - 知识库详情 - kb:read
- PUT /knowledge-bases/{id} - 修改知识库元信息 - kb:write
- DELETE /knowledge-bases/{id} - 删除知识库 - kb:write
- POST /knowledge-bases/{id}/re-vectorize - 重新向量化 - kb:vectorize
- GET /knowledge-bases/{id}/vectorize-status - 向量化进度 - kb:vectorize
- PUT /knowledge-bases/{id}/permissions - 配置知识库权限 - kb:write

### 5.7 创建 backend/app/api/v1/documents.py

路由前缀: /knowledge-bases/{kb_id}/documents, tags=["文档管理"]

- GET /knowledge-bases/{kb_id}/documents - 文档列表 - doc:read
- POST /knowledge-bases/{kb_id}/documents/upload - 上传文档（multipart/form-data）- kb:upload
- GET /knowledge-bases/{kb_id}/documents/{id} - 文档详情 - doc:read
- DELETE /knowledge-bases/{kb_id}/documents/{id} - 删除文档 - doc:write
- PUT /knowledge-bases/{kb_id}/documents/{id}/segment-rules - 修改分段规则 - doc:segment
- POST /knowledge-bases/{kb_id}/documents/{id}/re-segment - 重新分段 - doc:segment
- POST /knowledge-bases/{kb_id}/documents/{id}/normalize - 文档规范化 - doc:write
- GET /knowledge-bases/{kb_id}/documents/{id}/chunks - 分段预览 - doc:read
- PUT /knowledge-bases/{kb_id}/documents/{id}/chunks/{chunk_id} - 编辑分段 - doc:segment

### 5.8 创建 backend/app/api/v1/qa.py

路由前缀: /qa, tags=["智能问答"]

- POST /qa/ask - 发送问题（SSE 流式返回）- qa:ask（访客可访问，使用 get_optional_user）
- GET /qa/sessions - 我的会话列表 - 需登录
- GET /qa/sessions/{id} - 会话消息历史 - 需登录
- PUT /qa/sessions/{id} - 重命名会话 - 需登录
- DELETE /qa/sessions/{id} - 删除会话 - 需登录
- POST /qa/feedback - 回答反馈 - 需登录

### 5.9 创建 backend/app/api/v1/hit_tests.py

路由前缀: /hit-tests, tags=["命中率测试"]

- GET /hit-tests/cases - 测试用例列表 - test:read
- POST /hit-tests/cases - 创建测试用例 - test:write
- PUT /hit-tests/cases/{id} - 编辑测试用例 - test:write
- DELETE /hit-tests/cases/{id} - 删除测试用例 - test:write
- POST /hit-tests/runs - 执行命中率测试 - test:write
- GET /hit-tests/runs - 测试运行记录列表 - test:read
- GET /hit-tests/runs/{id} - 测试结果详情 - test:read
- GET /hit-tests/runs/{id}/export - 导出 CSV - test:read

### 5.10 创建 backend/app/api/v1/snapshots.py

路由前缀: /knowledge-bases/{kb_id}/snapshots, tags=["快照管理"]

- GET /knowledge-bases/{kb_id}/snapshots - 快照列表 - snapshot:read
- POST /knowledge-bases/{kb_id}/snapshots - 手动创建快照 - snapshot:write
- GET /knowledge-bases/{kb_id}/snapshots/{id} - 快照详情 - snapshot:read
- POST /knowledge-bases/{kb_id}/snapshots/{id}/preview - 回退差异预览 - snapshot:read
- POST /knowledge-bases/{kb_id}/snapshots/{id}/rollback - 回退到指定快照 - snapshot:restore
- DELETE /knowledge-bases/{kb_id}/snapshots/{id} - 删除快照 - snapshot:write

### 5.11 创建 backend/app/api/v1/audit.py

路由前缀: /audit, tags=["审计日志"]

- GET /audit/logs - 审计日志列表（分页+筛选）- audit:read
- GET /audit/logs/{id} - 审计日志详情 - audit:read

### 5.12 创建 backend/app/api/v1/monitor.py

路由前缀: /monitor, tags=["系统监控"]

- GET /monitor/health - 系统健康检查 (公开)
- GET /monitor/metrics - Prometheus 指标端点 (内部，不在此路由注册，在 main.py 单独处理)
- GET /monitor/stats - 系统统计概览 - system:read

### 5.13 更新 backend/app/main.py

在 main.py 中导入 api_router 并挂载：
```python
from app.api.v1 import api_router
app.include_router(api_router)
```

添加异常处理器：
- 全局 500 异常处理器（返回统一 BaseResponse 格式）
- HTTPException 处理器
- ValidationError 处理器（Pydantic 校验失败）
```

---

## 提示词 6：Docker 部署配置

**目的**：创建 docker-compose.yml、各服务的 Dockerfile、Nginx 配置、数据库初始化脚本

**提示词文本**：

```
你是一个 DevOps 工程师。请在项目根目录和 docker/ 目录下创建容器化部署所需的全部配置文件。所有配置文件必须包含中文注释。

## 任务

### 6.1 创建 docker-compose.yml（项目根目录）

定义以下服务，每个服务标注中文注释说明用途：

1. **api** (FastAPI 后端):
   - build: ./backend
   - 端口: 8000
   - 环境变量从 .env 加载
   - 挂载 ./backend/app 用于开发热重载
   - 依赖: postgres, redis, chroma, minio
   - 健康检查: curl /monitor/health

2. **web** (Nginx 前端静态文件):
   - 镜像: nginx:1.25-alpine
   - 端口: 80
   - 挂载 ./frontend 到 /usr/share/nginx/html
   - 挂载 ./docker/nginx/nginx.conf 到 /etc/nginx/conf.d/default.conf

3. **postgres** (PostgreSQL 数据库):
   - 镜像: postgres:16-alpine
   - 端口: 5432
   - 挂载数据卷到 ./data/postgres
   - 初始化脚本: ./docker/postgres/init.sql
   - 健康检查: pg_isready

4. **redis** (Redis 缓存/队列 broker):
   - 镜像: redis:7-alpine
   - 端口: 6379
   - 挂载数据卷到 ./data/redis
   - 健康检查: redis-cli ping

5. **chroma** (Chroma 向量数据库):
   - 镜像: chromadb/chroma:latest
   - 端口: 8000
   - 挂载数据卷到 ./data/chroma
   - 环境变量: IS_PERSISTENT=TRUE, PERSIST_DIRECTORY=/chroma/chroma

6. **minio** (对象存储):
   - 镜像: minio/minio:latest
   - 端口: 9000 (API), 9001 (Console)
   - 挂载数据卷到 ./data/minio
   - 启动命令: server /data --console-address ":9001"
   - 健康检查

7. **langfuse-server** (LLM 可观测):
   - 镜像: ghcr.io/langfuse/langfuse:latest
   - 端口: 3000
   - 依赖: langfuse-db
   - 环境变量: DATABASE_URL, NEXTAUTH_SECRET, NEXTAUTH_URL, SALT, ENCRYPTION_KEY

8. **langfuse-db** (Langfuse 专用 PostgreSQL):
   - 镜像: postgres:16-alpine
   - 端口: 5433
   - 挂载数据卷到 ./data/langfuse-db

9. **prometheus** (指标采集):
   - 镜像: prom/prometheus:latest
   - 端口: 9090
   - 挂载 ./docker/prometheus/prometheus.yml

10. **grafana** (可视化面板):
    - 镜像: grafana/grafana:latest
    - 端口: 3001
    - 挂载 ./docker/grafana/dashboards 到仪表盘目录
    - 环境变量: GF_SERVER_ROOT_URL, GF_SECURITY_ADMIN_PASSWORD

11. **nginx** (反向代理/统一入口):
    - 镜像: nginx:1.25-alpine
    - 端口: 8080 (映射宿主机)
    - 挂载 ./docker/nginx/reverse-proxy.conf

所有服务加入自定义网络: `kb-network`（bridge 模式）。

### 6.2 创建 backend/Dockerfile

- 基础镜像: python:3.10-slim
- 工作目录: /app
- 安装系统依赖（build-essential 等）
- 复制 requirements.txt 并 pip install
- 复制 app 目录
- 启动命令: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

### 6.3 创建 docker/nginx/nginx.conf

Nginx 配置，中文注释说明每个 location 块的用途：
- `/` 映射到前端 guest 目录（访客端）
- `/admin` 映射到前端 admin 目录（管理端）
- `/assets/` 映射到前端 shared 目录（共享资源）
- 配置 gzip 压缩
- 配置缓存策略（静态资源 7 天，HTML 不缓存）

### 6.4 创建 docker/nginx/reverse-proxy.conf

反向代理 Nginx 配置，中文注释：
- 端口 8080 作为统一入口
- `/api/` 代理到 api:8000
- `/` 代理到 web:80
- `/grafana/` 代理到 grafana:3001
- `/langfuse/` 代理到 langfuse-server:3000
- 配置 CORS 头
- 配置请求体大小限制（文档上传: 100MB）
- 配置超时时间（SSE 流式: 600s）

### 6.5 创建 docker/postgres/init.sql

初始化 SQL 脚本，中文注释：
1. 创建数据库（如果不存在）
2. 创建 uuid-ossp 扩展
3. 开启 pg_trgm 扩展（用于全文检索）
4. 创建初始角色数据（admin、user、kb_admin 三个内置角色需要预先插入）

### 6.6 创建 docker/prometheus/prometheus.yml

Prometheus 配置，采集以下目标：
- prometheus 自身: 9090
- api 服务: api:8000/metrics
- postgres-exporter（如果需要单独部署）
- redis-exporter（如果需要单独部署）

scrape_interval: 15s

### 6.7 创建 .env.example（更新）

补充 Docker 相关环境变量（如果提示词 1 已创建，则检查并确保完整）：
- GRAFANA_ADMIN_PASSWORD
- LANGFUSE_NEXTAUTH_SECRET
- LANGFUSE_SALT
- LANGFUSE_ENCRYPTION_KEY
```

---

## 提示词 7：OpenAPI 契约文件（接口文档标准格式）

**目的**：生成独立的 OpenAPI 3.0 规范文件（JSON 格式），作为前后端团队的接口契约，不依赖服务器运行即可查看

**提示词文本**：

```
你是一个 API 文档工程师。请在项目根目录创建 contracts/ 目录，并生成完整的 OpenAPI 3.0 规范文件。这是前后端团队的接口契约，必须精确、完整。

## 任务

### 7.1 创建 contracts/openapi.json

生成完整的 OpenAPI 3.0.3 规范 JSON 文件，包含以下内容：

**info 部分**：
- title: "AI 知识库 RAG 平台 API"
- version: "2.1.0"
- description: 包含项目简介，标注"访客端"和"管理端"两组接口的区别

**servers 部分**：
- 本地开发: http://localhost:8080/api/v1
- Docker 部署: http://localhost:8080/api/v1

**security 部分**：Bearer JWT

**components/schemas 部分**：定义所有请求和响应的 Schema（与 Pydantic Schema 对应）

**paths 部分**：定义以下全部接口（完整的请求参数、响应格式、状态码）：

认证模块 (4 个接口):
- POST /auth/register - 用户注册
- POST /auth/login - 用户登录
- POST /auth/refresh - 刷新 Token
- GET /auth/me - 获取当前用户信息

用户管理 (6 个接口):
- GET /users - 用户列表
- GET /users/{id} - 用户详情
- PUT /users/{id} - 修改用户信息
- PATCH /users/{id}/status - 启用/禁用
- PUT /users/{id}/roles - 修改角色
- POST /users/{id}/reset-password - 重置密码

角色管理 (5 个接口):
- GET /roles - 角色列表
- POST /roles - 创建角色
- PUT /roles/{id} - 修改角色
- DELETE /roles/{id} - 删除角色
- PUT /roles/{id}/permissions - 配置权限

大模型管理 (5 个接口):
- GET /models - 模型列表
- POST /models - 添加模型
- PUT /models/{id} - 修改模型
- PATCH /models/{id}/status - 启用/禁用
- PUT /models/{id}/default - 设为默认

知识库管理 (8 个接口):
- GET /knowledge-bases - 知识库列表
- POST /knowledge-bases - 创建知识库
- GET /knowledge-bases/{id} - 知识库详情
- PUT /knowledge-bases/{id} - 修改知识库
- DELETE /knowledge-bases/{id} - 删除知识库
- POST /knowledge-bases/{id}/re-vectorize - 重新向量化
- GET /knowledge-bases/{id}/vectorize-status - 向量化进度
- PUT /knowledge-bases/{id}/permissions - 配置权限

文档管理 (9 个接口):
- GET /knowledge-bases/{kb_id}/documents - 文档列表
- POST /knowledge-bases/{kb_id}/documents/upload - 上传文档 (multipart/form-data)
- GET /knowledge-bases/{kb_id}/documents/{id} - 文档详情
- DELETE /knowledge-bases/{kb_id}/documents/{id} - 删除文档
- PUT /knowledge-bases/{kb_id}/documents/{id}/segment-rules - 分段规则
- POST /knowledge-bases/{kb_id}/documents/{id}/re-segment - 重新分段
- POST /knowledge-bases/{kb_id}/documents/{id}/normalize - 规范化
- GET /knowledge-bases/{kb_id}/documents/{id}/chunks - 分段预览
- PUT /knowledge-bases/{kb_id}/documents/{id}/chunks/{chunk_id} - 编辑分段

智能问答 (6 个接口):
- POST /qa/ask - 发送问题 (SSE 流式)
- GET /qa/sessions - 会话列表
- GET /qa/sessions/{id} - 会话历史
- PUT /qa/sessions/{id} - 重命名会话
- DELETE /qa/sessions/{id} - 删除会话
- POST /qa/feedback - 回答反馈

命中率测试 (8 个接口):
- GET /hit-tests/cases - 用例列表
- POST /hit-tests/cases - 创建用例
- PUT /hit-tests/cases/{id} - 编辑用例
- DELETE /hit-tests/cases/{id} - 删除用例
- POST /hit-tests/runs - 执行测试
- GET /hit-tests/runs - 运行记录
- GET /hit-tests/runs/{id} - 测试详情
- GET /hit-tests/runs/{id}/export - 导出 CSV

快照管理 (6 个接口):
- GET /knowledge-bases/{kb_id}/snapshots - 快照列表
- POST /knowledge-bases/{kb_id}/snapshots - 创建快照
- GET /knowledge-bases/{kb_id}/snapshots/{id} - 快照详情
- POST /knowledge-bases/{kb_id}/snapshots/{id}/preview - 差异预览
- POST /knowledge-bases/{kb_id}/snapshots/{id}/rollback - 回退
- DELETE /knowledge-bases/{kb_id}/snapshots/{id} - 删除快照

审计日志 (2 个接口):
- GET /audit/logs - 审计日志列表
- GET /audit/logs/{id} - 审计日志详情

系统监控 (2 个接口):
- GET /monitor/health - 健康检查
- GET /monitor/stats - 系统统计

每个接口标注：
- tags（分组）
- summary（简短说明）
- description（详细说明，含业务逻辑描述）
- security（是否需要认证）
- parameters（路径参数、查询参数）
- requestBody（请求体 Schema + 示例）
- responses（200/201/400/401/403/404/500，每个状态码示例响应体）

### 7.2 创建 contracts/README.md

说明接口契约文件的使用方式：
1. 将 openapi.json 导入 Swagger Editor 或 Postman 查看
2. 前端开发者参照此文件进行接口对接
3. 后端开发者参照此文件实现接口
4. 契约变更需团队评审
5. 契约版本与产品手册版本同步
```

---

## 提示词 8：前端骨架页面

**目的**：创建前端访客端和管理端的 HTML 骨架页面，包含蓝白配色、导航布局、基础交互

**提示词文本**：

```
你是一个前端开发工程师。请在 frontend/ 目录下创建前端骨架页面。所有代码必须包含中文注释。使用原生 HTML + CSS + JavaScript，蓝白配色（主色调 #1A73E8）。

## 技术要求

1. 主色调: #1A73E8，辅助色: #4A90D9, #0D47A1
2. 布局: 左侧导航栏 + 右侧内容区（管理端）；顶部导航栏 + 内容区（访客端）
3. 响应式设计: 桌面端优先，兼顾平板（768px 断点）
4. 组件风格: 简洁现代，圆角卡片，浅色背景
5. 不使用任何前端框架

## 任务

### 8.1 创建 frontend/shared/css/common.css

全局共享样式，中文注释说明每个区块的用途：
- CSS 变量定义（颜色、间距、圆角、阴影）
- 重置样式（margin/padding/box-sizing）
- 通用布局类（.container, .flex-row, .flex-col 等）
- 通用组件样式（按钮 .btn / .btn-primary / .btn-danger，卡片 .card，表格 .table，表单 .form-group，模态框 .modal，消息提示 .toast）
- 通用工具类（.text-center, .text-right, .mt-*, .mb-*, .hidden 等）

### 8.2 创建 frontend/shared/js/common.js

全局共享脚本：
- API 基础请求函数 `apiRequest(method, url, data, options)`，自动附加 Authorization header、处理 401 跳转登录、统一错误处理
- `formatDate(dateStr)` 日期格式化
- `formatFileSize(bytes)` 文件大小格式化
- `debounce(fn, delay)` 防抖函数
- `showToast(message, type)` 消息提示（支持 success/error/warning/info）
- `showConfirm(title, message)` 确认弹窗（返回 Promise）
- `getToken()` / `setToken(token)` / `clearToken()` Token 管理（localStorage）
- `isLoggedIn()` 登录状态检查
- `getUserInfo()` 获取当前用户信息（从 /api/v1/auth/me 缓存）

### 8.3 创建 frontend/guest/css/style.css

访客端专用样式（导入 common.css）：
- 顶部导航栏样式（白色背景，logo 蓝色，导航链接）
- 问答界面样式（消息气泡、输入框固定在底部、打字机效果）
- 引用卡片样式（来源信息、相关性分数）
- 登录/注册表单样式

### 8.4 创建 frontend/guest/js/qa.js

访客端问答页面的 JavaScript 骨架，中文注释：
- 会话管理：创建、切换、加载历史
- SSE 流式接收：EventSource 连接、chunk/citations/done/error 事件处理
- 消息渲染：用户消息（右对齐）、AI 消息（左对齐 + 引用展示）
- 输入框：发送按钮、Enter 快捷键
- 上传入口：根据登录状态显示/隐藏

### 8.5 创建 frontend/guest/index.html

访客端首页/问答页：
- 顶部导航栏：Logo（AI 知识库）、导航链接（智能问答、文档上传（需登录））
- 右侧区域：登录/注册/个人中心入口
- 主内容区：问答界面（消息列表 + 底部输入框）
- 未登录时显示登录/注册入口
- 引用 CSS: shared/css/common.css, guest/css/style.css
- 引用 JS: shared/js/common.js, guest/js/qa.js

### 8.6 创建 frontend/guest/login.html 和 register.html

登录页和注册页（样式与 index.html 一致）：
- 居中表单卡片
- 输入验证（前端基本校验）
- 错误提示
- 登录成功跳转首页

### 8.7 创建 frontend/admin/css/style.css

管理端专用样式（导入 common.css）：
- 左侧导航栏样式（220px 宽，深蓝背景 #0D47A1）
- 右侧内容区
- 仪表盘卡片网格
- 数据表格样式
- 表单（知识库创建/编辑）
- 标签和状态徽章

### 8.8 创建 frontend/admin/index.html

管理端仪表盘页面：
- 左侧导航栏：仪表盘、用户管理、角色管理、大模型管理、知识库管理、命中率测试、审计日志、系统监控
- 右上角：智能对话按钮（跳转访客端）+ 退出按钮
- 仪表盘内容区：知识库总数/文档总数/用户总数卡片、近 7 天问答量趋势图（预留占位）、系统状态指示器
- 顶部显示当前用户名和角色

### 8.9 创建管理端子页面骨架

为以下页面创建最小骨架 HTML（左侧导航栏 + 右侧空白内容区 + 页面标题）：
- frontend/admin/users.html
- frontend/admin/roles.html
- frontend/admin/models.html
- frontend/admin/knowledge-bases.html
- frontend/admin/kb-detail.html
- frontend/admin/documents.html
- frontend/admin/snapshots.html
- frontend/admin/hit-test.html
- frontend/admin/audit.html
- frontend/admin/monitor.html

每个子页面包含：
1. 左侧导航栏（与 index.html 一致，当前页高亮）
2. 右侧内容区：页面标题 + 占位内容 "功能开发中，请参照 API 契约进行实现"
3. 引用相同的 CSS 和 JS
```

---

## 提示词 9：开发工作流与 CI 配置

**目的**：创建代码质量工具配置、pre-commit hooks、GitHub CI 流水线、Alembic 迁移初始化

**提示词文本**：

```
你是一个开发工作流工程师。请创建项目开发协作所需的工具配置文件。所有配置文件必须包含中文注释。

## 任务

### 9.1 创建 pyproject.toml（项目根目录）

配置以下工具：

```toml
[project]
name = "ai-knowledge-base-rag"
version = "2.1.0"
description = "AI 知识库 RAG 平台"
requires-python = ">=3.10,<3.11"

[tool.black]
line-length = 120
target-version = ["py310"]

[tool.ruff]
line-length = 120
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]
```

### 9.2 创建 .pre-commit-config.yaml（项目根目录）

配置 pre-commit hooks：
- black（Python 代码格式化）
- ruff（Python 代码检查）
- trailing-whitespace（移除行尾空格）
- end-of-file-fixer（文件末尾换行）
- check-yaml（YAML 文件检查）
- check-json（JSON 文件检查）
- detect-private-key（检测私钥泄露）

### 9.3 创建 .github/workflows/ci.yml

GitHub Actions CI 流水线：
- 触发条件: push 到 main/develop，PR 到 main/develop
- 步骤:
  1. Checkout 代码
  2. 安装 Python 3.10
  3. 安装依赖
  4. 运行 ruff 代码检查
  5. 运行 black 格式检查（--check 模式）
  6. 运行 pytest 测试（需要 PostgreSQL/Redis 服务容器）

### 9.4 创建 backend/alembic/env.py 和 alembic.ini

Alembic 数据库迁移配置：
- alembic.ini: 使用异步数据库 URL（从 settings.DATABASE_URL 读取模板）
- env.py: 导入所有模型、配置异步引擎、设置自动迁移

迁移目录 backend/alembic/versions/ 已存在。

### 9.5 创建 backend/app/core/database.py

数据库连接管理模块：
1. `create_async_engine()` 创建异步引擎（含连接池配置）
2. `get_async_session()` 异步会话工厂
3. `init_db()` 初始化函数：创建所有表（如果不存在）
4. `get_db()` 依赖注入用的异步生成器（已在 dependencies.py 中引用）
5. 中文注释说明连接池大小、超时等配置参数

### 9.6 创建 backend/app/utils/__init__.py 和 backend/app/utils/helpers.py

工具函数模块骨架：
1. `generate_uuid() -> str` - 生成 UUID 字符串
2. `get_current_utc() -> datetime` - 获取当前 UTC 时间
3. `sanitize_filename(filename: str) -> str` - 文件名安全处理
4. `truncate_text(text: str, max_length: int) -> str` - 文本截断
5. 所有函数包含中文注释

### 9.7 创建 CONTRIBUTING.md（项目根目录）

团队贡献指南：
- 分支命名规则
- 提交信息格式
- Code Review 流程
- 开发环境搭建步骤
- 运行测试的命令
- API 开发流程（先定义 Schema -> 实现路由 -> 编写测试）
- 前端开发流程（参照 OpenAPI 契约 -> 实现页面 -> 联调）
```

---

## 提示词 10：初始化 Git 仓库并推送 GitHub

**目的**：将所有生成的文件初始化为 Git 仓库并推送到 GitHub

**提示词文本**：

```
请帮我初始化 Git 仓库并完成首次提交。

## 执行步骤

1. 在项目根目录执行 `git init`
2. 创建 .gitignore（如果提示词 1 已创建则跳过）
3. 执行 `git add .`
4. 执行 `git commit -m "chore: 初始化项目框架 -- AI 知识库 RAG 平台 V2.1.0

包含：
- 后端 FastAPI 应用骨架（12 个 API 路由模块、核心配置、安全认证、依赖注入）
- 数据模型层（19 个 SQLAlchemy ORM 模型）
- API 契约层（12 个 Pydantic Schema 模块）
- OpenAPI 3.0 规范文件（contracts/openapi.json）
- Docker Compose 部署配置（11 个服务）
- 前端骨架页面（访客端 + 管理端，蓝白配色）
- 开发工具配置（pre-commit、GitHub CI、Alembic 迁移）
- 环境变量模板和环境配置
"`

5. 提示我手动执行以下命令推送到 GitHub（不要自动执行）：
   ```
   git remote add origin <你的 GitHub 仓库地址>
   git branch -M main
   git push -u origin main
   ```
```

---

## 执行检查清单

完成以上 10 条提示词后，请确认以下全部项均已完成：

| 检查项 | 状态 |
|--------|------|
| 目录结构完整（backend/frontend/docker/contracts/data） | [ ] |
| .gitignore 包含必要忽略项 | [ ] |
| .env.example 包含全部配置项 | [ ] |
| requirements.txt 包含全部依赖 | [ ] |
| README.md 包含项目说明 | [ ] |
| core/config.py 支持全部配置组 | [ ] |
| core/security.py 支持 JWT 认证 | [ ] |
| core/dependencies.py 支持权限注入 | [ ] |
| core/database.py 支持异步连接 | [ ] |
| 19 个 SQLAlchemy 模型文件完整 | [ ] |
| 12 个 Pydantic Schema 模块完整 | [ ] |
| 12 个 API 路由文件完整（含 Swagger 注解） | [ ] |
| main.py 挂载所有路由 | [ ] |
| OpenAPI 3.0 契约文件完整 | [ ] |
| docker-compose.yml 包含 11 个服务 | [ ] |
| 后端 Dockerfile 完整 | [ ] |
| Nginx 配置完整（前端 + 反向代理） | [ ] |
| PostgreSQL 初始化脚本完整 | [ ] |
| Prometheus 配置完整 | [ ] |
| 前端访客端页面骨架（index/login/register/profile） | [ ] |
| 前端管理端页面骨架（11 个子页面） | [ ] |
| 前端共享样式和脚本 | [ ] |
| pre-commit 配置完整 | [ ] |
| GitHub CI 流水线配置完整 | [ ] |
| Alembic 迁移初始化 | [ ] |
| CONTRIBUTING.md 贡献指南 | [ ] |
| Git 仓库已初始化并完成首次提交 | [ ] |

---

## 后续步骤

框架搭建完成并推送 GitHub 后，团队成员应：

1. 克隆仓库到本地
2. 复制 .env.example 为 .env 并填写配置
3. 执行 `docker compose up -d` 启动开发环境
4. 访问 http://localhost:8080/docs 查看 Swagger UI 接口文档
5. 访问 http://localhost:8080 查看访客端
6. 访问 http://localhost:8080/admin 查看管理端
7. 参照产品手册和 OpenAPI 契约进行模块开发

---

> 本文档为项目框架搭建提示词集合，V1.0。每一条提示词可直接复制到 Cursor 中执行。执行顺序为 1 -> 10，不可跳过或打乱顺序。

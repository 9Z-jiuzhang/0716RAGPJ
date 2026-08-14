"""应用运行配置：对齐 .env.example，并扩展智能问答（5.6）参数。"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 .env（兼容从 backend/ 或根目录启动）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


def _hydrate_env_from_file(path: Path) -> None:
    """将 .env 键值注入 os.environ（不覆盖已有环境变量）；容忍非 UTF-8 编码。"""
    if not path.exists():
        return
    raw = path.read_bytes()
    text: str | None = None
    for enc in ("utf-8", "utf-8-sig", "gb18030", "cp936", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


_hydrate_env_from_file(_ENV_FILE)


class Settings(BaseSettings):
    """从环境变量加载配置；启动时已尝试从项目根 .env 注入。"""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
    )

    # ---------- 应用基础 ----------
    APP_NAME: str = "AI-KnowledgeBase-RAG"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = False
    # local=开发联调；cloud=云端生产（启动时强制校验密钥与 CORS）
    DEPLOYMENT_MODE: str = "local"
    SECRET_KEY: str = "change-me"
    # 对外公网根地址（含协议与域名，无尾斜杠），云端部署必填，例如 https://kb.example.com
    PUBLIC_BASE_URL: str = ""
    # 唯一超管账号 super 的登录密码：仅通过 .env 维护，页面不可改密
    SUPER_ADMIN_PASSWORD: str = "Super123!"
    # 是否在每次启动时把 DB 中 super 密码强制同步为 SUPER_ADMIN_PASSWORD（云端建议 false，首次引导后再关）
    SUPER_ADMIN_SYNC_PASSWORD: bool = True
    # 是否播种演示账号 admin / staff_*（云端务必 false）
    SEED_DEMO_USERS: bool = True
    # 是否开放公开注册接口（云端可关，仅管理员后台建号）
    AUTH_REGISTER_ENABLED: bool = True
    # 是否允许未鉴权访问 /metrics（云端建议 false，由内网 Prometheus 抓取或加鉴权）
    METRICS_PUBLIC: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = str(_PROJECT_ROOT / "data" / "logs")
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5

    # ---------- PostgreSQL ----------
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 9543
    POSTGRES_DB: str = "knowledge_base"
    POSTGRES_USER: str = "kb_user"
    POSTGRES_PASSWORD: str = "change-me"

    # ---------- Redis（会话热状态与并发隔离） ----------
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 9637
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # ---------- Chroma 向量库（Client-Server 模式） ----------
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000
    CHROMA_TENANT: str = "default_tenant"
    CHROMA_DATABASE: str = "default_database"

    # ---------- MinIO 对象存储 ----------
    MINIO_ENDPOINT: str = "minio:9900"
    MINIO_ACCESS_KEY: str = "change-me"
    MINIO_SECRET_KEY: str = "change-me"
    MINIO_BUCKET: str = "knowledge-base-docs"

    # ---------- LLM 大模型（默认千问 / DashScope 兼容模式） ----------
    LLM_PROVIDER: str = "dashscope"
    LLM_API_KEY: str = "change-me"
    LLM_MODEL: str = "qwen3.7-plus"
    LLM_BASE_URL: str = ""
    LLM_TIMEOUT_SECONDS: int = 120
    LLM_MAX_TOKENS: int = 2048
    # 千问等混合思考模型：主回答流式开启思考；推理写入 reasoning_content，由 LLMService 包装为 <think> 供前端气泡展示
    LLM_ENABLE_THINKING: bool = True
    # 思考 token 上限（厂商 extra_body.thinking_budget）；0 表示不传该字段
    LLM_THINKING_BUDGET: int = 2048

    # ---------- 轻量任务模型 ----------
    # Guard 与 Query 预处理默认复用主 LLM；Base URL / API Key 留空时继承主连接。
    LLM_GUARD_MODEL: str = "qwen3.7-plus"
    LLM_GUARD_BASE_URL: str = ""
    LLM_GUARD_API_KEY: str = ""
    LLM_GUARD_TIMEOUT_SECONDS: int = 20
    QA_QUERY_PROCESSING_MODEL: str = "qwen3.7-plus"
    QA_QUERY_PROCESSING_BASE_URL: str = ""
    QA_QUERY_PROCESSING_API_KEY: str = ""
    QA_QUERY_PROCESSING_TIMEOUT_SECONDS: int = 30

    # ---------- Embedding 嵌入模型（千问） ----------
    EMBEDDING_PROVIDER: str = "dashscope"
    EMBEDDING_API_KEY: str = "change-me"
    EMBEDDING_MODEL_NAME: str = "qwen3.7-text-embedding"
    EMBEDDING_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_TIMEOUT_SECONDS: int = 60
    # 每次向量化请求的最大文本条数；按厂商限额调整
    EMBEDDING_BATCH_SIZE: int = 10

    # ---------- Rerank 重排（默认千问 DashScope） ----------
    # 密钥为空时服务会安全降级为原始检索排序，不中断知识库问答。
    RERANK_PROVIDER: str = "dashscope"
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = "qwen3-vl-rerank"
    RERANK_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"
    RERANK_TIMEOUT_SECONDS: int = 30
    # 重排前扩大候选集，避免只对最终 Top-K 重排而失去纠正召回顺序的意义。
    RERANK_CANDIDATE_MULTIPLIER: int = 4

    # ---------- Langfuse（默认自建 compose 服务；也可指向 SaaS） ----------
    LANGFUSE_HOST: str = "http://langfuse-web:9310"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_REDACT_MAX_LEN: int = 500

    # ---------- JWT 认证 ----------
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # 逗号分隔的允许来源；同域反代可留空或写具体 https://domain。生产禁止使用 *
    CORS_ORIGINS: str = "*"
    CORS_ALLOW_CREDENTIALS: bool = True

    # ---------- 快照策略 ----------
    SNAPSHOT_MAX_COUNT: int = 50
    SNAPSHOT_RETENTION_DAYS: int = 90

    # ---------- 文档上传 ----------
    MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024
    VIRUS_SCAN_ENABLED: bool = False
    CLAMAV_HOST: str = "localhost"
    CLAMAV_PORT: int = 3310

    # ---------- 限流 ----------
    RATE_LIMIT_ENABLED: bool = True

    # ---------- 外部数据源（只读接入） ----------
    DATA_SOURCE_ENCRYPTION_KEY: str = ""
    DATA_SOURCE_ALLOWED_HOSTS: str = ""
    DATA_SOURCE_ALLOWED_PORTS: str = ""
    DATA_SOURCE_CONNECT_TIMEOUT_SECONDS: int = 10
    DATA_SOURCE_QUERY_TIMEOUT_SECONDS: int = 30
    DATA_SOURCE_MAX_PREVIEW_ROWS: int = 100
    DATA_SOURCE_MAX_PAGE_SIZE: int = 500
    DATA_SOURCE_MAX_IMPORT_ROWS: int = 10000
    DATA_SOURCE_MAX_IMPORT_BYTES: int = 10 * 1024 * 1024
    DATA_SOURCE_MAX_POOL_SIZE: int = 5
    DATA_SOURCE_ALLOW_SQLITE: bool = True

    # ---------- 外部开放 API ----------
    EXTERNAL_API_KEY_PEPPER: str = ""
    EXTERNAL_API_DEFAULT_RATE_LIMIT: int = 60
    EXTERNAL_API_MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024

    # ---------- 智能问答与会话记忆（产品手册 5.6） ----------
    QA_CONTEXT_WINDOW: int = 10
    QA_SESSION_TTL_MINUTES: int = 30
    # 闲置超过该分钟数的 active 会话 → expired（清 Redis，历史仍可查）
    QA_SESSION_IDLE_EXPIRE_MINUTES: int = 30
    # 后台扫描闲置会话的间隔（秒）
    QA_SESSION_EXPIRE_SWEEP_SECONDS: int = 60
    # ---------- 问答历史保留策略 ----------
    # 所有身份只保留最近 7 天且最多 20 轮；后台定期物理删除，单次问答后也会立即裁剪。
    QA_HISTORY_RETENTION_DAYS: int = 7
    QA_HISTORY_MAX_TURNS: int = 20
    QA_HISTORY_RETENTION_SWEEP_SECONDS: int = 300
    QA_DEFAULT_STRATEGY: str = "hybrid"
    QA_DEFAULT_TOP_K: int = 5
    # 上下文跟进问抬升 top_k，缓解关键段挤不出前三
    QA_FOLLOWUP_TOP_K: int = 5
    # 跟进问合并上轮引文分段（粘性证据）；默认开启
    QA_STICKY_EVIDENCE_ENABLED: bool = True
    QA_STICKY_EVIDENCE_CAP: int = 8
    # 命中后补同文档邻段（标题/正文拆开场景）
    QA_NEIGHBOR_CHUNKS_ENABLED: bool = True
    QA_NEIGHBOR_CHUNK_RADIUS: int = 1
    QA_RELEVANCE_THRESHOLD: float = 0.3
    QA_RRF_K: int = 60
    QA_GUEST_SESSION_TTL_MINUTES: int = 30
    # ---------- 用户 Query 预处理 ----------
    # 默认关闭改写；上下文追问可由业务路由按请求临时开启。
    QA_QUERY_REWRITE_ENABLED: bool = False
    QA_QUERY_EXPANSION_ENABLED: bool = False
    # 扩展 Query 数量限制在 0-5；开启时默认只生成 1 条，减少检索与融合开销。
    QA_QUERY_EXPANSION_COUNT: int = 1
    QA_HYDE_ENABLED: bool = False
    # 改写、扩展和 HyDE 合并为一次结构化调用，限制输出长度以控制耗时与成本。
    QA_QUERY_PROCESSING_MAX_TOKENS: int = 768
    # ---------- 六维优化功能开关（默认保守；语义直答默认仅观察） ----------
    CONVERSATION_ROUTER_V2_ENABLED: bool = True
    PREVIOUS_ANSWER_TRANSFORM_ENABLED: bool = True
    SESSION_STORE_V2_ENABLED: bool = False
    MODEL_CONFIG_REGISTRY_V2_ENABLED: bool = False
    QA_EXACT_CACHE_ENABLED: bool = False
    QA_SEMANTIC_CACHE_ENABLED: bool = False
    QA_SEMANTIC_CACHE_OBSERVE_ONLY: bool = True
    QA_RETRIEVAL_CACHE_ENABLED: bool = False
    QA_QUEUE_ENABLED: bool = False
    SCHEDULER_EXTERNAL_ENABLED: bool = False
    ANALYTICS_PIPELINE_V2_ENABLED: bool = True
    VECTOR_DUAL_WRITE_ENABLED: bool = False
    VECTOR_SHADOW_READ_ENABLED: bool = False
    # chroma | alibaba
    VECTOR_READ_PROVIDER: str = "chroma"
    # 语义直答统一相似度阈值与分差（可被角色/知识库覆盖，不低于组织下限）
    QA_SEMANTIC_SIMILARITY_THRESHOLD: float = 0.80
    QA_SEMANTIC_MIN_MARGIN: float = 0.05
    QA_SEMANTIC_MIN_QUALITY: float = 0.60
    # 模型并发有界信号量（0 表示不限制）
    MODEL_MAX_CONCURRENT_GENERATIONS: int = 20
    QA_MAX_QUEUE_WAIT_SECONDS: int = 60
    # ---------- 按角色缓存知识库 ----------
    ROLE_CACHE_DEFAULT_INTERVAL_DAYS: int = 7
    ROLE_CACHE_DOCUMENT_QUESTION_COUNT: int = 20
    ROLE_CACHE_HISTORY_QUESTION_COUNT: int = 5
    # 单次分析选取有限片段与字符，防止周期任务提示词无界增长。
    ROLE_CACHE_DOCUMENT_CHUNK_LIMIT: int = 30
    ROLE_CACHE_DOCUMENT_CHARS_PER_CHUNK: int = 800
    ROLE_CACHE_LLM_MAX_TOKENS: int = 4096
    ROLE_CACHE_SCHEDULER_POLL_SECONDS: int = 3600
    # 过渡期：停止角色缓存写入，命中仅只读回退
    ROLE_CACHE_WRITE_ENABLED: bool = False
    ROLE_CACHE_READONLY_FALLBACK: bool = True
    # ---------- 知识库 FAQ 主缓存 ----------
    FAQ_MASTER_SWITCH: bool = True
    FAQ_GENERATION_ENABLED: bool = True
    FAQ_DEBUG_SKIP_WRITE: bool = False
    FAQ_DEBUG_SKIP_READ: bool = False
    FAQ_PER_DOCUMENT_COUNT: int = 25
    FAQ_PER_KB_LIMIT: int = 500
    FAQ_KB_DAILY_LIMIT: int = 500
    FAQ_TENANT_CONCURRENT_LIMIT: int = 3
    FAQ_QUALITY_THRESHOLD: float = 0.7
    FAQ_SIMILARITY_THRESHOLD: float = 0.85
    FAQ_REJECT_DISABLE_THRESHOLD: int = 3
    FAQ_REDIS_CACHE_TTL_SECONDS: int = 900
    FAQ_DOCUMENT_CHUNK_BATCH_SIZE: int = 12
    FAQ_DOCUMENT_CHARS_PER_CHUNK: int = 800
    FAQ_LLM_MAX_TOKENS: int = 4096
    FAQ_TENANT_ID: str = "default"
    FAQ_SENSITIVE_PATTERNS: list[str] = [
        r"\d{15,18}",
        r"1[3-9]\d{9}",
        r"[\u4e00-\u9fa5]{2,4}薪[资酬]",
    ]
    # ---------- LLM Guard 与意图识别 ----------
    LLM_GUARD_ENABLED: bool = True
    # 本地规则无法明确归类时才调用 LLM 分类器，兼顾安全性与缓存节省效果。
    LLM_GUARD_CLASSIFIER_ENABLED: bool = True
    LLM_GUARD_BLOCK_THRESHOLD: float = 0.65
    # 默认分类器不可用时放行，但高风险本地规则始终生效；高安全环境可改为 true。
    LLM_GUARD_FAIL_CLOSED: bool = False
    LLM_GUARD_PREVIEW_MAX_CHARS: int = 200
    # ---------- RAGAS 评估 ----------
    RAGAS_ENABLED: bool = True
    RAGAS_DO_NOT_TRACK: bool = True
    RAGAS_DEFAULT_SAMPLE_LIMIT: int = 10
    RAGAS_MAX_SAMPLE_LIMIT: int = 50
    RAGAS_MAX_CONTEXTS_PER_SAMPLE: int = 10
    RAGAS_CONTEXT_MAX_CHARS: int = 3000
    # 检索无命中时：默认仅固定拒答（prefer abstain）；显式开启后才对白名单意图写参考答案
    QA_FALLBACK_LLM_ENABLED: bool = False
    # 可选：无命中时附加轻量联网检索结果，供参考答案提示词使用（无 API Key，默认关闭）
    QA_FALLBACK_WEB_SEARCH_ENABLED: bool = False

    @property
    def database_url(self) -> str:
        """返回 SQLAlchemy asyncpg 异步连接地址。"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL(self) -> str:  # noqa: N802
        """兼容旧代码的数据库连接地址。"""
        return self.database_url

    @property
    def redis_url(self) -> str:
        """返回 Redis 异步客户端连接 URL。"""
        if self.REDIS_PASSWORD:
            from urllib.parse import quote

            pwd = quote(self.REDIS_PASSWORD, safe="")
            return f"redis://:{pwd}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def cors_origin_list(self) -> list[str]:
        """解析 CORS 允许来源列表。"""
        raw = (self.CORS_ORIGINS or "").strip()
        if not raw:
            return []
        return [part.strip() for part in raw.split(",") if part.strip()]

    def assert_cloud_ready(self) -> None:
        """DEPLOYMENT_MODE=cloud 时拒绝占位密钥，避免带着默认口令上线。"""
        if (self.DEPLOYMENT_MODE or "local").strip().lower() != "cloud":
            return
        weak_markers = {"", "change-me", "<请填写>", "Super123!", "Admin123!", "Staff123!"}
        problems: list[str] = []
        if (self.SECRET_KEY or "").strip() in weak_markers:
            problems.append("SECRET_KEY")
        if (self.JWT_SECRET_KEY or "").strip() in weak_markers:
            problems.append("JWT_SECRET_KEY")
        if (self.POSTGRES_PASSWORD or "").strip() in weak_markers:
            problems.append("POSTGRES_PASSWORD")
        if (self.MINIO_ACCESS_KEY or "").strip() in weak_markers or (
            self.MINIO_SECRET_KEY or ""
        ).strip() in weak_markers:
            problems.append("MINIO_ACCESS_KEY/MINIO_SECRET_KEY")
        if (self.SUPER_ADMIN_PASSWORD or "").strip() in {"", "Super123!", "<请填写>"}:
            problems.append("SUPER_ADMIN_PASSWORD")
        if "*" in self.cors_origin_list or not self.cors_origin_list:
            problems.append("CORS_ORIGINS 须为具体 https 域名（禁止 *）")
        if not (self.PUBLIC_BASE_URL or "").strip().startswith("https://"):
            problems.append("PUBLIC_BASE_URL 须为 https:// 开头的公网根地址")
        if problems:
            raise RuntimeError("云端安全检查未通过，请修改 .env 后重启：" + "；".join(problems))

    @property
    def chroma_http_url(self) -> str:
        """返回 Chroma HTTP 服务根地址，供健康检查使用。"""
        return f"http://{self.CHROMA_HOST}:{self.CHROMA_PORT}"

    @property
    def llm_api_base_resolved(self) -> str | None:
        """解析 LLM API Base URL；空字符串视为未配置。"""
        return self.LLM_BASE_URL.strip() or None

    @property
    def embedding_api_base_resolved(self) -> str | None:
        """解析 Embedding API Base URL。"""
        return self.EMBEDDING_API_BASE.strip() or None


@lru_cache
def get_settings() -> Settings:
    """缓存配置单例，避免重复解析环境变量。"""
    return Settings()


settings = get_settings()

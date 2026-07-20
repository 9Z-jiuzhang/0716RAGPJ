"""应用运行配置：对齐 .env.example，并扩展智能问答（5.6）参数。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 .env（兼容从 backend/ 或根目录启动）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """从项目根目录 .env 加载环境变量，供全局单例使用。"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 应用基础 ----------
    APP_NAME: str = "AI-KnowledgeBase-RAG"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me"
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = str(_PROJECT_ROOT / "data" / "logs")
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5

    # ---------- PostgreSQL ----------
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "knowledge_base"
    POSTGRES_USER: str = "kb_user"
    POSTGRES_PASSWORD: str = "change-me"

    # ---------- Redis（会话热状态与并发隔离） ----------
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # ---------- Chroma 向量库（Client-Server 模式） ----------
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000
    CHROMA_TENANT: str = "default_tenant"
    CHROMA_DATABASE: str = "default_database"

    # ---------- MinIO 对象存储 ----------
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "change-me"
    MINIO_SECRET_KEY: str = "change-me"
    MINIO_BUCKET: str = "knowledge-base-docs"

    # ---------- LLM 大模型 ----------
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = "change-me"
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = ""
    LLM_TIMEOUT_SECONDS: int = 120
    LLM_MAX_TOKENS: int = 2048

    # ---------- 轻量任务模型 ----------
    # Guard 与 Query 预处理不再占用主回答模型。默认使用 MiniMax 官方高速文本模型；
    # Base URL 与 API Key 留空时复用主 LLM 的连接信息，但客户端和连接池相互独立。
    LLM_GUARD_MODEL: str = "MiniMax-M2.7-highspeed"
    LLM_GUARD_BASE_URL: str = ""
    LLM_GUARD_API_KEY: str = ""
    LLM_GUARD_TIMEOUT_SECONDS: int = 20
    QA_QUERY_PROCESSING_MODEL: str = "MiniMax-M2.7-highspeed"
    QA_QUERY_PROCESSING_BASE_URL: str = ""
    QA_QUERY_PROCESSING_API_KEY: str = ""
    QA_QUERY_PROCESSING_TIMEOUT_SECONDS: int = 30

    # ---------- Embedding 嵌入模型 ----------
    EMBEDDING_PROVIDER: str = "dashscope"
    EMBEDDING_API_KEY: str = "change-me"
    EMBEDDING_MODEL_NAME: str = "text-embedding-v3"
    EMBEDDING_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_TIMEOUT_SECONDS: int = 60
    # 每次向量化请求的最大文本条数；阿里云 DashScope text-embedding-v3 上限为 10
    EMBEDDING_BATCH_SIZE: int = 10

    # ---------- Rerank 重排 ----------
    # 默认采用 Cohere 官方多语言 Rerank。密钥为空时服务会安全降级为原始检索排序，
    # 不会因为外部重排服务不可用而中断知识库问答。
    RERANK_PROVIDER: str = "cohere"
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = "rerank-v4.0-pro"
    RERANK_BASE_URL: str = "https://api.cohere.ai"
    RERANK_TIMEOUT_SECONDS: int = 30
    # 重排前扩大候选集，避免只对最终 Top-K 重排而失去纠正召回顺序的意义。
    RERANK_CANDIDATE_MULTIPLIER: int = 4

    # ---------- Langfuse（云端或自建兼容端点；Compose 不含 Langfuse 容器） ----------
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_REDACT_MAX_LEN: int = 500

    # ---------- JWT 认证 ----------
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: str = "*"

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
    QA_RELEVANCE_THRESHOLD: float = 0.3
    QA_RRF_K: int = 60
    QA_GUEST_SESSION_TTL_MINUTES: int = 30
    # ---------- 用户 Query 预处理 ----------
    # 默认仅开启改写；Query 扩展与 HyDE 属于高耗时增强项，管理员可在会话页随时开启。
    QA_QUERY_REWRITE_ENABLED: bool = True
    QA_QUERY_EXPANSION_ENABLED: bool = False
    # 扩展 Query 数量限制在 0-5；开启时默认只生成 1 条，减少检索与融合开销。
    QA_QUERY_EXPANSION_COUNT: int = 1
    QA_HYDE_ENABLED: bool = False
    # 改写、扩展和 HyDE 合并为一次结构化调用，限制输出长度以控制耗时与成本。
    QA_QUERY_PROCESSING_MAX_TOKENS: int = 768
    # ---------- 按角色缓存知识库 ----------
    ROLE_CACHE_DEFAULT_INTERVAL_DAYS: int = 7
    ROLE_CACHE_DOCUMENT_QUESTION_COUNT: int = 20
    ROLE_CACHE_HISTORY_QUESTION_COUNT: int = 5
    # 单次分析选取有限片段与字符，防止周期任务提示词无界增长。
    ROLE_CACHE_DOCUMENT_CHUNK_LIMIT: int = 30
    ROLE_CACHE_DOCUMENT_CHARS_PER_CHUNK: int = 800
    ROLE_CACHE_LLM_MAX_TOKENS: int = 4096
    ROLE_CACHE_SCHEDULER_POLL_SECONDS: int = 3600
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
    # 检索无命中时：先声明知识库未找到依据，再调用 LLM 给出「参考答案」（不伪造 KB 引用）
    QA_FALLBACK_LLM_ENABLED: bool = True
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
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

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

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

    # ---------- Embedding 嵌入模型 ----------
    EMBEDDING_PROVIDER: str = "dashscope"
    EMBEDDING_API_KEY: str = "change-me"
    EMBEDDING_MODEL_NAME: str = "text-embedding-v3"
    EMBEDDING_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_TIMEOUT_SECONDS: int = 60

    # ---------- Rerank（可选） ----------
    RERANK_PROVIDER: str = ""
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = ""

    # ---------- Langfuse ----------
    LANGFUSE_HOST: str = "http://langfuse-server:3000"
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
    QA_DEFAULT_STRATEGY: str = "hybrid"
    QA_DEFAULT_TOP_K: int = 5
    QA_RELEVANCE_THRESHOLD: float = 0.3
    QA_RRF_K: int = 60
    QA_GUEST_SESSION_TTL_MINUTES: int = 30

    @property
    def database_url(self) -> str:
        """返回 SQLAlchemy asyncpg 异步连接地址。"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL(self) -> str:
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

"""应用运行配置。【对齐 .env.example 键名】"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 .env（兼容从 backend/ 或根目录启动）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """从项目根目录 .env 加载环境变量。"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    APP_NAME: str = "AI-KnowledgeBase-RAG"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me"
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = str(_PROJECT_ROOT / "data" / "logs")
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5

    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "knowledge_base"
    POSTGRES_USER: str = "kb_user"
    POSTGRES_PASSWORD: str = "change-me"

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000

    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "change-me"
    MINIO_SECRET_KEY: str = "change-me"
    MINIO_BUCKET: str = "knowledge-base-docs"

    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = "change-me"
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = ""

    EMBEDDING_PROVIDER: str = "dashscope"
    EMBEDDING_API_KEY: str = "change-me"
    EMBEDDING_MODEL_NAME: str = "text-embedding-v3"
    EMBEDDING_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    RERANK_PROVIDER: str = ""
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = ""

    LANGFUSE_HOST: str = "http://langfuse-server:3000"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_REDACT_MAX_LEN: int = 500

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: str = "*"

    SNAPSHOT_MAX_COUNT: int = 50
    SNAPSHOT_RETENTION_DAYS: int = 90

    MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024

    @property
    def database_url(self) -> str:
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
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

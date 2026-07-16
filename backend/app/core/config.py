"""认证模块运行配置。"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从项目根目录 .env 加载环境变量。"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    APP_NAME: str = "AI-KnowledgeBase-RAG"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me"

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

    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_API_KEY: str = "change-me"
    EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"
    EMBEDDING_API_BASE: str = ""

    RERANK_PROVIDER: str = ""
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = ""

    LANGFUSE_HOST: str = "http://localhost:3000"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: str = "*"

    LOG_LEVEL: str = "INFO"

    SNAPSHOT_MAX_COUNT: int = 50
    SNAPSHOT_RETENTION_DAYS: int = 90

    @property
    def database_url(self) -> str:
        """返回 SQLAlchemy asyncpg 连接地址。"""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def DATABASE_URL(self) -> str:
        """兼容旧代码的数据库连接地址。"""
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
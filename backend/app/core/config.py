"""应用配置模块。

使用 pydantic-settings 从 .env 与环境变量加载配置，全局单例 settings 供各层引用。
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/app/core/config.py -> 上溯三级）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """全局配置类，按业务域分组。"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 应用配置组 ----------
    APP_NAME: str = "AI-KnowledgeBase-RAG"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me"

    # ---------- 数据库配置组 ----------
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "knowledge_base"
    POSTGRES_USER: str = "kb_user"
    POSTGRES_PASSWORD: str = "change-me"

    @property
    def DATABASE_URL(self) -> str:
        """异步 PostgreSQL 连接串（asyncpg）。"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ---------- Redis 配置组 ----------
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    @property
    def REDIS_URL(self) -> str:
        """Redis 连接串。"""
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # ---------- Chroma 配置组 ----------
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000

    # ---------- MinIO 配置组 ----------
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minio"
    MINIO_SECRET_KEY: str = "minio123"
    MINIO_BUCKET: str = "knowledge-base-docs"

    # ---------- LLM 配置组 ----------
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: Optional[str] = None

    # ---------- Embedding 配置组 ----------
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    # 兼容工作区 .env 中的别名
    EMBEDDING_MODEL_NAME: Optional[str] = None
    EMBEDDING_API_BASE: Optional[str] = None

    # ---------- Rerank 配置组 ----------
    RERANK_PROVIDER: Optional[str] = None
    RERANK_API_KEY: Optional[str] = None
    RERANK_MODEL: Optional[str] = None

    # ---------- Langfuse 配置组 ----------
    LANGFUSE_HOST: str = "http://langfuse-server:3000"
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None

    # ---------- JWT 配置组 ----------
    JWT_SECRET_KEY: str = "change-me-jwt"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---------- 快照策略（产品手册 5.8.4）----------
    SNAPSHOT_MAX_COUNT: int = Field(default=50, description="每个知识库最多保留的快照数")
    SNAPSHOT_RETENTION_DAYS: int = Field(default=90, description="快照保留天数，超期自动清理")

    # ---------- 日志配置组 ----------
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """返回缓存的 Settings 单例。"""
    return Settings()


settings = get_settings()

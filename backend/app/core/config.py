from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    应用配置类

    从环境变量或 .env 文件加载配置项，与 .env.example 保持一致
    """

    # 应用基础配置
    APP_NAME: str = "AI-KnowledgeBase-RAG"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # 数据库 PostgreSQL 配置
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "kb_user"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "knowledge_base"

    # Redis 配置
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    # 向量数据库 Chroma 配置
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000

    # 对象存储 MinIO 配置
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "knowledge-base-docs"

    # LLM 大模型配置
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = ""

    # Embedding 嵌入模型配置
    EMBEDDING_PROVIDER: str = "dashscope"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL_NAME: str = "text-embedding-v3"
    EMBEDDING_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Rerank 重排模型配置（可选）
    RERANK_PROVIDER: str = ""
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = ""

    # Langfuse 可观测配置
    LANGFUSE_HOST: str = "http://langfuse-server:3000"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""

    # JWT 认证配置
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # API 配置
    API_V1_STR: str = "/api/v1"

    class Config:
        """配置类的配置"""

        env_file = ".env"
        case_sensitive = False

    @property
    def database_url(self) -> str:
        """
        构造数据库连接 URL

        返回:
            PostgreSQL 连接字符串
        """
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()

"""认证模块运行配置。"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从项目根目录 .env 加载环境变量。"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    APP_NAME: str = "AI-KnowledgeBase-RAG"
    APP_VERSION: str = "2.1.0"
    DEBUG: bool = False
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "knowledge_base"
    POSTGRES_USER: str = "kb_user"
    POSTGRES_PASSWORD: str = "change-me"
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: str = "*"
    # 快照策略（产品手册 5.8.4）
    SNAPSHOT_MAX_COUNT: int = 50
    SNAPSHOT_RETENTION_DAYS: int = 90

    @property
    def database_url(self) -> str:
        """返回 SQLAlchemy asyncpg 连接地址。"""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

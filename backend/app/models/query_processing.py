"""Query 预处理运行策略模型。

全系统只保留一条默认策略。将开关保存在数据库而不是浏览器或进程内存中，
可以保证多实例部署时管理员修改立即对所有问答节点生效。
"""

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class QueryProcessingConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """管理员可调整的 Query 改写、扩展与 HyDE 开关。"""

    __tablename__ = "query_processing_configs"

    config_key: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        default="default",
        comment="单例配置键，当前固定为 default",
    )
    rewrite_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expansion_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expansion_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hyde_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

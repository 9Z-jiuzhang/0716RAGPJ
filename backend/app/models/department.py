"""部门模型。

成员仍通过 users.department（单一编码）关联；
知识库通过 kb_departments 多对多关联部门 code（兼容列 knowledge_bases.department）。
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Department(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """组织部门。"""

    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True, comment="部门编码")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="部门名称")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="说明")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")

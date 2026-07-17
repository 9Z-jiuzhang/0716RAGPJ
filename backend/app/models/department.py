"""部门 ORM 模型。

成员与知识库仍通过 users.department / knowledge_bases.department
字符串 code 关联，便于兼容现有部门隔离逻辑。
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Department(TimestampMixin, Base):
    """组织部门：编码、名称、介绍。"""

    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, comment="部门编码，如 A / B / HR"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="部门名称")
    description: Mapped[str | None] = mapped_column(Text, comment="部门介绍")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

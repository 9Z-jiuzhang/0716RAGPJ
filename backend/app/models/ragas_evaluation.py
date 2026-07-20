"""RAGAS 评估运行与逐样本结果模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RagasEvaluationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """一次针对指定知识库的 RAGAS 评估运行。"""

    __tablename__ = "ragas_evaluation_runs"
    __table_args__ = (Index("ix_ragas_runs_kb_created", "kb_id", "created_at"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="pending/running/completed/failed",
    )
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metric_scores: Mapped[dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="各 RAGAS 指标的样本平均分",
    )
    metric_success_counts: Mapped[dict[str, int]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="各指标成功评分的样本数",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[RagasEvaluationItem]] = relationship(
        "RagasEvaluationItem",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class RagasEvaluationItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """单个问答样本的输入、上下文、分数与 RAGAS 原因说明。"""

    __tablename__ = "ragas_evaluation_items"
    __table_args__ = (Index("ix_ragas_items_run_created", "run_id", "created_at"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ragas_evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    qa_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("qa_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_input: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_contexts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_scores: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    metric_reasons: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    metric_errors: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[RagasEvaluationRun] = relationship("RagasEvaluationRun", back_populates="items")

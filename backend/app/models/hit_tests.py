"""命中率测试模型。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class TestCases(TimestampMixin, Base):
    """
    测试用例数据库模型

    存储命中率测试的问题集合定义
    """

    __tablename__ = "test_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text)
    question_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    questions = relationship(
        "TestQuestions",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TestQuestions(Base):
    """
    测试问题数据库模型

    存储单个测试问题及其期望命中结果
    """

    __tablename__ = "test_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_doc_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True))
    )
    expected_chunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True))
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    case = relationship("TestCases", back_populates="questions")


class TestRuns(TimestampMixin, Base):
    """
    测试运行数据库模型

    存储每次命中率测试的执行记录和统计结果
    """

    __tablename__ = "test_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="SET NULL"),
    )
    kb_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False
    )
    doc_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    similarity_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recall_at_k: Mapped[float | None] = mapped_column(Float)
    mrr: Mapped[float | None] = mapped_column(Float)
    avg_elapsed_ms: Mapped[float | None] = mapped_column(Float)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results = relationship(
        "TestResults",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TestResults(Base):
    """
    单题测试结果数据库模型

    存储每个问题的测试结果详情
    """

    __tablename__ = "test_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    is_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hit_rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    actual_chunks: Mapped[list[str]] = mapped_column(ARRAY(Text))

    run = relationship("TestRuns", back_populates="results")

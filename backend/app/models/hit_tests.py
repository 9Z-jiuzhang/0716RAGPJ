from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 基础模型类"""
    pass


class TestCases(Base):
    """
    测试用例数据库模型

    存储命中率测试的问题集合定义
    """
    __tablename__ = "test_cases"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="用例 ID",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="用例名称",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        comment="用例描述",
    )
    question_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="问题数量",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )

    # 关系定义
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

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="问题 ID",
    )
    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        comment="关联的测试用例 ID",
    )
    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="问题文本",
    )
    expected_doc_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        comment="期望命中的文档 ID 列表",
    )
    expected_chunk_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        comment="期望命中的分段 ID 列表",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="排序顺序",
    )

    # 关系定义
    case = relationship(
        "TestCases",
        back_populates="questions",
    )


class TestRuns(Base):
    """
    测试运行数据库模型

    存储每次命中率测试的执行记录和统计结果
    """
    __tablename__ = "test_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="运行 ID",
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="SET NULL"),
        comment="关联的测试用例 ID",
    )
    kb_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        nullable=False,
        comment="测试的知识库 ID 列表",
    )
    doc_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        comment="文档 ID 列表（可选过滤）",
    )
    strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="检索策略",
    )
    top_k: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        comment="返回条数",
    )
    similarity_threshold: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="相似度阈值",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        comment="状态",
    )
    total_questions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="总问题数",
    )
    hit_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="命中数",
    )
    recall_at_k: Mapped[float | None] = mapped_column(
        Float,
        comment="Recall@K",
    )
    mrr: Mapped[float | None] = mapped_column(
        Float,
        comment="Mean Reciprocal Rank",
    )
    avg_elapsed_ms: Mapped[float | None] = mapped_column(
        Float,
        comment="平均耗时（毫秒）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="完成时间",
    )

    # 关系定义
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

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="结果 ID",
    )
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
        comment="关联的测试运行 ID",
    )
    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="问题文本",
    )
    is_hit: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否命中",
    )
    hit_rank: Mapped[int | None] = mapped_column(
        Integer,
        comment="命中排名",
    )
    score: Mapped[float | None] = mapped_column(
        Float,
        comment="相似度分数",
    )
    strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="检索策略",
    )
    elapsed_ms: Mapped[int | None] = mapped_column(
        Integer,
        comment="耗时（毫秒）",
    )
    actual_chunks: Mapped[list[dict]] = mapped_column(
        ARRAY(Text),
        comment="实际检索到的分段列表（JSON 序列化）",
    )

    # 关系定义
    run = relationship(
        "TestRuns",
        back_populates="results",
    )

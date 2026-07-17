"""命中率测试相关 Schema。"""

import uuid
from datetime import datetime
from typing import Literal

from app.schemas.common import PaginationResponse
from pydantic import BaseModel, Field


class TestQuestion(BaseModel):
    """测试问题"""

    question: str = Field(description="问题文本")
    expected_doc_ids: list[uuid.UUID] | None = Field(
        None, description="期望命中的文档 ID 列表"
    )
    expected_chunk_ids: list[uuid.UUID] | None = Field(
        None, description="期望命中的分段 ID 列表"
    )


class CreateTestCaseRequest(BaseModel):
    """创建测试用例请求"""

    name: str = Field(description="用例名称")
    description: str | None = Field(None, description="用例描述")
    questions: list[TestQuestion] = Field(description="问题列表")


class UpdateTestCaseRequest(BaseModel):
    """更新测试用例请求"""

    name: str | None = Field(None, description="用例名称")
    description: str | None = Field(None, description="用例描述")
    questions: list[TestQuestion] | None = Field(None, description="问题列表")


class TestCaseResponse(BaseModel):
    """测试用例响应"""

    id: uuid.UUID = Field(description="用例 ID")
    name: str = Field(description="用例名称")
    description: str | None = Field(None, description="用例描述")
    question_count: int = Field(description="问题数量")
    questions: list[TestQuestion] = Field(description="问题列表")
    created_at: datetime = Field(description="创建时间")


class TestCaseListResponse(PaginationResponse[TestCaseResponse]):
    """测试用例列表响应"""

    items: list[TestCaseResponse] = Field(description="用例列表")


class TestRunRequest(BaseModel):
    """执行测试请求"""

    case_id: uuid.UUID | None = Field(
        None, description="用例 ID，不传则使用 questions 做单题/临时测试"
    )
    kb_ids: list[uuid.UUID] = Field(description="知识库 ID 列表", min_length=1)
    doc_ids: list[uuid.UUID] | None = Field(
        None, description="文档 ID 列表（可选过滤）"
    )
    strategy: Literal["vector", "fulltext", "hybrid"] = Field(description="检索策略")
    top_k: int = Field(5, description="返回条数", ge=1, le=20)
    similarity_threshold: float = Field(0.5, description="相似度阈值", ge=0, le=1)
    questions: list[str] | None = Field(
        None, description="临时问题列表（仅当 case_id 为空时使用）"
    )


class TestRunResponse(BaseModel):
    """测试运行响应"""

    id: uuid.UUID = Field(description="运行 ID")
    case_id: uuid.UUID | None = Field(None, description="关联的用例 ID")
    kb_ids: list[uuid.UUID] = Field(description="测试的知识库 ID 列表")
    strategy: Literal["vector", "fulltext", "hybrid"] = Field(description="检索策略")
    top_k: int = Field(description="返回条数")
    status: Literal["running", "completed", "failed"] = Field(description="状态")
    total_questions: int = Field(description="总问题数")
    hit_count: int = Field(description="命中数")
    recall_at_k: float | None = Field(None, description="Recall@K")
    mrr: float | None = Field(None, description="Mean Reciprocal Rank")
    avg_elapsed_ms: float | None = Field(None, description="平均耗时（毫秒）")
    completed_at: datetime | None = Field(None, description="完成时间")


class TestRunListResponse(PaginationResponse[TestRunResponse]):
    """测试运行列表响应"""

    items: list[TestRunResponse] = Field(description="运行记录列表")


class TestResultResponse(BaseModel):
    """单题测试结果响应"""

    id: uuid.UUID = Field(description="结果 ID")
    question: str = Field(description="问题文本")
    is_hit: bool = Field(description="是否命中")
    hit_rank: int | None = Field(None, description="命中排名")
    score: float | None = Field(None, description="相似度分数")
    strategy: Literal["vector", "fulltext", "hybrid"] = Field(description="检索策略")
    elapsed_ms: int | None = Field(None, description="耗时（毫秒）")
    actual_chunks: list[dict] = Field(description="实际检索到的分段列表")


class CompareTestRequest(BaseModel):
    """多策略对比测试请求"""

    case_id: uuid.UUID = Field(description="用例 ID")
    kb_ids: list[uuid.UUID] = Field(description="知识库 ID 列表", min_length=1)
    doc_ids: list[uuid.UUID] | None = Field(None, description="文档 ID 列表")
    strategies: list[Literal["vector", "fulltext", "hybrid"]] = Field(
        default_factory=lambda: ["vector", "fulltext", "hybrid"],
        min_length=2,
        description="待对比的检索策略列表",
    )
    top_k: int = Field(5, ge=1, le=20)
    similarity_threshold: float = Field(0.5, ge=0, le=1)


class StrategyCompareItem(BaseModel):
    strategy: Literal["vector", "fulltext", "hybrid"]
    is_hit: bool | None = None
    hit_rank: int | None = None
    score: float | None = None
    elapsed_ms: int | None = None


class QuestionCompareRow(BaseModel):
    question: str
    by_strategy: list[StrategyCompareItem]


class CompareTestResponse(BaseModel):
    case_id: uuid.UUID
    runs: list[TestRunResponse]
    side_by_side: list[QuestionCompareRow]

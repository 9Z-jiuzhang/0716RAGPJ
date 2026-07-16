from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.hit_tests import TestCases, TestQuestions, TestResults, TestRuns
from app.schemas.hit_tests import (
    CreateTestCaseRequest,
    TestCaseListResponse,
    TestCaseResponse,
    TestQuestion,
    TestResultResponse,
    TestRunListResponse,
    TestRunRequest,
    TestRunResponse,
    UpdateTestCaseRequest,
)


class HitTestService:
    """
    命中率测试服务

    提供测试用例管理和测试运行执行的核心业务逻辑
    """

    def __init__(self, db: Session):
        """
        初始化服务

        参数:
            db: 数据库会话
        """
        self.db = db

    def list_test_cases(self, page: int, page_size: int) -> TestCaseListResponse:
        """
        获取测试用例列表（分页）

        参数:
            page: 页码，从 1 开始
            page_size: 每页条数

        返回:
            分页的测试用例列表响应
        """
        # 计算分页偏移量
        offset = (page - 1) * page_size

        # 查询总记录数
        total = self.db.execute(
            select(func.count(TestCases.id))
        ).scalar_one_or_none() or 0

        # 查询当前页数据
        query = (
            select(TestCases)
            .order_by(TestCases.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        cases = self.db.execute(query).scalars().all()

        # 转换为响应格式
        items = [self._convert_case_to_response(case) for case in cases]

        return TestCaseListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_test_case(self, case_id: UUID) -> TestCaseResponse | None:
        """
        获取单个测试用例详情

        参数:
            case_id: 测试用例 ID

        返回:
            测试用例响应，不存在时返回 None
        """
        # 查询测试用例
        case = self.db.get(TestCases, case_id)
        if not case:
            return None

        # 转换为响应格式
        return self._convert_case_to_response(case)

    def create_test_case(self, request: CreateTestCaseRequest) -> TestCaseResponse:
        """
        创建测试用例

        参数:
            request: 创建测试用例请求

        返回:
            创建后的测试用例响应
        """
        # 创建测试用例数据库记录
        case = TestCases(
            id=uuid4(),
            name=request.name,
            description=request.description,
            question_count=len(request.questions),
            created_at=datetime.utcnow(),
        )
        self.db.add(case)
        self.db.flush()

        # 创建测试问题记录
        for idx, question in enumerate(request.questions):
            test_question = TestQuestions(
                id=uuid4(),
                case_id=case.id,
                question=question.question,
                expected_doc_ids=question.expected_doc_ids,
                expected_chunk_ids=question.expected_chunk_ids,
                sort_order=idx,
            )
            self.db.add(test_question)

        # 提交事务
        self.db.commit()
        self.db.refresh(case)

        # 转换为响应格式
        return self._convert_case_to_response(case)

    def update_test_case(
        self,
        case_id: UUID,
        request: UpdateTestCaseRequest,
    ) -> TestCaseResponse | None:
        """
        更新测试用例

        参数:
            case_id: 测试用例 ID
            request: 更新测试用例请求

        返回:
            更新后的测试用例响应，不存在时返回 None
        """
        # 查询测试用例
        case = self.db.get(TestCases, case_id)
        if not case:
            return None

        # 更新名称（如果提供）
        if request.name is not None:
            case.name = request.name

        # 更新描述（如果提供）
        if request.description is not None:
            case.description = request.description

        # 更新问题列表（如果提供）
        if request.questions is not None:
            # 删除现有问题记录
            self.db.execute(
                TestQuestions.__table__.delete().where(TestQuestions.case_id == case_id)
            )

            # 创建新的问题记录
            for idx, question in enumerate(request.questions):
                test_question = TestQuestions(
                    id=uuid4(),
                    case_id=case.id,
                    question=question.question,
                    expected_doc_ids=question.expected_doc_ids,
                    expected_chunk_ids=question.expected_chunk_ids,
                    sort_order=idx,
                )
                self.db.add(test_question)

            # 更新问题数量
            case.question_count = len(request.questions)

        # 提交事务
        self.db.commit()
        self.db.refresh(case)

        # 转换为响应格式
        return self._convert_case_to_response(case)

    def delete_test_case(self, case_id: UUID) -> bool:
        """
        删除测试用例

        参数:
            case_id: 测试用例 ID

        返回:
            删除成功返回 True，不存在返回 False
        """
        # 查询测试用例
        case = self.db.get(TestCases, case_id)
        if not case:
            return False

        # 删除关联的测试问题记录
        self.db.execute(
            TestQuestions.__table__.delete().where(TestQuestions.case_id == case_id)
        )

        # 删除测试用例
        self.db.delete(case)
        self.db.commit()

        return True

    def execute_test_run(self, request: TestRunRequest) -> TestRunResponse:
        """
        执行命中率测试运行

        参数:
            request: 测试运行请求

        返回:
            测试运行响应（异步任务受理）
        """
        # 获取测试问题列表
        questions: list[TestQuestion] = []

        if request.case_id:
            # 从测试用例获取问题
            case = self.db.get(TestCases, request.case_id)
            if case:
                query = (
                    select(TestQuestions)
                    .where(TestQuestions.case_id == request.case_id)
                    .order_by(TestQuestions.sort_order)
                )
                db_questions = self.db.execute(query).scalars().all()
                questions = [
                    TestQuestion(
                        question=q.question,
                        expected_doc_ids=q.expected_doc_ids,
                        expected_chunk_ids=q.expected_chunk_ids,
                    )
                    for q in db_questions
                ]
        elif request.questions:
            # 使用临时问题列表
            questions = [
                TestQuestion(question=q) for q in request.questions
            ]

        # 创建测试运行记录
        run = TestRuns(
            id=uuid4(),
            case_id=request.case_id,
            kb_ids=request.kb_ids,
            strategy=request.strategy,
            top_k=request.top_k,
            status="running",
            total_questions=len(questions),
            hit_count=0,
            created_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.flush()

        # 执行每个问题的检索测试
        hit_count = 0
        total_elapsed_ms = 0.0

        for question in questions:
            # 记录单个问题开始时间
            start_time = time.perf_counter()

            # 执行检索（调用检索服务）
            results = self._execute_retrieval(
                question=question.question,
                kb_ids=request.kb_ids,
                doc_ids=request.doc_ids,
                strategy=request.strategy,
                top_k=request.top_k,
                similarity_threshold=request.similarity_threshold,
            )

            # 计算耗时
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            total_elapsed_ms += elapsed_ms

            # 判断是否命中
            is_hit, hit_rank = self._check_hit(
                results=results,
                expected_doc_ids=question.expected_doc_ids,
                expected_chunk_ids=question.expected_chunk_ids,
            )

            if is_hit:
                hit_count += 1

            # 记录单题测试结果（实际块数据以 JSON 字符串列表存储）
            actual_chunks_json = [json.dumps(r) for r in results]
            test_result = TestResults(
                id=uuid4(),
                run_id=run.id,
                question=question.question,
                is_hit=is_hit,
                hit_rank=hit_rank,
                score=results[0]["score"] if results else None,
                strategy=request.strategy,
                elapsed_ms=elapsed_ms,
                actual_chunks=actual_chunks_json,
            )
            self.db.add(test_result)

        # 计算评估指标
        recall_at_k = hit_count / len(questions) if questions else None
        avg_elapsed_ms = total_elapsed_ms / len(questions) if questions else None

        # 更新测试运行状态和统计
        run.status = "completed"
        run.hit_count = hit_count
        run.recall_at_k = recall_at_k
        run.mrr = self._calculate_mrr(run.id)
        run.avg_elapsed_ms = avg_elapsed_ms
        run.completed_at = datetime.utcnow()

        # 提交事务
        self.db.commit()
        self.db.refresh(run)

        # 转换为响应格式
        return self._convert_run_to_response(run)

    def list_test_runs(self, page: int, page_size: int) -> TestRunListResponse:
        """
        获取测试运行列表（分页）

        参数:
            page: 页码，从 1 开始
            page_size: 每页条数

        返回:
            分页的测试运行列表响应
        """
        # 计算分页偏移量
        offset = (page - 1) * page_size

        # 查询总记录数
        total = self.db.execute(
            select(func.count(TestRuns.id))
        ).scalar_one_or_none() or 0

        # 查询当前页数据
        query = (
            select(TestRuns)
            .order_by(TestRuns.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        runs = self.db.execute(query).scalars().all()

        # 转换为响应格式
        items = [self._convert_run_to_response(run) for run in runs]

        return TestRunListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_test_run(self, run_id: UUID) -> dict | None:
        """
        获取测试运行详情（含每题明细）

        参数:
            run_id: 测试运行 ID

        返回:
            测试运行详情字典，不存在时返回 None
        """
        # 查询测试运行
        run = self.db.get(TestRuns, run_id)
        if not run:
            return None

        # 查询单题测试结果
        query = select(TestResults).where(TestResults.run_id == run_id)
        results = self.db.execute(query).scalars().all()

        # 构建响应数据，字段名与契约保持一致
        return {
            "summary": self._convert_run_to_response(run),
            "results": [self._convert_result_to_response(result) for result in results],
        }

    def export_test_run_csv(self, run_id: UUID) -> str | None:
        """
        导出测试结果为 CSV 格式

        参数:
            run_id: 测试运行 ID

        返回:
            CSV 字符串，不存在时返回 None
        """
        # 查询测试运行和结果
        run = self.db.get(TestRuns, run_id)
        if not run:
            return None

        query = select(TestResults).where(TestResults.run_id == run_id)
        results = self.db.execute(query).scalars().all()

        # 构建 CSV 内容
        lines = [
            "问题,是否命中,命中排名,分数,策略,耗时(ms)",
        ]
        for result in results:
            lines.append(
                f"{result.question},{result.is_hit},{result.hit_rank or ''},"
                f"{result.score or ''},{result.strategy},{result.elapsed_ms or ''}"
            )

        return "\n".join(lines)

    def _execute_retrieval(
        self,
        question: str,
        kb_ids: list[UUID],
        doc_ids: list[UUID] | None,
        strategy: str,
        top_k: int,
        similarity_threshold: float,
    ) -> list[dict]:
        """
        执行检索（框架阶段占位实现）

        参数:
            question: 查询问题
            kb_ids: 知识库 ID 列表
            doc_ids: 文档 ID 列表（可选过滤）
            strategy: 检索策略
            top_k: 返回条数
            similarity_threshold: 相似度阈值

        返回:
            检索结果列表，每个元素包含 doc_id、chunk_id、content、score 等字段
        """
        # 框架阶段：返回模拟数据
        # 实际实现应调用检索服务（如 LangChain、LlamaIndex 等）
        return [
            {
                "doc_id": str(uuid4()),
                "chunk_id": str(uuid4()),
                "content": f"模拟检索结果内容 - {question}",
                "score": round(0.7 + (hash(question) % 30) / 100, 2),
            }
            for _ in range(min(top_k, 3))
        ]

    def _check_hit(
        self,
        results: list[dict],
        expected_doc_ids: list[UUID] | None,
        expected_chunk_ids: list[UUID] | None,
    ) -> tuple[bool, int | None]:
        """
        判断是否命中期望结果

        参数:
            results: 检索结果列表
            expected_doc_ids: 期望命中的文档 ID 列表
            expected_chunk_ids: 期望命中的分段 ID 列表

        返回:
            (是否命中, 命中排名)
        """
        if not expected_doc_ids and not expected_chunk_ids:
            # 无期望结果，默认视为未命中
            return False, None

        for rank, result in enumerate(results, 1):
            result_doc_id = UUID(result.get("doc_id", ""))
            result_chunk_id = UUID(result.get("chunk_id", ""))

            # 检查是否命中期望文档或分段
            doc_hit = expected_doc_ids and result_doc_id in expected_doc_ids
            chunk_hit = expected_chunk_ids and result_chunk_id in expected_chunk_ids

            if doc_hit or chunk_hit:
                return True, rank

        return False, None

    def _calculate_mrr(self, run_id: UUID) -> float | None:
        """
        计算 Mean Reciprocal Rank (MRR)

        参数:
            run_id: 测试运行 ID

        返回:
            MRR 值，无结果时返回 None
        """
        # 查询测试结果
        query = select(TestResults).where(TestResults.run_id == run_id)
        results = self.db.execute(query).scalars().all()

        if not results:
            return None

        # 计算 MRR
        reciprocal_ranks = []
        for result in results:
            if result.hit_rank and result.hit_rank > 0:
                reciprocal_ranks.append(1.0 / result.hit_rank)
            else:
                reciprocal_ranks.append(0.0)

        return sum(reciprocal_ranks) / len(reciprocal_ranks)

    def _convert_case_to_response(self, case: Any) -> TestCaseResponse:
        """
        将数据库模型转换为测试用例响应

        参数:
            case: 测试用例数据库记录

        返回:
            测试用例响应
        """
        # 查询关联的问题列表
        query = (
            select(TestQuestions)
            .where(TestQuestions.case_id == case.id)
            .order_by(TestQuestions.sort_order)
        )
        db_questions = self.db.execute(query).scalars().all()

        questions = [
            TestQuestion(
                question=q.question,
                expected_doc_ids=q.expected_doc_ids,
                expected_chunk_ids=q.expected_chunk_ids,
            )
            for q in db_questions
        ]

        return TestCaseResponse(
            id=case.id,
            name=case.name,
            description=case.description,
            question_count=case.question_count,
            questions=questions,
            created_at=case.created_at,
        )

    def _convert_run_to_response(self, run: Any) -> TestRunResponse:
        """
        将数据库模型转换为测试运行响应

        参数:
            run: 测试运行数据库记录

        返回:
            测试运行响应
        """
        return TestRunResponse(
            id=run.id,
            case_id=run.case_id,
            kb_ids=run.kb_ids,
            strategy=run.strategy,
            top_k=run.top_k,
            status=run.status,
            total_questions=run.total_questions,
            hit_count=run.hit_count,
            recall_at_k=run.recall_at_k,
            mrr=run.mrr,
            avg_elapsed_ms=run.avg_elapsed_ms,
            completed_at=run.completed_at,
        )

    def _convert_result_to_response(self, result: Any) -> TestResultResponse:
        """
        将数据库模型转换为单题测试结果响应

        参数:
            result: 单题测试结果数据库记录

        返回:
            单题测试结果响应
        """
        # 将 JSON 字符串列表解析为 dict 列表
        actual_chunks = [json.loads(chunk) for chunk in (result.actual_chunks or [])]
        return TestResultResponse(
            id=result.id,
            question=result.question,
            is_hit=result.is_hit,
            hit_rank=result.hit_rank,
            score=result.score,
            strategy=result.strategy,
            elapsed_ms=result.elapsed_ms,
            actual_chunks=actual_chunks,
        )

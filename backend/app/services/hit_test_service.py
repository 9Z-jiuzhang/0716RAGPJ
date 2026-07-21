"""命中率测试服务。"""

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hit_tests import TestCases, TestQuestions, TestResults, TestRuns
from app.schemas.hit_tests import (
    CompareTestRequest,
    CompareTestResponse,
    CreateTestCaseRequest,
    TestCaseListResponse,
    TestCaseResponse,
    TestExample,
    TestQuestion,
    TestResultResponse,
    TestRunListResponse,
    TestRunRequest,
    TestRunResponse,
    UpdateTestCaseRequest,
)

logger = logging.getLogger(__name__)


class HitTestService:
    """
    命中率测试服务

    提供测试用例管理和测试运行执行的核心业务逻辑
    """

    def __init__(self, db: AsyncSession):
        """
        初始化服务

        参数:
            db: 异步数据库会话
        """
        self.db = db

    async def list_test_cases(self, page: int, page_size: int) -> TestCaseListResponse:
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
        total = await self.db.scalar(select(func.count(TestCases.id))) or 0

        # 查询当前页数据
        query = select(TestCases).order_by(TestCases.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(query)
        cases = result.scalars().all()

        # 转换为响应格式
        items = [await self._convert_case_to_response(case) for case in cases]

        return TestCaseListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_test_case(self, case_id: uuid.UUID) -> TestCaseResponse | None:
        """
        获取单个测试用例详情

        参数:
            case_id: 测试用例 ID

        返回:
            测试用例响应，不存在时返回 None
        """
        # 查询测试用例
        case = await self.db.get(TestCases, case_id)
        if not case:
            return None

        # 转换为响应格式
        return await self._convert_case_to_response(case)

    async def create_test_case(self, request: CreateTestCaseRequest) -> TestCaseResponse:
        """
        创建测试用例

        参数:
            request: 创建测试用例请求

        返回:
            创建后的测试用例响应
        """
        # 合并 questions 与 examples；无期望标注的用例按检索冒烟使用
        questions = self._merge_questions_and_examples(request.questions, request.examples)

        # 创建测试用例数据库记录
        case = TestCases(
            id=uuid.uuid4(),
            name=request.name,
            description=request.description,
            question_count=len(questions),
        )
        self.db.add(case)
        await self.db.flush()

        # 创建测试问题记录
        for idx, question in enumerate(questions):
            test_question = TestQuestions(
                id=uuid.uuid4(),
                case_id=case.id,
                question=question.question,
                expected_doc_ids=question.expected_doc_ids,
                expected_chunk_ids=question.expected_chunk_ids,
                expected_answer=question.expected_answer,
                context=question.context,
                sort_order=idx,
            )
            self.db.add(test_question)

        # 提交事务
        await self.db.commit()
        await self.db.refresh(case)

        # 转换为响应格式
        return await self._convert_case_to_response(case)

    async def update_test_case(
        self,
        case_id: uuid.UUID,
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
        case = await self.db.get(TestCases, case_id)
        if not case:
            return None

        # 更新名称（如果提供）
        if request.name is not None:
            case.name = request.name

        # 更新描述（如果提供）
        if request.description is not None:
            case.description = request.description

        # 更新问题列表（如果提供 questions 或 examples）
        if request.questions is not None or request.examples is not None:
            questions = self._merge_questions_and_examples(request.questions or [], request.examples)
            # 删除现有问题记录
            await self.db.execute(TestQuestions.__table__.delete().where(TestQuestions.case_id == case_id))

            # 创建新的问题记录
            for idx, question in enumerate(questions):
                test_question = TestQuestions(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    question=question.question,
                    expected_doc_ids=question.expected_doc_ids,
                    expected_chunk_ids=question.expected_chunk_ids,
                    expected_answer=question.expected_answer,
                    context=question.context,
                    sort_order=idx,
                )
                self.db.add(test_question)

            # 更新问题数量
            case.question_count = len(questions)

        # 提交事务
        await self.db.commit()
        await self.db.refresh(case)

        # 转换为响应格式
        return await self._convert_case_to_response(case)

    async def delete_test_case(self, case_id: uuid.UUID) -> bool:
        """
        删除测试用例

        参数:
            case_id: 测试用例 ID

        返回:
            删除成功返回 True，不存在返回 False
        """
        # 查询测试用例
        case = await self.db.get(TestCases, case_id)
        if not case:
            return False

        # 删除测试用例（级联删除关联的问题记录）
        await self.db.delete(case)
        await self.db.commit()

        return True

    async def execute_test_run(self, request: TestRunRequest) -> TestRunResponse:
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
            case = await self.db.get(TestCases, request.case_id)
            if not case:
                raise ValueError("测试用例不存在")
            query = (
                select(TestQuestions).where(TestQuestions.case_id == request.case_id).order_by(TestQuestions.sort_order)
            )
            result = await self.db.execute(query)
            db_questions = result.scalars().all()
            questions = [
                TestQuestion(
                    question=q.question,
                    expected_doc_ids=q.expected_doc_ids,
                    expected_chunk_ids=q.expected_chunk_ids,
                )
                for q in db_questions
            ]
        elif request.questions:
            # 临时问题：无期望标注，仅用于检索冒烟（有召回即计命中），不代表真实命中率。
            questions = [TestQuestion(question=str(q).strip()) for q in request.questions if str(q).strip()]
            if not questions:
                raise ValueError("临时问题列表不能为空")

        if not questions:
            raise ValueError("没有可执行的测试问题")
        # 有期望标注的题目仍校验；纯问题用例走检索冒烟，不强制期望文档。
        labeled = [item for item in questions if item.expected_doc_ids or item.expected_chunk_ids]
        if labeled and len(labeled) != len(questions):
            raise ValueError("同一用例中不能混用「仅问题」与「带期望文档/分段」的题目")
        if labeled:
            self._validate_ground_truth(questions)

        # 创建测试运行记录
        run = TestRuns(
            id=uuid.uuid4(),
            case_id=request.case_id,
            kb_ids=request.kb_ids,
            doc_ids=request.doc_ids,
            strategy=request.strategy,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            status="running",
            total_questions=len(questions),
            hit_count=0,
        )
        self.db.add(run)
        await self.db.flush()

        # 执行每个问题的检索测试
        hit_count = 0
        total_elapsed_ms = 0.0
        relevance_scores: list[float] = []

        for question in questions:
            # 记录单个问题开始时间
            start_time = time.perf_counter()

            # 执行检索（调用检索服务）
            results = await self._execute_retrieval(
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
            # 单题得分 = 命中片段相关度；未命中不计分。
            matched_score = None
            if is_hit and hit_rank and 1 <= hit_rank <= len(results):
                raw = results[hit_rank - 1].get("score")
                if raw is not None:
                    matched_score = float(raw)
                    relevance_scores.append(matched_score)
            test_result = TestResults(
                id=uuid.uuid4(),
                run_id=run.id,
                question=question.question,
                is_hit=is_hit,
                hit_rank=hit_rank,
                score=matched_score,
                strategy=request.strategy,
                elapsed_ms=elapsed_ms,
                actual_chunks=actual_chunks_json,
            )
            self.db.add(test_result)

        # 计算评估指标
        recall_at_k = hit_count / len(questions) if questions else None
        avg_elapsed_ms = total_elapsed_ms / len(questions) if questions else None
        # 综合得分 = 各题命中片段相关度的算术平均；全未命中时为 0。
        avg_relevance = (
            (sum(relevance_scores) / len(relevance_scores)) if relevance_scores else (0.0 if questions else None)
        )

        # 更新测试运行状态和统计
        run.status = "completed"
        run.hit_count = hit_count
        run.recall_at_k = recall_at_k
        run.mrr = await self._calculate_mrr(run.id)
        run.avg_elapsed_ms = avg_elapsed_ms
        run.completed_at = datetime.now()
        # 暂存到实例属性供响应序列化（表无独立 score 列时由结果回算，此处作兜底）
        run._avg_relevance_score = avg_relevance  # type: ignore[attr-defined]

        # 提交事务
        await self.db.commit()
        await self.db.refresh(run)

        # 转换为响应格式
        return self._convert_run_to_response(run, avg_relevance=avg_relevance)

    async def list_test_runs(self, page: int, page_size: int) -> TestRunListResponse:
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
        total = await self.db.scalar(select(func.count(TestRuns.id))) or 0

        # 查询当前页数据
        query = select(TestRuns).order_by(TestRuns.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(query)
        runs = result.scalars().all()

        # 转换为响应格式
        items = [self._convert_run_to_response(run) for run in runs]

        return TestRunListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_test_run(self, run_id: uuid.UUID) -> dict | None:
        """
        获取测试运行详情（含每题明细）

        参数:
            run_id: 测试运行 ID

        返回:
            测试运行详情字典，不存在时返回 None
        """
        # 查询测试运行
        run = await self.db.get(TestRuns, run_id)
        if not run:
            return None

        # 查询单题测试结果
        query = select(TestResults).where(TestResults.run_id == run_id)
        result = await self.db.execute(query)
        results = result.scalars().all()

        # 构建响应数据，字段名与契约保持一致
        return {
            "summary": self._convert_run_to_response(run),
            "results": [self._convert_result_to_response(result) for result in results],
        }

    async def export_test_run_csv(self, run_id: uuid.UUID) -> str | None:
        """
        导出测试结果为 CSV 格式

        参数:
            run_id: 测试运行 ID

        返回:
            CSV 字符串，不存在时返回 None
        """
        # 查询测试运行和结果
        run = await self.db.get(TestRuns, run_id)
        if not run:
            return None

        query = select(TestResults).where(TestResults.run_id == run_id)
        result = await self.db.execute(query)
        results = result.scalars().all()

        # 构建 CSV 内容
        lines = ["问题,是否命中,命中排名,命中片段相关度,策略,耗时(ms)"]
        for result_item in results:
            lines.append(
                f"{result_item.question},{result_item.is_hit},{result_item.hit_rank or ''},"
                f"{result_item.score or ''},{result_item.strategy},{result_item.elapsed_ms or ''}"
            )

        return "\n".join(lines)

    async def delete_test_run(self, run_id: uuid.UUID) -> bool:
        """删除单条测试运行记录（级联删除明细）。"""
        run = await self.db.get(TestRuns, run_id)
        if not run:
            return False
        await self.db.delete(run)
        await self.db.commit()
        return True

    async def delete_all_test_runs(self) -> int:
        """清空全部测试运行记录，返回删除条数。"""
        total = await self.db.scalar(select(func.count(TestRuns.id))) or 0
        if total:
            await self.db.execute(TestRuns.__table__.delete())
            await self.db.commit()
        return int(total)

    async def compare_strategies(self, request: CompareTestRequest) -> CompareTestResponse:
        """同一用例在多种检索策略下并排对比。"""
        from app.schemas.hit_tests import (
            CompareTestResponse,
            QuestionCompareRow,
            StrategyCompareItem,
            TestRunRequest,
        )

        strategies = list(dict.fromkeys(request.strategies))
        if len(strategies) < 2:
            raise ValueError("至少需要两种策略进行对比")

        runs = []
        for strategy in strategies:
            run_req = TestRunRequest(
                case_id=request.case_id,
                kb_ids=request.kb_ids,
                doc_ids=request.doc_ids,
                strategy=strategy,
                top_k=request.top_k,
                similarity_threshold=request.similarity_threshold,
            )
            runs.append(await self.execute_test_run(run_req))

        # 按问题聚合各策略明细
        by_question: dict[str, list[StrategyCompareItem]] = {}
        for run in runs:
            detail = await self.get_test_run(run.id)
            if not detail:
                continue
            for item in detail["results"]:
                row = by_question.setdefault(item.question, [])
                row.append(
                    StrategyCompareItem(
                        strategy=item.strategy,
                        is_hit=item.is_hit,
                        hit_rank=item.hit_rank,
                        score=item.score,
                        elapsed_ms=item.elapsed_ms,
                    )
                )

        side_by_side = [QuestionCompareRow(question=q, by_strategy=items) for q, items in by_question.items()]
        return CompareTestResponse(case_id=request.case_id, runs=runs, side_by_side=side_by_side)

    async def _execute_retrieval(
        self,
        question: str,
        kb_ids: list[uuid.UUID],
        doc_ids: list[uuid.UUID] | None,
        strategy: str,
        top_k: int,
        similarity_threshold: float,
    ) -> list[dict]:
        """
        执行检索：复用问答模块 HybridRetriever（vector / fulltext / hybrid）。

        返回:
            检索结果列表，每个元素包含 doc_id、chunk_id、content、score 等字段
        """
        from sqlalchemy import select

        from app.models.knowledge_base import KnowledgeBase
        from app.retrieval.hybrid import hybrid_retriever
        from app.retrieval.types import KBTarget, RetrievalStrategy

        if not kb_ids:
            return []

        rows = list(
            (
                await self.db.scalars(
                    select(KnowledgeBase).where(
                        KnowledgeBase.id.in_(kb_ids),
                        KnowledgeBase.status == "active",
                    )
                )
            ).all()
        )
        targets: list[KBTarget] = []
        for kb in rows:
            version = (kb.current_index_version or "").strip()
            if not version:
                continue
            targets.append(KBTarget(kb_id=kb.id, name=kb.name, index_version=version))

        if not targets:
            return []

        strategy_key: RetrievalStrategy = strategy if strategy in ("vector", "fulltext", "hybrid") else "hybrid"
        result = await hybrid_retriever.retrieve(
            self.db,
            question,
            targets,
            strategy=strategy_key,
            top_k=top_k,
            relevance_threshold=similarity_threshold,
        )

        hits = result.hits
        # 混合/向量失败且无召回时，强制降级全文并放宽阈值，避免「库内有文却 0 命中」
        if not hits and strategy_key != "fulltext":
            logger.warning(
                "命中率测试主检索无结果 strategy=%s，降级全文检索 question=%s",
                strategy_key,
                question[:80],
            )
            result = await hybrid_retriever.retrieve(
                self.db,
                question,
                targets,
                strategy="fulltext",
                top_k=top_k,
                relevance_threshold=0.0,
            )
            hits = result.hits

        if doc_ids:
            wanted = {str(d) for d in doc_ids}
            hits = [h for h in hits if h.doc_id in wanted]

        return [
            {
                "doc_id": h.doc_id,
                "chunk_id": h.chunk_id,
                "content": (h.content or "")[:800],
                "score": round(float(h.score), 6),
                "chunk_index": h.chunk_index,
                "doc_name": h.doc_name,
            }
            for h in hits
        ]

    def _check_hit(
        self,
        results: list[dict],
        expected_doc_ids: list[uuid.UUID] | None,
        expected_chunk_ids: list[uuid.UUID] | None,
    ) -> tuple[bool, int | None]:
        """
        判断是否命中期望结果。

        - 配置了 expected_doc_ids / expected_chunk_ids：Top-K 内命中任一期望即算命中
        - 未配置期望（临时问题冒烟）：Top-K 有任意召回即算命中
        """
        if not results:
            return False, None

        if not expected_doc_ids and not expected_chunk_ids:
            return True, 1

        expected_docs = {str(x) for x in (expected_doc_ids or [])}
        expected_chunks = {str(x) for x in (expected_chunk_ids or [])}

        for rank, result in enumerate(results, 1):
            result_doc_id = str(result.get("doc_id") or "")
            result_chunk_id = str(result.get("chunk_id") or "")
            doc_hit = bool(expected_docs and result_doc_id in expected_docs)
            chunk_hit = bool(expected_chunks and result_chunk_id in expected_chunks)
            if doc_hit or chunk_hit:
                return True, rank

        return False, None

    @staticmethod
    def _merge_questions_and_examples(
        questions: list[TestQuestion] | None,
        examples: list[TestExample] | None,
    ) -> list[TestQuestion]:
        merged: list[TestQuestion] = list(questions or [])
        for item in examples or []:
            merged.append(
                TestQuestion(
                    question=item.question,
                    expected_doc_ids=item.expected_doc_ids,
                    expected_chunk_ids=item.expected_chunk_ids,
                    expected_answer=item.expected_answer,
                    context=item.context,
                )
            )
        if not merged:
            raise ValueError("请至少提供一道问题或一个 Example")
        return merged

    @staticmethod
    def _validate_ground_truth(questions: list[TestQuestion]) -> None:
        """确保每道题至少标注一个期望文档或期望分段。

        命中率是检索结果与标准答案集合的比较指标；没有标准答案时不能把“召回了
        任意内容”解释为命中，否则测试结果会系统性虚高。
        """
        unlabeled = [
            index + 1
            for index, item in enumerate(questions)
            if not item.expected_doc_ids and not item.expected_chunk_ids
        ]
        if unlabeled:
            positions = "、".join(str(index) for index in unlabeled[:10])
            suffix = "等" if len(unlabeled) > 10 else ""
            raise ValueError(f"第 {positions} 题{suffix}未配置期望文档或期望分段，无法计算真实命中率")

    async def _calculate_mrr(self, run_id: uuid.UUID) -> float | None:
        """
        计算 Mean Reciprocal Rank (MRR)

        参数:
            run_id: 测试运行 ID

        返回:
            MRR 值，无结果时返回 None
        """
        # 查询测试结果
        query = select(TestResults).where(TestResults.run_id == run_id)
        result = await self.db.execute(query)
        results = result.scalars().all()

        if not results:
            return None

        # 计算 MRR
        reciprocal_ranks = []
        for result_item in results:
            if result_item.hit_rank and result_item.hit_rank > 0:
                reciprocal_ranks.append(1.0 / result_item.hit_rank)
            else:
                reciprocal_ranks.append(0.0)

        return sum(reciprocal_ranks) / len(reciprocal_ranks)

    async def _convert_case_to_response(self, case: Any) -> TestCaseResponse:
        """
        将数据库模型转换为测试用例响应

        参数:
            case: 测试用例数据库记录

        返回:
            测试用例响应
        """
        # 查询关联的问题列表
        query = select(TestQuestions).where(TestQuestions.case_id == case.id).order_by(TestQuestions.sort_order)
        result = await self.db.execute(query)
        db_questions = result.scalars().all()

        questions = [
            TestQuestion(
                question=q.question,
                expected_doc_ids=q.expected_doc_ids,
                expected_chunk_ids=q.expected_chunk_ids,
                expected_answer=getattr(q, "expected_answer", None),
                context=getattr(q, "context", None),
            )
            for q in db_questions
        ]
        examples = [
            TestExample(
                question=q.question,
                expected_answer=q.expected_answer,
                context=q.context,
                expected_doc_ids=q.expected_doc_ids,
                expected_chunk_ids=q.expected_chunk_ids,
            )
            for q in questions
        ]

        return TestCaseResponse(
            id=case.id,
            name=case.name,
            description=case.description,
            question_count=case.question_count,
            questions=questions,
            examples=examples,
            created_at=case.created_at,
        )

    def _convert_run_to_response(
        self,
        run: Any,
        *,
        avg_relevance: float | None = None,
    ) -> TestRunResponse:
        """
        将数据库模型转换为测试运行响应

        参数:
            run: 测试运行数据库记录
            avg_relevance: 可选，执行时已算好的平均相关度；缺省则从明细回算

        返回:
            测试运行响应
        """
        hit_rate = (run.hit_count / run.total_questions) if run.total_questions else None
        score = avg_relevance
        if score is None:
            score = getattr(run, "_avg_relevance_score", None)
        if score is None:
            result_rows = list(getattr(run, "results", None) or [])
            relevance_scores = [float(item.score) for item in result_rows if getattr(item, "score", None) is not None]
            if relevance_scores:
                score = sum(relevance_scores) / len(relevance_scores)
            elif run.total_questions:
                score = 0.0
        if score is not None:
            score = round(float(score), 6)
        return TestRunResponse(
            id=run.id,
            case_id=run.case_id,
            kb_ids=run.kb_ids,
            strategy=run.strategy,
            top_k=run.top_k,
            status=run.status,
            total_questions=run.total_questions,
            hit_count=run.hit_count,
            hit_rate=hit_rate,
            # 综合得分 = 命中片段相关度均值；命中率见 hit_rate / 命中列。
            score=score,
            recall_at_k=run.recall_at_k,
            mrr=run.mrr,
            avg_elapsed_ms=run.avg_elapsed_ms,
            created_at=getattr(run, "created_at", None),
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
        actual_chunks = []
        for chunk in result.actual_chunks or []:
            if isinstance(chunk, dict):
                actual_chunks.append(chunk)
                continue
            try:
                actual_chunks.append(json.loads(chunk))
            except (TypeError, json.JSONDecodeError):
                actual_chunks.append({"content": str(chunk)})
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

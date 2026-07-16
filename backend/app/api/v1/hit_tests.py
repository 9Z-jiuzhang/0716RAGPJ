"""命中率测试 API。"""

import uuid
from typing import Any

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.schemas.common import BaseResponse
from app.schemas.hit_tests import (
    CompareTestRequest,
    CreateTestCaseRequest,
    TestRunRequest,
    UpdateTestCaseRequest,
)
from app.services.hit_test_service import HitTestService
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/hit-tests", tags=["命中率测试"])


@router.get("/cases", response_model=BaseResponse)
async def list_test_cases(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:read")),
) -> BaseResponse:
    """
    获取测试用例列表（分页）

    需要 test:read 权限。分页查询命中率测试用例集。
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    service = HitTestService(db)
    result = await service.list_test_cases(page=page, page_size=page_size)

    return BaseResponse(data=result)


@router.post("/cases", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    request: CreateTestCaseRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:write")),
) -> BaseResponse:
    """
    创建测试用例

    需要 test:write 权限。创建含期望文档/分段的问题集。
    """
    if not request.questions or len(request.questions) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="问题列表不能为空",
        )

    service = HitTestService(db)
    case = await service.create_test_case(request=request)

    return BaseResponse(data=case)


@router.put("/cases/{id}", response_model=BaseResponse)
async def update_test_case(
    id: uuid.UUID,
    request: UpdateTestCaseRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:write")),
) -> BaseResponse:
    """
    更新测试用例

    需要 test:write 权限。更新用例名称、描述或问题列表。
    """
    if not request.name and not request.description and request.questions is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="至少需要提供一个更新字段",
        )

    service = HitTestService(db)
    case = await service.update_test_case(case_id=id, request=request)

    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试用例不存在",
        )

    return BaseResponse(data=case)


@router.delete("/cases/{id}", response_model=BaseResponse)
async def delete_test_case(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:write")),
) -> BaseResponse:
    """
    删除测试用例

    需要 test:write 权限。删除用例集及其关联的问题记录。
    """
    service = HitTestService(db)
    success = await service.delete_test_case(case_id=id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试用例不存在",
        )

    return BaseResponse(message="删除成功")


@router.post("/runs", response_model=BaseResponse, status_code=status.HTTP_202_ACCEPTED)
async def execute_test_run(
    request: TestRunRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:write")),
) -> BaseResponse:
    """
    执行命中率测试

    需要 test:write 权限。基于用例集或临时 questions 执行测试，异步执行。
    只能测试当前用户有权限访问的知识库范围。
    """
    if not request.case_id and not request.questions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="必须提供 case_id 或 questions",
        )

    if request.questions and len(request.questions) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="questions 列表不能为空",
        )

    service = HitTestService(db)
    from app.services.langfuse_service import get_langfuse

    lf = get_langfuse()
    trace = lf.start_trace(
        name="hit_test_run",
        user_id=str(getattr(user, "id", "")),
        metadata={"case_id": str(request.case_id) if request.case_id else None},
    )
    run = await service.execute_test_run(request=request)
    lf.span_retrieval(
        trace,
        query=f"hit_test case={request.case_id}",
        context_summary=f"run_id={getattr(run, 'id', run)}",
        hit_count=0,
    )
    lf.flush()

    return BaseResponse(data=run)


@router.post("/compare", response_model=BaseResponse)
async def compare_test_strategies(
    request: CompareTestRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:write")),
) -> BaseResponse:
    """同一问题集在不同检索策略下并排对比命中率。"""
    if len(set(request.strategies)) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="strategies 至少包含两种不同策略",
        )
    service = HitTestService(db)
    try:
        result = await service.compare_strategies(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return BaseResponse(data=result)


@router.get("/runs", response_model=BaseResponse)
async def list_test_runs(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:read")),
) -> BaseResponse:
    """
    获取测试运行记录列表（分页）

    需要 test:read 权限。分页查询历史测试运行记录。
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    service = HitTestService(db)
    result = await service.list_test_runs(page=page, page_size=page_size)

    return BaseResponse(data=result)


@router.get("/runs/{id}", response_model=BaseResponse)
async def get_test_run(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:read")),
) -> BaseResponse:
    """
    获取测试运行详情

    需要 test:read 权限。返回测试运行汇总统计及各题命中明细。
    """
    service = HitTestService(db)
    run = await service.get_test_run(run_id=id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试运行记录不存在",
        )

    return BaseResponse(data=run)


@router.get("/runs/{id}/export", response_class=PlainTextResponse)
async def export_test_run_csv(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_permission("test:read")),
) -> Any:
    """
    导出测试结果为 CSV

    需要 test:read 权限。下载测试运行结果的 CSV 文件。
    """
    service = HitTestService(db)
    csv_content = await service.export_test_run_csv(run_id=id)

    if not csv_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试运行记录不存在",
        )

    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=hit_test_run_{id}.csv",
        },
    )

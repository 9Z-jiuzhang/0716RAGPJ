from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db, require_permission
from app.schemas.common import StandardResponse
from app.schemas.hit_tests import (
    CreateTestCaseRequest,
    TestCaseListResponse,
    TestCaseResponse,
    TestRunListResponse,
    TestRunRequest,
    TestRunResponse,
    UpdateTestCaseRequest,
)
from app.services.hit_test_service import HitTestService
from app.utils.response import success_response

router = APIRouter(prefix="/hit-tests", tags=["命中率测试"])


@router.get("/cases", response_model=StandardResponse[TestCaseListResponse])
def list_test_cases(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _=Depends(require_permission("test:read")),
) -> StandardResponse[TestCaseListResponse]:
    """
    获取测试用例列表（分页）

    需要 test:read 权限。分页查询命中率测试用例集。
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    service = HitTestService(db)
    result = service.list_test_cases(page=page, page_size=page_size)

    return success_response(data=result)


@router.post(
    "/cases",
    response_model=StandardResponse[TestCaseResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_test_case(
    request: CreateTestCaseRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _=Depends(require_permission("test:write")),
) -> StandardResponse[TestCaseResponse]:
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
    case = service.create_test_case(request=request)

    return success_response(data=case)


@router.put("/cases/{id}", response_model=StandardResponse[TestCaseResponse])
def update_test_case(
    id: UUID,
    request: UpdateTestCaseRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _=Depends(require_permission("test:write")),
) -> StandardResponse[TestCaseResponse]:
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
    case = service.update_test_case(case_id=id, request=request)

    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试用例不存在",
        )

    return success_response(data=case)


@router.delete("/cases/{id}", response_model=StandardResponse[None])
def delete_test_case(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _=Depends(require_permission("test:write")),
) -> StandardResponse[None]:
    """
    删除测试用例

    需要 test:write 权限。删除用例集及其关联的问题记录。
    """
    service = HitTestService(db)
    success = service.delete_test_case(case_id=id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试用例不存在",
        )

    return success_response(message="删除成功")


@router.post(
    "/runs",
    response_model=StandardResponse[TestRunResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_test_run(
    request: TestRunRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _=Depends(require_permission("test:write")),
) -> StandardResponse[TestRunResponse]:
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
    run = service.execute_test_run(request=request)

    return success_response(data=run)


@router.get("/runs", response_model=StandardResponse[TestRunListResponse])
def list_test_runs(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _=Depends(require_permission("test:read")),
) -> StandardResponse[TestRunListResponse]:
    """
    获取测试运行记录列表（分页）

    需要 test:read 权限。分页查询历史测试运行记录。
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    service = HitTestService(db)
    result = service.list_test_runs(page=page, page_size=page_size)

    return success_response(data=result)


@router.get("/runs/{id}", response_model=StandardResponse[dict])
def get_test_run(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _=Depends(require_permission("test:read")),
) -> StandardResponse[dict]:
    """
    获取测试运行详情

    需要 test:read 权限。返回测试运行汇总统计及各题命中明细。
    """
    service = HitTestService(db)
    run = service.get_test_run(run_id=id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测试运行记录不存在",
        )

    return success_response(data=run)


@router.get("/runs/{id}/export", response_class=PlainTextResponse)
def export_test_run_csv(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    _=Depends(require_permission("test:read")),
) -> Any:
    """
    导出测试结果为 CSV

    需要 test:read 权限。下载测试运行结果的 CSV 文件。
    """
    service = HitTestService(db)
    csv_content = service.export_test_run_csv(run_id=id)

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

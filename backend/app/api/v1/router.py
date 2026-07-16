"""V1 路由总入口。"""

from fastapi import APIRouter

from .audit import router as audit_router
from .auth import router as auth_router
from .hit_tests import router as hit_tests_router
from .qa import router as qa_router
from .roles import router as roles_router
from .snapshots import router as snapshots_router
from .users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(roles_router)
api_router.include_router(hit_tests_router)
api_router.include_router(snapshots_router)
api_router.include_router(audit_router)
api_router.include_router(qa_router)

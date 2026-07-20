"""V1 路由总入口。"""

from fastapi import APIRouter

from .audit import router as audit_router
from .auth import router as auth_router
from .departments import router as departments_router
from .hit_tests import router as hit_tests_router
from .models import router as models_router
from .monitor import router as monitor_router
from .qa import router as qa_router
from .ragas import router as ragas_router
from .role_caches import router as role_caches_router
from .roles import router as roles_router
from .snapshots import router as snapshots_router
from .users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(roles_router)
api_router.include_router(departments_router)
api_router.include_router(models_router)
api_router.include_router(hit_tests_router)
api_router.include_router(snapshots_router)
api_router.include_router(audit_router)
api_router.include_router(monitor_router)
api_router.include_router(qa_router)
api_router.include_router(ragas_router)
api_router.include_router(role_caches_router)

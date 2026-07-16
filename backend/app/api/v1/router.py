"""v1 路由注册入口。"""

from fastapi import APIRouter

from app.api.v1.audit import router as audit_router
from app.api.v1.snapshots import router as snapshots_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(snapshots_router)
api_router.include_router(audit_router)
